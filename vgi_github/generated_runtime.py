"""Generic execution of reviewed, schema-derived GitHub entity contracts.

Only the opt-in generated worker loads these contracts. SQL supplies typed resource
arguments; endpoint paths, GraphQL documents and field mappings come from the
checked-in artifact. Pages are validated and emitted as they arrive.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, make_dataclass
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any

import pyarrow as pa
from vgi.arguments import Arg, SecretLookupEntry
from vgi.cache_control import CacheControl
from vgi.invocation import BindResponse
from vgi.table_function import TableFunctionGenerator, init_single_worker
from vgi_rpc import ArrowSerializableDataclass

from vgi_github import auth
from vgi_github import github_api as api
from vgi_github.client_log import emitter
from vgi_github.meta import docs, field
from vgi_github.rest import _path_value

_MISSING = object()
_PLACEHOLDER = re.compile(r"\{([^}]+)\}")
_SCALARS = {
    "VARCHAR": (pa.string(), str),
    "BIGINT": (pa.int64(), int),
    "INTEGER": (pa.int32(), int),
    "DOUBLE": (pa.float64(), float),
    "FLOAT": (pa.float32(), float),
    "BOOLEAN": (pa.bool_(), bool),
    "DATE": (pa.date32(), date),
    "TIMESTAMP WITH TIME ZONE": (pa.timestamp("us", tz="UTC"), datetime),
}


class GeneratedContractError(api.GitHubReportingError):
    """A generated source cannot satisfy its declared typed entity contract."""


def _arrow_type(schema: dict[str, Any]) -> pa.DataType:
    kind = schema["kind"]
    if kind == "scalar":
        try:
            return _SCALARS[schema["type"]][0]
        except KeyError as exc:
            raise ValueError(f"Unsupported generated scalar type {schema['type']}") from exc
    if kind == "list":
        item = schema["item"]
        return pa.list_(pa.field("item", _arrow_type(item), nullable=item.get("nullable", False)))
    if kind == "struct":
        return pa.struct([_arrow_field(column) for column in schema["fields"]])
    raise ValueError(f"Unsupported generated schema kind {kind!r}")


def _arrow_field(column: dict[str, Any]) -> pa.Field:
    return field(
        column["name"],
        _arrow_type(column["schema"]),
        column.get("description") or column["name"],
        nullable=column.get("nullable", False) or not column.get("required", True),
    )


def _read_path(value: Any, path: list[str], label: str) -> Any:
    for component in path:
        if value is _MISSING:
            return _MISSING
        if value is None:
            # The compiler propagates parent nullability to a flattened column.
            # Its decoder decides whether this explicit NULL is permitted.
            return None
        if not isinstance(value, dict):
            raise GeneratedContractError(f"{label}: expected an object at {component}")
        value = value.get(component, _MISSING)
    return value


def _decode(
    value: Any, schema: dict[str, Any], label: str, *, required: bool = True, nullable: bool | None = None
) -> Any:
    if value is _MISSING:
        if required:
            raise GeneratedContractError(f"{label}: missing required field")
        return None
    if value is None:
        allow_null = schema.get("nullable", False) if nullable is None else nullable
        if allow_null:
            return None
        raise GeneratedContractError(f"{label}: NULL is not allowed")
    kind = schema["kind"]
    if kind == "struct":
        if not isinstance(value, dict):
            raise GeneratedContractError(f"{label}: expected an object")
        return {
            child["name"]: _decode(
                value.get(child["name"], _MISSING),
                child["schema"],
                f"{label}.{child['name']}",
                required=child.get("required", True),
                nullable=child.get("nullable"),
            )
            for child in schema["fields"]
        }
    if kind == "list":
        if not isinstance(value, list):
            raise GeneratedContractError(f"{label}: expected an array")
        return [_decode(item, schema["item"], f"{label}[{index}]") for index, item in enumerate(value)]
    scalar = schema["type"]
    enum_value = value
    valid = False
    if scalar == "VARCHAR":
        valid = isinstance(value, str)
    elif scalar in ("BIGINT", "INTEGER"):
        bits = 64 if scalar == "BIGINT" else 32
        valid = type(value) is int and -(2 ** (bits - 1)) <= value < 2 ** (bits - 1)
    elif scalar in ("DOUBLE", "FLOAT"):
        valid = type(value) in (int, float) and math.isfinite(value)
    elif scalar == "BOOLEAN":
        valid = type(value) is bool
    elif scalar == "DATE" and type(value) is date:
        valid = True
    elif scalar == "TIMESTAMP WITH TIME ZONE" and isinstance(value, datetime):
        valid = value.tzinfo is not None
        if valid:
            value = value.astimezone(UTC)
    elif scalar in ("DATE", "TIMESTAMP WITH TIME ZONE") and isinstance(value, str):
        try:
            if scalar == "DATE":
                value = date.fromisoformat(value)
            else:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if value.tzinfo is None:
                    raise ValueError("missing timezone")
                value = value.astimezone(UTC)
            valid = True
        except ValueError:
            valid = False
    if not valid:
        raise GeneratedContractError(f"{label}: invalid {scalar} value")
    if "enum" in schema and enum_value not in schema["enum"]:
        raise GeneratedContractError(f"{label}: value is outside the declared enum")
    return value


def _binding(binding: dict[str, Any], arguments: dict[str, Any], cursor: str | None = None) -> Any:
    if "object" in binding:
        return {name: _binding(value, arguments, cursor) for name, value in binding["object"].items()}
    if "literal" in binding:
        return binding["literal"]
    if binding.get("cursor") is True:
        return cursor
    value = arguments[binding["argument"]]
    transform = binding.get("transform")
    if transform:
        if transform not in ("repository_owner", "repository_name"):
            raise ValueError(f"Unsupported generated argument transform {transform!r}")
        owner, name = api.split_repo(value)
        return owner if transform == "repository_owner" else name
    return value


def _page(
    entity: dict[str, Any], arguments: dict[str, Any], credentials: Any, cursor: dict[str, Any]
) -> list[Any]:
    """Fetch exactly one page; the serializable cursor contains no result payload."""
    transport = entity["transport"]
    kind = transport["kind"]
    pagination = transport["pagination"]
    page = cursor.get("page", 0)
    api.remaining_time()
    if kind == "rest":
        if transport.get("method", "GET") != "GET" or pagination["kind"] not in ("link", "none"):
            raise ValueError("Generated REST contracts require GET and reviewed pagination")
        bindings = transport["path_bindings"]
        path = transport["path"]
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Generated REST path must be relative to the GitHub API")
        if set(_PLACEHOLDER.findall(path)) != set(bindings):
            raise ValueError("Generated REST path bindings do not match its placeholders")
        target = cursor.get("next_url") or _PLACEHOLDER.sub(
            lambda match: _path_value(_binding(bindings[match[1]], arguments)), path
        )
        query = {
            name: _binding(binding, arguments)
            for name, binding in transport.get("query_bindings", {}).items()
        }
        query.setdefault("per_page", api.PER_PAGE)
        seen = cursor.setdefault("visited", [])
        if target in seen:
            raise GeneratedContractError(f"{entity['name']}: repeated pagination URL")
        seen.append(target)
        response = api._get(
            target,
            query if page == 0 else None,
            credentials=credentials,
            api_version=transport.get("api_version", api.API_VERSION),
        )
        rows = _read_path(response.payload, transport["result_path"], entity["name"])
        if transport.get("result_shape", "array") == "object":
            if not isinstance(rows, dict):
                raise GeneratedContractError(f"{entity['name']}: expected an entity object")
            rows = [rows]
        elif not isinstance(rows, list):
            raise GeneratedContractError(f"{entity['name']}: expected an entity array")
        cursor["next_url"] = response.next_url
        cursor["done"] = pagination["kind"] == "none" or not response.next_url
    elif kind == "graphql":
        if pagination["kind"] != "cursor":
            raise ValueError("Generated GraphQL contracts require cursor pagination")
        variables = {
            name: _binding(binding, arguments, cursor.get("cursor"))
            for name, binding in transport["variables"].items()
        }
        response = api.graphql_query(
            transport["document"],
            variables,
            operation_name=transport.get("operation_name"),
            credentials=credentials,
        )
        data = response.get("data")
        if not isinstance(data, dict):
            raise GeneratedContractError(f"{entity['name']}: missing GraphQL query data")
        rows = _read_path(data, transport["result_path"], entity["name"])
        info = _read_path(data, pagination["page_info_path"], entity["name"])
        if (
            not isinstance(rows, list)
            or not isinstance(info, dict)
            or type(info.get("hasNextPage")) is not bool
        ):
            raise GeneratedContractError(f"{entity['name']}: malformed GraphQL connection/pageInfo")
        following = info.get("endCursor")
        seen = cursor.setdefault("visited", [])
        if info["hasNextPage"] and (not isinstance(following, str) or not following or following in seen):
            raise GeneratedContractError(f"{entity['name']}: missing or repeated pagination cursor")
        if following is not None:
            seen.append(following)
        cursor["cursor"] = following
        cursor["done"] = not info["hasNextPage"]
    else:
        raise ValueError(f"Unsupported generated transport {kind!r}")
    cursor["page"] = page + 1
    return rows


def _bind(cls: type, params: Any) -> BindResponse:
    return BindResponse(output_schema=cls.FIXED_SCHEMA)


@dataclass(kw_only=True)
class GeneratedScanState(ArrowSerializableDataclass):
    """One page at each traversal depth, pagination cursors and row identities."""

    cursor_json: str = ""
    deadline: float = 0.0
    done: bool = False


class _GeneratedProducer(TableFunctionGenerator[Any, GeneratedScanState]):
    """Give dynamically generated classes a resolvable, serializable state type."""


def _initial_state(cls: type, params: Any) -> GeneratedScanState:
    arguments = {
        definition["name"]: _decode(
            getattr(params.args, definition["name"], definition.get("default", _MISSING)),
            definition.get("schema", {"kind": "scalar", "type": definition["type"]}),
            f"{cls.ENTITY['name']}.{definition['name']}",
            nullable=definition.get("nullable", False),
        )
        for definition in cls.ARGUMENTS
    }
    cohort = cls.ENTITY.get("cohort")
    cohort_values = None
    if cohort:
        supplied = arguments[cohort["parameter"]]
        alternatives = [*cohort["alternatives"], cohort["parameter"]]
        if sum(arguments.get(name) is not None for name in alternatives) != 1:
            raise GeneratedContractError(f"Specify exactly one of {', '.join(alternatives)}")
        if supplied is not None:
            for stage in cls.TRAVERSAL["stages"]:
                scope = cls.SCOPES.get(stage.get("scope"), {})
                for name, required in scope.get("requires_parameters", {}).items():
                    if arguments.get(name) is not None and any(arguments.get(other) is None for other in required):
                        raise GeneratedContractError(f"{name} requires {', '.join(required)}")
            cohort_values = [row[cohort["field"]] for row in supplied]
            identities = set()
            for value in cohort_values:
                if not value.strip():
                    raise GeneratedContractError(f"{cohort['parameter']}: empty resource argument")
                if cohort.get("resource") == "repository":
                    api.split_repo(value)
                if value.casefold() in identities:
                    raise GeneratedContractError(f"{cohort['parameter']}: duplicate resource argument")
                identities.add(value.casefold())
            if cohort_values:
                arguments[cohort["argument"]] = cohort_values[0]
            # The typed argument is retained once, in the continuation state.
            arguments[cohort["parameter"]] = None
    for stage in cls.TRAVERSAL["stages"] if cls.TRAVERSAL else []:
        scope = cls.SCOPES.get(stage.get("scope"), {})
        exclusive = scope.get("exclusive_parameters", [])
        if exclusive and cohort_values != [] and sum(arguments.get(name) is not None for name in exclusive) != 1:
            raise GeneratedContractError(f"Specify exactly one of {', '.join(exclusive)}")
        for name, required in scope.get("requires_parameters", {}).items():
            if arguments.get(name) is not None and any(arguments.get(other) is None for other in required):
                raise GeneratedContractError(f"{name} requires {', '.join(required)}")
    for definition in cls.ARGUMENTS:
        name = definition["name"]
        value = arguments[name]
        if value is not None and "min_length" in definition and len(value.strip()) < definition["min_length"]:
            raise GeneratedContractError(f"{name}: empty resource argument")
        if value is not None and "minimum" in definition and value < definition["minimum"]:
            raise GeneratedContractError(f"{name}: must be at least {definition['minimum']}")
    return GeneratedScanState(
        cursor_json=json.dumps({"arguments": arguments, "frames": [], "seen": [],
                                "cohort_values": cohort_values, "cohort_index": 0}),
        done=cohort_values == [],
    )


def _decode_rows(
    entity: dict[str, Any], arguments: dict[str, Any], payloads: list[Any]
) -> list[dict[str, Any]]:
    rows = []
    for payload in payloads:
        api.remaining_time()
        if not isinstance(payload, dict):
            raise GeneratedContractError(f"{entity['name']}: expected an entity object")
        row = {}
        for column in entity["columns"]:
            label = f"{entity['name']}.{column['name']}"
            value = (
                arguments[column["source_argument"]]
                if "source_argument" in column
                else _read_path(payload, column["path"], label)
            )
            row[column["name"]] = _decode(
                value,
                column["schema"],
                label,
                required=column.get("required", True),
                nullable=column.get("nullable", False),
            )
        for assertion in entity.get("policy", {}).get("row_assertions", []):
            if assertion["comparison"] != "github_login":
                raise ValueError("Unsupported generated row assertion comparison")
            actual = row[assertion["column"]]
            expected = arguments[assertion["argument"]]
            if (
                not isinstance(actual, str)
                or not isinstance(expected, str)
                or actual.casefold() != expected.casefold()
            ):
                raise GeneratedContractError(
                    f"{entity['name']}: row assertion failed: "
                    f"{assertion['column']} must match {assertion['argument']}"
                )
        rows.append(row)
    return rows


def _identity(entity: dict[str, Any], row: dict[str, Any]) -> str:
    values = [row[name] for name in entity["grain"]]
    if any(value is None or (isinstance(value, str) and not value.strip()) for value in values):
        raise GeneratedContractError(f"{entity['name']}: NULL or empty row identity")
    if any(isinstance(value, (dict, list)) for value in values):
        raise ValueError("Generated entity grain must contain scalar columns")
    return json.dumps(values, default=str, separators=(",", ":"))


def _unique_rows(entity: dict[str, Any], rows: list[dict[str, Any]], seen: list[str]) -> None:
    """Validate identities across pages without imposing a result-size policy."""
    identities = set(seen)
    for row in rows:
        identity = _identity(entity, row)
        if identity in identities:
            raise GeneratedContractError(f"{entity['name']}: duplicate row identity")
        identities.add(identity)
        seen.append(identity)


def _stage_binding(binding: dict[str, Any], arguments: dict[str, Any], context: dict[str, Any]) -> Any:
    if "parameter" in binding:
        return arguments[binding["parameter"]]
    if "stage" in binding:
        return context[binding["stage"]][binding["column"]]
    if "literal" in binding:
        return binding["literal"]
    raise ValueError("Unsupported generated traversal binding")


def _source_frame(
    stage_name: str, source: dict[str, Any], arguments: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    if "select" in source:
        source = source["select"]
    while "parameter" in source:
        source = (
            source["if_present"] if arguments.get(source["parameter"]) is not None else source["if_absent"]
        )
    resolver = source if "resolve" in source else None
    physical = source["resolve"] if resolver else source
    bound = {
        name: _stage_binding(value, arguments, context)
        for name, value in physical.get("arguments", {}).items()
    }
    return {
        "entity": physical["entity"],
        "stage": stage_name,
        "arguments": bound,
        "cursor": {},
        "rows": [],
        "position": 0,
        "seen": [],
        "resolver": resolver,
    }


def _frame(
    cls: type, index: int, arguments: dict[str, Any], context: dict[str, Any], credentials: Any
) -> dict[str, Any]:
    if not cls.TRAVERSAL:
        return {
            "entity": cls.ENTITY["name"],
            "stage": cls.ENTITY["name"],
            "arguments": arguments,
            "cursor": {},
            "rows": [],
            "position": 0,
            "seen": [],
        }
    stage = cls.TRAVERSAL["stages"][index]
    source = cls.SCOPES[stage["scope"]] if "scope" in stage else stage
    return _source_frame(stage["name"], source, arguments, context)


def _json_value(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported generated cursor value {type(value).__name__}")


def _restore_value(value: Any, schema: dict[str, Any]) -> Any:
    """Restore already validated ancestor values from the serializable page."""
    if value is None:
        return None
    if schema["kind"] == "struct":
        return {
            child["name"]: _restore_value(value[child["name"]], child["schema"]) for child in schema["fields"]
        }
    if schema["kind"] == "list":
        return [_restore_value(item, schema["item"]) for item in value]
    if schema["type"] in ("DATE", "TIMESTAMP WITH TIME ZONE"):
        return _decode(value, schema, "retained ancestor value")
    return value


def _process(cls: type, params: Any, state: GeneratedScanState, out: Any) -> None:
    if state.done:
        out.finish()
        return
    if auth.reporting_of(params.attach_opaque_data) and state.deadline == 0:
        state.deadline = api.time.monotonic() + auth.operation_timeout_of(params.attach_opaque_data)
    with (
        api.reporting_operation(params.attach_opaque_data, deadline=state.deadline),
        api.reporting_to(emitter(out)),
    ):
        credentials = auth.for_call(params.secrets, params.attach_opaque_data)
        progress = json.loads(state.cursor_json)
        frames = progress["frames"]
        arguments = progress["arguments"]
        if not frames:
            frames.append(_frame(cls, 0, arguments, {}, credentials))
        depth = len(cls.TRAVERSAL["stages"]) if cls.TRAVERSAL else 1
        result_rows = []
        while frames:
            frame = frames[-1]
            leaf = len(frames) == depth
            context = {ancestor["stage"]: ancestor["current"] for ancestor in frames[:-1]}
            if not leaf and frame["position"] < len(frame["rows"]):
                frame["current"] = frame["rows"][frame["position"]]
                frame["position"] += 1
                context[frame["stage"]] = frame["current"]
                frames.append(_frame(cls, len(frames), arguments, context, credentials))
                continue
            if frame["cursor"].get("done"):
                frames.pop()
                continue
            entity = cls.SOURCES[frame["entity"]]
            payloads = _page(entity, frame["arguments"], credentials, frame["cursor"])
            rows = _decode_rows(entity, frame["arguments"], payloads)
            _unique_rows(entity, rows, frame["seen"])
            resolver = frame.get("resolver")
            if resolver:
                if len(rows) != 1 or not frame["cursor"].get("done"):
                    raise GeneratedContractError(
                        "Scope resolver must return exactly one complete account row"
                    )
                value = rows[0][resolver["field"]]
                branch = resolver["cases"].get(value)
                if branch is None:
                    raise GeneratedContractError(f"Unsupported scope account type {value!r}")
                frames[-1] = _source_frame(frame["stage"], branch, arguments, context)
            elif leaf:
                if cls.TRAVERSAL:
                    for row in rows:
                        context[frame["stage"]] = row
                        result_rows.append(
                            {
                                column["name"]: _restore_value(
                                    context[column["source_stage"]][column["source_column"]],
                                    column["schema"],
                                )
                                for column in cls.ENTITY["columns"]
                            }
                        )
                else:
                    result_rows = rows
                _unique_rows(cls.ENTITY, result_rows, progress["seen"])
            else:
                frame["rows"] = rows
                frame["position"] = 0
            # Every request occupies one producer tick. Ancestor-only and empty
            # pages emit a valid empty batch; the native producer asks for more.
            break
        if not frames:
            cohort_values = progress.get("cohort_values")
            next_index = progress.get("cohort_index", 0) + 1
            if cohort_values is None or next_index >= len(cohort_values):
                state.done = True
                out.finish()
                return
            progress["cohort_index"] = next_index
            arguments[cls.ENTITY["cohort"]["argument"]] = cohort_values[next_index]
        state.cursor_json = json.dumps(progress, default=_json_value, separators=(",", ":"))
        api.remaining_time()
        # Build with the full schema, then let the real collector project it.
        # This preserves cardinality even for count(*)'s zero-column projection.
        out.emit(
            pa.RecordBatch.from_pylist(result_rows, schema=cls.FIXED_SCHEMA),
            cache_control=CacheControl(no_store=True),
        )


def make_function(entity: dict[str, Any], contract: dict[str, Any] | None = None) -> type:
    """Create a native producer entirely from one compiled entity/traversal."""
    name = entity["name"]
    arguments = sorted(entity["arguments"], key=lambda argument: argument["position"])
    if not arguments or [arg["position"] for arg in arguments] != list(range(len(arguments))):
        raise ValueError("Generated functions require contiguous positional arguments")
    fields = []
    for argument in arguments:
        python_type = list[dict[str, Any]] if "schema" in argument else _SCALARS[argument["type"]][1]
        if argument.get("nullable"):
            python_type |= None
        declaration = (
            argument["name"],
            Annotated[
                python_type,
                Arg(argument["position"], doc=argument.get("description") or argument["name"],
                    **({"arrow_type": _arrow_type(argument["schema"])} if "schema" in argument else {})),
            ],
        )
        fields.append((*declaration, argument["default"]) if "default" in argument else declaration)
    args = make_dataclass(f"{name}Args", fields, kw_only=True, frozen=True)
    schema = pa.schema([_arrow_field(column) for column in entity["columns"]])
    if not entity["grain"] or any(column not in schema.names for column in entity["grain"]):
        raise ValueError("Generated functions require an explicit output grain")
    description = entity.get("description") or name
    prose = (
        description + " Complete typed entity listing from a reviewed generated contract. "
        "All advertised pages are followed without a generated row or page cap; "
        "provider errors and operation deadlines fail the query. "
        "Nested values, required fields and row identities are validated before projection. "
        "Results are uncached. Scalar scope arguments select a reviewed traversal; "
        "this producer is a query source and does not accept correlated LATERAL arguments."
    )
    meta = type(
        "Meta",
        (),
        {
            "name": name,
            "description": description,
            "categories": ["generated"],
            "projection_pushdown": True,
            "required_secrets": [SecretLookupEntry(secret_type=auth.SECRET_TYPE)],
            "tags": docs(
                category="generated",
                llm=prose,
                md=prose,
                extra={
                    "vgi.result_columns_schema": json.dumps(
                        [
                            {
                                "name": column["name"],
                                "type": column["type"],
                                "description": column.get("description") or column["name"],
                            }
                            for column in entity["columns"]
                        ]
                    )
                },
            ),
        },
    )
    return init_single_worker(
        type(
            f"{name}Function",
            (_GeneratedProducer,),
            {
                "__module__": __name__,
                "__doc__": prose,
                "Meta": meta,
                "FunctionArguments": args,
                "FIXED_SCHEMA": schema,
                "ENTITY": entity,
                "ARGUMENTS": arguments,
                "SOURCES": {source["name"]: source for source in contract["entities"]}
                if contract
                else {name: entity},
                "SCOPES": contract.get("scopes", {}) if contract else {},
                "TRAVERSAL": entity.get("traversal"),
                "on_bind": classmethod(_bind),
                "initial_state": classmethod(_initial_state),
                "process": classmethod(_process),
            },
        )
    )


def load_functions(path: str | Path | None = None) -> list[type]:
    artifact = Path(path) if path is not None else files("vgi_github").joinpath("generated_entities.json")
    contract = json.loads(artifact.read_text())
    if contract.get("format") != "vgi-github-entities" or contract.get("version") != 1:
        raise ValueError("Unsupported generated GitHub entity artifact")
    functions = contract.get("functions", contract["entities"])
    names = [entity["name"] for entity in functions]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate generated GitHub function name")
    return [make_function(entity, contract) for entity in functions]
