"""Complete, discoverable REST GET coverage from a pinned OpenAPI manifest.

Every operation has a SQL function in ``github.rest``. Path arguments are
positional (and LATERAL-composable); ``query`` is a JSON object containing the
documented query parameters. One output row preserves one whole response page,
including nested fields, scalars, HTTP status and non-JSON bodies.
"""

from __future__ import annotations

import json
import keyword
import re
from dataclasses import make_dataclass
from importlib.resources import files
from typing import Annotated, Any

import pyarrow as pa
from vgi.arguments import Arg, SecretLookupEntry
from vgi.cache_control import CacheControl
from vgi.invocation import BindResponse
from vgi.table_function import TableFunctionGenerator, init_single_worker
from vgi.table_in_out_function import RowTransformFunction

from vgi_github import auth
from vgi_github import github_api as api
from vgi_github.caching import result_cache_control
from vgi_github.client_log import emitter
from vgi_github.meta import docs, examples, field, keywords
from vgi_github.schemas import batch_from_rows

MANIFEST = json.loads(files("vgi_github").joinpath("rest_manifest.json").read_text())
OPERATIONS = {op["operation_id"]: op for op in MANIFEST["operations"]}
API_VERSION: str = MANIFEST["api_version"]
_PARAMETER = re.compile(r"\{([^}]+)\}")

RESPONSE_SCHEMA = pa.schema(
    [
        field("operation_id", pa.string(), "GitHub's OpenAPI operation identifier."),
        field("page_number", pa.int64(), "Response page within this invocation, starting at 1."),
        field("status_code", pa.int64(), "HTTP status, including 202 pending and 204 empty responses."),
        field("content_type", pa.string(), "Response media type as returned by GitHub."),
        field(
            "data",
            pa.string(),
            "Complete JSON response as text; use DuckDB JSON functions to extract fields.",
        ),
        field("body", pa.binary(), "Exact response bytes, including archives, logs, diffs and raw files."),
        field(
            "next_url",
            pa.string(),
            "Next page URL, or NULL. Non-NULL on the last row means more pages exist.",
        ),
    ]
)

ENDPOINT_SCHEMA = pa.schema(
    [
        field("operation_id", pa.string(), "GitHub OpenAPI operation identifier accepted by api.rest()."),
        field("function_name", pa.string(), "SQL function name in the rest schema."),
        field("method", pa.string(), "Always GET; no REST write operations are registered."),
        field("path", pa.string(), "REST path template; placeholders are positional SQL arguments in order."),
        field("category", pa.string(), "GitHub API category."),
        field("summary", pa.string(), "GitHub's short operation description."),
        field("parameters", pa.string(), "JSON parameter definitions, including required flags and schemas."),
        field(
            "products",
            pa.list_(pa.string()),
            "GitHub products whose pinned specification contains this operation.",
        ),
        field("documentation_url", pa.string(), "Official documentation for this endpoint."),
        field("deprecated", pa.bool_(), "Whether GitHub marks the operation deprecated."),
    ]
)


def json_object(value: str, label: str) -> dict[str, Any]:
    """Decode parameter JSON without accepting arrays, scalars or non-finite numbers."""

    def invalid_constant(constant: str) -> None:
        raise ValueError(f"non-finite number {constant}")

    try:
        result = json.loads(value, parse_constant=invalid_constant)
    except (ValueError, TypeError) as exc:
        raise api.GitHubInputError(f"{label} must be a JSON object: {exc}") from exc
    if not isinstance(result, dict):
        raise api.GitHubInputError(f"{label} must be a JSON object")
    return result


def _path_value(value: Any) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise api.GitHubInputError("Path parameters must be strings or integers")
    text = str(value)
    # Check each component even though slashes are encoded: upstream routers
    # can decode them before resolving a path. '%' stays encoded as literal data.
    if any(part in (".", "..") for part in text.replace("\\", "/").split("/")):
        raise api.GitHubInputError("Path parameters cannot contain dot segments")
    return api.segment(text)


def request_arguments(operation: dict, path_values: dict, query: dict) -> tuple[str, list[tuple[str, Any]]]:
    """Build a GET path exclusively from a known template and encoded parameters."""
    names = set(_PARAMETER.findall(operation["path"]))
    if set(path_values) != names:
        raise api.GitHubInputError(f"{operation['operation_id']} requires path parameters {sorted(names)}")
    path = _PARAMETER.sub(lambda match: _path_value(path_values[match[1]]), operation["path"])
    declared = {p["name"]: p for p in operation["parameters"] if p["in"] == "query"}
    unknown = set(query) - declared.keys()
    if unknown:
        raise api.GitHubInputError(f"Unknown query parameters: {', '.join(sorted(unknown))}")
    for name, definition in declared.items():
        if definition.get("required") and query.get(name) is None:
            raise api.GitHubInputError(f"Required query parameter: {name}")
    pairs = []
    for name, value in query.items():
        if value is None:
            continue
        if isinstance(value, dict) or (
            isinstance(value, list) and any(isinstance(v, (dict, list)) for v in value)
        ):
            raise api.GitHubInputError(f"Query parameter {name} must be a scalar or array of scalars")
        definition = declared[name]
        if isinstance(value, list):
            if definition.get("explode", True):
                pairs.extend((name, item) for item in value)
            else:
                pairs.append(
                    (
                        name,
                        ",".join(
                            str(item).lower() if isinstance(item, bool) else str(item) for item in value
                        ),
                    )
                )
        else:
            pairs.append((name, value))
    return path, pairs


def response_row(
    response: api.Response, operation_id: str, page_number: int, *, accept: str = api.ACCEPT_JSON
) -> dict[str, Any]:
    data = None
    # GitHub can label raw file bytes as application/vnd.github.raw+json (and
    # sometimes application/json). The selected representation takes precedence
    # over that misleading suffix. Binary downloads need no Content-Type header.
    raw_media = any(f"application/vnd.github.{kind}" in accept for kind in ("raw", "diff", "patch", "sha"))
    media = response.content_type.lower().split(";", 1)[0].strip()
    expects_json = (media == "application/json" or media.endswith("+json")) and not raw_media
    if response.body and (expects_json or not response.content_type):
        try:
            # Preserve JSON text exactly, including integers beyond BIGINT.
            data = response.body.decode("utf-8")
            json.loads(data)
        except (ValueError, UnicodeError) as exc:
            data = None
            if expects_json:
                raise api.GitHubError(
                    response.status, operation_id, "GitHub returned malformed JSON"
                ) from exc
    return {
        "operation_id": operation_id,
        "page_number": page_number,
        "status_code": response.status,
        "content_type": response.content_type,
        "data": data,
        "body": response.body,
        "next_url": response.next_url,
    }


def fetch(operation: dict, path_values: dict, args: Any, credentials: Any, hint: api.CacheHint) -> list[dict]:
    """Read bounded pages; an explicit next_url makes partial walks visible."""
    if operation["method"] != "GET":
        raise api.GitHubInputError("Only GET operations are permitted")
    path, query = request_arguments(operation, path_values, json_object(args.query, "query"))
    if args.max_pages < 0 or args.max_pages > api.MAX_PAGES:
        raise api.GitHubInputError(f"max_pages must be between 0 and {api.MAX_PAGES}")
    if any(c in args.accept + args.api_version for c in "\r\n"):
        raise api.GitHubInputError("Media type and API version cannot contain newlines")
    if api.reporting_enabled() and args.max_pages != 0:
        raise api.GitHubReportingError("REST reporting requires max_pages => 0")
    rows = []
    target = path
    visited = set()
    for index in range(args.max_pages or api.MAX_PAGES):
        api.remaining_time()
        if target in visited:
            raise api.GitHubError(0, path, "Repeated pagination URL")
        visited.add(target)
        response = api._get(
            target,
            query if index == 0 else None,
            credentials=credentials,
            hint=hint,
            accept=args.accept,
            raw=True,
            api_version=args.api_version,
            allow_not_found=args.allow_not_found,
        )
        row = response_row(response, operation["operation_id"], index + 1, accept=args.accept)
        rows.append(row)
        if args.max_pages == 0 and row["data"]:
            payload = json.loads(row["data"])
            if isinstance(payload, dict):
                if payload.get("incomplete_results"):
                    raise api.GitHubReportingError("GitHub returned incomplete results; narrow the query")
                if operation["path"].startswith("/search/") and payload.get("total_count", 0) > 1000:
                    raise api.GitHubReportingError("GitHub search caps results at 1,000; narrow the query")
                if operation["path"].endswith("/git/trees/{tree_sha}") and payload.get("truncated"):
                    raise api.GitHubReportingError(
                        "GitHub truncated this tree; query its subtrees separately"
                    )
        if not response.next_url:
            return rows
        target = response.next_url
    if args.max_pages == 0:
        raise api.GitHubPageLimitError(path, len(rows))
    return rows


def common_arguments() -> list[tuple]:
    return [
        (
            "query",
            Annotated[str, Arg("query", default="{}", doc="JSON object of documented query parameters")],
            "{}",
        ),
        (
            "max_pages",
            Annotated[
                int,
                Arg(
                    "max_pages",
                    default=1,
                    ge=0,
                    le=api.MAX_PAGES,
                    doc="Response pages per input: default 1; 0 follows all, at most 100",
                ),
            ],
            1,
        ),
        (
            "accept",
            Annotated[
                str,
                Arg(
                    "accept",
                    default=api.ACCEPT_JSON,
                    doc="Media type, e.g. application/vnd.github.diff or application/octet-stream",
                ),
            ],
            api.ACCEPT_JSON,
        ),
        (
            "api_version",
            Annotated[
                str,
                Arg(
                    "api_version",
                    default=API_VERSION,
                    doc="GitHub REST API version; override for an Enterprise Server",
                ),
            ],
            API_VERSION,
        ),
        (
            "allow_not_found",
            Annotated[
                bool,
                Arg(
                    "allow_not_found",
                    default=False,
                    doc="Return HTTP 404 as a response row for membership/existence checks",
                ),
            ],
            False,
        ),
        (
            "cache_ttl",
            Annotated[
                int | None,
                Arg(
                    "cache_ttl",
                    default=None,
                    ge=0,
                    doc="Cache seconds; omitted inherits ATTACH, 0 uses GitHub policy",
                ),
            ],
            None,
        ),
    ]


def _bind(cls, params):
    return BindResponse(output_schema=cls.FIXED_SCHEMA)


def _process_rows(cls, params, state, batch, out):
    rows, parents, fetched = [], [], {}
    hint = api.CacheHint()
    with api.reporting_operation(params.attach_opaque_data), api.reporting_to(emitter(out)):
        credentials = auth.for_call(params.secrets, params.attach_opaque_data)
        for index, values in enumerate(
            zip(*(batch.column(name).to_pylist() for name in cls.INPUT_NAMES), strict=True)
        ):
            api.remaining_time()
            if any(value is None for value in values):
                if api.reporting_enabled():
                    raise api.GitHubReportingError("REST reporting source keys must not be NULL")
                continue
            if values not in fetched:
                if cls.OPERATION is None:
                    identity, encoded_paths = values
                    if identity not in OPERATIONS:
                        raise api.GitHubInputError(f"Unknown read operation {identity!r}; see api.endpoints")
                    operation = OPERATIONS[identity]
                    paths = json_object(encoded_paths, "path_parameters")
                else:
                    operation = cls.OPERATION
                    paths = dict(zip(cls.PATH_NAMES, values, strict=True))
                fetched[values] = fetch(operation, paths, params.args, credentials, hint)
            found = fetched[values]
            rows.extend(found)
            parents.extend([index] * len(found))
        out.emit(
            batch_from_rows(rows, params.output_schema),
            parent_rows=parents,
            cache_control=result_cache_control(
                hint, params.args.cache_ttl, params.attach_opaque_data, per_value=True
            ),
        )


def _process_scan(cls, params, state, out):
    hint = api.CacheHint()
    with api.reporting_operation(params.attach_opaque_data), api.reporting_to(emitter(out)):
        credentials = auth.for_call(params.secrets, params.attach_opaque_data)
        rows = fetch(cls.OPERATION, {}, params.args, credentials, hint)
        out.emit(
            batch_from_rows(rows, params.output_schema),
            cache_control=result_cache_control(hint, params.args.cache_ttl, params.attach_opaque_data),
        )
    out.finish()


def _identifier(name: str) -> str:
    result = re.sub(r"\W", "_", name)
    return result + "_" if keyword.iskeyword(result) else result


def make_function(operation: dict | None) -> type:
    """Generate real VGI declarations, including positional signatures and docs."""
    if operation:
        name = operation["function_name"]
        path_names = _PARAMETER.findall(operation["path"])
        description = operation["summary"]
        parameters = {p["name"]: p for p in operation["parameters"] if p["in"] == "path"}
        argument_specs = [
            (
                _identifier(n),
                int if parameters[n].get("schema", {}).get("type") == "integer" else str,
                # Add its role to short upstream glosses, which can otherwise
                # duplicate the operation summary without explaining the input.
                "Path value identifying the resource: "
                + re.sub(r"\bUUID\b", "unique identifier", parameters[n].get("description", n)),
            )
            for n in path_names
        ]
    else:
        name, path_names, description = "rest", [], "Call a documented GitHub REST GET operation by ID"
        argument_specs = [
            ("operation_id", str, "Read operation from api.endpoints, e.g. pulls/list-reviews"),
            ("path_parameters", str, "JSON object of path parameters, e.g. owner, repo, pull_number"),
        ]
    fields = [
        (n, Annotated[kind, Arg(index, doc=doc)]) for index, (n, kind, doc) in enumerate(argument_specs)
    ]
    args = make_dataclass(f"{name}Args", [*fields, *common_arguments()], kw_only=True, frozen=True)
    input_names = [n for n, _, _ in argument_specs]
    prose = (
        f"{description}. Returns one row per HTTP response page; data contains the complete JSON "
        "and body the exact bytes. Use json_each(data) for array responses. Path arguments support "
        "LATERAL. Pass documented filters in query as JSON. Default max_pages=1; next_url indicates "
        "more data. max_pages=0 follows Link headers, bounded at 100 pages. GitHub permissions, "
        "product availability and endpoint-specific limits still apply. No write operation is available."
    )
    if operation:
        prose += f" See [GitHub's endpoint documentation]({operation['documentation_url']})."
    md = prose + "\n\n### Parameters and results\n\n"
    if operation:
        md += (
            "Path arguments follow the order in the published SQL signature. "
            "Find the full query-parameter definitions in `github.api.endpoints.parameters` "
            f"for operation `{operation['operation_id']}`. "
            "Use `json_each(data)` to expand array responses, or `data::JSON ->> 'field'` "
            "to select an object field. Downloads are available in `body`."
        )
    else:
        md += "Discover operation IDs and their path/query parameters in `github.api.endpoints`."
    meta = type(
        "Meta",
        (),
        {
            "name": name,
            "description": description,
            "categories": ["rest"],
            "required_secrets": [SecretLookupEntry(secret_type=auth.SECRET_TYPE)],
            "projection_pushdown": True,
            "tags": docs(
                category="rest",
                llm=prose,
                md=md,
                result_schema=RESPONSE_SCHEMA,
                example_queries=examples(
                    (
                        "Read complete repository metadata through the GET dispatcher",
                        "SELECT data::JSON ->> 'full_name' AS full_name FROM github.api.rest("
                        '\'repos/get\', \'{"owner":"duckdb","repo":"duckdb"}\')',
                    )
                )
                if operation is None
                else None,
            ),
        },
    )
    namespace = {
        "__module__": __name__,
        "__doc__": prose,
        "Meta": meta,
        "FunctionArguments": args,
        "FIXED_SCHEMA": RESPONSE_SCHEMA,
        "OPERATION": operation,
        "INPUT_NAMES": input_names,
        "PATH_NAMES": path_names,
        "on_bind": classmethod(_bind),
        "process": classmethod(_process_rows if input_names else _process_scan),
    }
    base = RowTransformFunction if input_names else TableFunctionGenerator
    result = type(f"{name}Function", (base,), namespace)
    return result if input_names else init_single_worker(result)


REST_FUNCTIONS = [make_function(operation) for operation in OPERATIONS.values()]
RestFunction = make_function(None)


@init_single_worker
class EndpointsFunction(TableFunctionGenerator[None, None]):
    """Local inventory; discovery makes no network requests."""

    FIXED_SCHEMA = ENDPOINT_SCHEMA

    class Meta:
        name = "all_endpoints"
        description = "All documented GitHub REST read operations and their SQL signatures"
        categories = ["rest"]
        projection_pushdown = True
        tags = docs(
            category="rest",
            result_schema=ENDPOINT_SCHEMA,
            llm="Local endpoint inventory. Filter category or summary, "
            "then call rest.function_name or api.rest.",
            md="Pinned GitHub.com and Enterprise Cloud GET operations. "
            "Parameters are JSON; discovery is offline.",
            example_queries=examples(
                (
                    "Discover PR review reads",
                    "SELECT operation_id, path FROM github.api.all_endpoints() WHERE category = 'pulls'",
                )
            ),
            extra={
                "provider": "github",
                "domain": "software-development",
                "vgi.keywords": keywords("REST", "endpoints", "API", "parameters", "OpenAPI"),
            },
        )

    @classmethod
    def on_bind(cls, params):
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(cls, params, state, out):
        rows = [{**op, "parameters": json.dumps(op["parameters"])} for op in OPERATIONS.values()]
        out.emit(batch_from_rows(rows, params.output_schema), cache_control=CacheControl(ttl=86400))
        out.finish()
