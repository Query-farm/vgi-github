"""Generic execution of reviewed, schema-derived GitHub entity contracts.

Only the opt-in generated worker loads these contracts. SQL supplies typed resource
arguments; endpoint paths, GraphQL documents and field mappings come from the
checked-in artifact. Pages are validated and emitted as they arrive.
"""

from __future__ import annotations

import base64
import json
import math
import re
from dataclasses import dataclass, make_dataclass
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
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
    "BLOB": (pa.binary(), bytes),
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


@dataclass
class _DocumentRow:
    row: Any
    document: Any


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
    if kind == "map":
        value = schema["value"]
        return pa.map_(
            pa.field("key", pa.string(), nullable=False),
            pa.field("value", _arrow_type(value), nullable=value.get("nullable", False)),
        )
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
    if "variant" in schema:
        definition = schema["variant"]
        discriminator = definition["discriminator"]
        names = definition["names"]
        fields = {field["name"]: field for field in schema["fields"]}
        source_discriminator = definition.get("source_discriminator")
        if source_discriminator is not None:
            event = _read_path(value, source_discriminator["path"], label)
            if not isinstance(event, str) or event not in source_discriminator["mapping"]:
                raise GeneratedContractError(f"{label}: unknown or missing reviewed variant discriminator")
            selected = [source_discriminator["mapping"][event]]
        elif discriminator is not None:
            if not isinstance(value, dict) or value.get(discriminator) not in names:
                raise GeneratedContractError(f"{label}: unknown or missing variant discriminator")
            selected = [value[discriminator]]
        else:
            selected = names
        decoded = {}
        for name in selected:
            try:
                decoded[name] = _decode(value, fields[name]["schema"], label + "." + name, nullable=False)
            except GeneratedContractError:
                if discriminator is not None or source_discriminator is not None:
                    raise
        if not decoded or definition["mode"] == "oneOf" and len(decoded) != 1:
            raise GeneratedContractError(
                f"{label}: response does not match the declared {definition['mode']} variants"
            )
        return {
            discriminator or "matched_types": next(iter(decoded)) if discriminator else list(decoded),
            **{name: decoded.get(name) for name in names},
        }
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
    if kind == "map":
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            raise GeneratedContractError(f"{label}: expected a dictionary with string keys")
        return {key: _decode(value[key], schema["value"], f"{label}[{key!r}]") for key in sorted(value)}
    scalar = schema["type"]
    enum_value = value
    valid = False
    if scalar == "BLOB":
        valid = isinstance(value, bytes)
    elif scalar == "VARCHAR":
        valid = isinstance(value, str)
    elif scalar in ("BIGINT", "INTEGER"):
        bits = 64 if scalar == "BIGINT" else 32
        if schema.get("encoding") == "decimal_string":
            # GraphQL BigInt is explicitly string-encoded by the pinned SDL.
            # Never accept JSON numbers or silently coerce fractional/exponent syntax.
            if not isinstance(value, str) or re.fullmatch(r"[+-]?[0-9]+", value) is None:
                raise GeneratedContractError(f"{label}: invalid decimal-string {scalar} value")
            digits = value.lstrip("+-").lstrip("0") or "0"
            if len(digits) > 19:
                raise GeneratedContractError(
                    f"{label}: invalid {scalar} value outside signed {bits}-bit range"
                )
            value = int(("-" if value.startswith("-") else "") + digits)
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


def _decimal_identity(value: Any) -> int | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > 19
        or re.fullmatch(r"0|[1-9][0-9]*", value) is None
        or int(value) >= 2**63
    ):
        raise GeneratedContractError("Expected a canonical nonnegative decimal identity within BIGINT range")
    return int(value)


def _binding(binding: dict[str, Any], arguments: dict[str, Any], cursor: str | None = None) -> Any:
    if "object" in binding:
        return {name: _binding(value, arguments, cursor) for name, value in binding["object"].items()}
    if "literal" in binding:
        value = binding["literal"]
    elif binding.get("cursor") is True:
        return cursor
    else:
        value = arguments[binding["argument"]]
    if isinstance(value, (date, datetime)):
        value = _json_value(value)
    transform = binding.get("transform")
    if transform == "decimal_string_to_bigint":
        return _decimal_identity(value)
    if transform:
        if transform not in ("repository_owner", "repository_name"):
            raise ValueError(f"Unsupported generated argument transform {transform!r}")
        owner, name = api.split_repo(value)
        return owner if transform == "repository_owner" else name
    if binding.get("encoding") == "decimal_string" and value is not None:
        if type(value) is not int or not -(2**63) <= value < 2**63:
            raise GeneratedContractError("GraphQL BigInt input requires a signed 64-bit integer")
        return str(value)
    return value


def _page(
    entity: dict[str, Any], arguments: dict[str, Any], credentials: Any, cursor: dict[str, Any]
) -> list[Any]:
    """Fetch exactly one page; the serializable cursor contains no result payload."""
    # Traversal bindings can have broader public contracts than the selected
    # endpoint. Revalidate here, including after continuation restores temporal
    # arguments as JSON strings, before any HTTP request is made.
    arguments.update(_physical_arguments(entity, arguments))
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

        def path_value(match):
            value = _binding(bindings[match[1]], arguments)
            if value == "" and match[1] in transport.get("allow_empty_path_parameters", []):
                return ""
            return _path_value(value)

        target = cursor.get("next_url") or _PLACEHOLDER.sub(path_value, path)
        query = {
            name: _binding(binding, arguments)
            for name, binding in transport.get("query_bindings", {}).items()
        }
        query = {name: value for name, value in query.items() if value is not None}
        for name, schema in transport.get("query_parameter_schemas", {}).items():
            if name in query:
                query[name] = _decode(query[name], schema, f"{entity['name']}.{name}")
        if "content" not in transport and transport.get("result_shape") != "object_entries":
            query.setdefault("per_page", api.PER_PAGE)
        seen = cursor.setdefault("visited", [])
        if target in seen:
            raise GeneratedContractError(f"{entity['name']}: repeated pagination URL")
        seen.append(target)
        response = api._get(
            target,
            [
                (name, item)
                for name, value in query.items()
                for item in (value if isinstance(value, list) else [value])
            ]
            if page == 0
            else None,
            credentials=None if transport.get("authentication") == "anonymous" else credentials,
            api_version=transport.get("api_version", api.API_VERSION),
            raw="content" in transport,
            accept=transport.get("accept", transport.get("content", {}).get("accept", api.ACCEPT_JSON)),
            allow_not_found="404" in transport.get("content", {}).get("response_statuses", []),
        )
        if "content" in transport:
            cursor.update(done=True, page=page + 1)
            return [_content_row(response, transport["content"], entity["name"])]
        if str(response.status) in transport.get("empty_response_statuses", []):
            if response.body or response.next_url:
                raise GeneratedContractError(
                    f"{entity['name']}: empty response must not contain body or pagination"
                )
            cursor.update(done=True, page=page + 1)
            return []
        if str(response.status) != transport.get("response_status", "200"):
            raise GeneratedContractError(f"{entity['name']}: unexpected response status {response.status}")
        if (
            response.next_url
            and pagination["kind"] == "none"
            and not pagination.get("unselected_collection_path")
        ):
            raise GeneratedContractError(
                f"{entity['name']}: unexpected pagination Link on nonpaginated response"
            )
        for assertion in transport.get("response_assertions", []):
            actual = _read_path(response.payload, assertion["path"], entity["name"])
            if actual is _MISSING and assertion.get("when_present"):
                continue
            expected = assertion["value"]
            if assertion["comparison"] == "equal":
                matches = type(actual) is type(expected) and actual == expected
            elif assertion["comparison"] == "length_lt":
                matches = isinstance(actual, list) and len(actual) < expected
            else:
                raise ValueError("Unsupported generated response assertion comparison")
            if not matches:
                raise GeneratedContractError(
                    f"{entity['name']}: response assertion failed for {'.'.join(assertion['path'])}; "
                    "the response cannot establish the declared complete population"
                )
        rows = _read_path(response.payload, transport["result_path"], entity["name"])
        if transport.get("result_shape") == "object_entries":
            if not isinstance(rows, dict) or any(not isinstance(key, str) for key in rows):
                raise GeneratedContractError(f"{entity['name']}: expected a dictionary with string keys")
            if response.next_url:
                raise GeneratedContractError(f"{entity['name']}: dictionary response cannot paginate")
            rows = [{"key": key, "value": rows[key]} for key in sorted(rows)]
        elif transport.get("result_shape", "array") == "object":
            if not isinstance(rows, dict):
                raise GeneratedContractError(f"{entity['name']}: expected an entity object")
            rows = [rows]
        elif not isinstance(rows, list):
            raise GeneratedContractError(f"{entity['name']}: expected an entity array")
        cursor["next_url"] = response.next_url
        cursor["done"] = pagination["kind"] == "none" or not response.next_url
        cursor["received_rows"] = cursor.get("received_rows", 0) + len(rows)
        if "expected_count_argument" in pagination:
            expected_count = arguments[pagination["expected_count_argument"]]
            if type(expected_count) is not int or expected_count < 0:
                raise GeneratedContractError(f"{entity['name']}: invalid expected pagination count")
            if cursor["received_rows"] > expected_count or (
                cursor["done"] and cursor["received_rows"] != expected_count
            ):
                raise GeneratedContractError(f"{entity['name']}: incomplete pagination expected count")
        if "reject_at_rows" in pagination and cursor["received_rows"] >= pagination["reject_at_rows"]:
            raise GeneratedContractError(
                f"{entity['name']}: response reached the upstream completeness boundary "
                f"of {pagination['reject_at_rows']} rows"
            )
        if "total_count_path" in pagination:
            total = _read_path(response.payload, pagination["total_count_path"], entity["name"])
            if type(total) is not int or total < 0:
                raise GeneratedContractError(f"{entity['name']}: invalid pagination total_count")
            if total != cursor.setdefault("expected_rows", total):
                raise GeneratedContractError(
                    f"{entity['name']}: pagination total_count changed during retrieval"
                )
            if cursor["received_rows"] > total or (cursor["done"] and cursor["received_rows"] != total):
                raise GeneratedContractError(f"{entity['name']}: incomplete pagination total_count")
    elif kind == "graphql":
        if pagination["kind"] not in {"cursor", "none"}:
            raise ValueError("Generated GraphQL contracts require cursor pagination or singleton lookup")
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
        if transport.get("response_aliases"):
            data = _restore_graphql_aliases(data, transport["response_aliases"], entity["name"])
        if not isinstance(data, dict):
            raise GeneratedContractError(f"{entity['name']}: missing GraphQL query data")
        if any(
            _read_path(data, path, entity["name"]) is None for path in transport.get("nullable_paths", [])
        ):
            if transport.get("nullable_path_policy") == "error":
                raise GeneratedContractError(f"{entity['name']}: required GraphQL traversal returned NULL")
            cursor.update(done=True, page=page + 1)
            return _checked_page_rows(entity, [])
        rows = _read_path(data, transport["result_path"], entity["name"])
        if pagination["kind"] == "none":
            if not isinstance(rows, dict):
                raise GeneratedContractError(f"{entity['name']}: expected a GraphQL entity object")
            cursor.update(done=True, page=page + 1)
            return _checked_page_rows(entity, [rows])
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
    if kind == "rest" and any("source_document_path" in column for column in entity["columns"]):
        # The response envelope remains a selected contract even when this page
        # contains no hit rows to carry its public metadata.
        for column in entity["columns"]:
            if "source_document_path" in column:
                label = f"{entity['name']}.{column['name']}"
                _decode(
                    _read_path(response.payload, column["source_document_path"], label),
                    column["schema"],
                    label,
                    required=column.get("required", True),
                    nullable=column.get("nullable", False),
                )
        rows = [_DocumentRow(row, response.payload) for row in rows]
    return _checked_page_rows(entity, rows)


def _checked_page_rows(entity: dict, rows: list) -> list:
    if entity.get("policy", {}).get("require_one_row") and len(rows) != 1:
        raise GeneratedContractError(f"{entity['name']}: required hydration must return exactly one row")
    return rows


def _restore_graphql_aliases(value: Any, aliases: dict[str, str], label: str) -> Any:
    if isinstance(value, list):
        return [_restore_graphql_aliases(item, aliases, label) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for wire, item in value.items():
        name = aliases.get(wire, wire)
        decoded = _restore_graphql_aliases(item, aliases, label)
        if name in result and result[name] != decoded:
            raise GeneratedContractError(f"{label}: conflicting GraphQL response aliases for {name}")
        result[name] = decoded
    return result


def _content_row(response: api.Response, contract: dict, label: str) -> dict:
    """Preserve completed bytes; pending status is not a successful empty file."""
    statuses = contract["response_statuses"]
    allowed = {int(status) for status in statuses if status.startswith("2") or status == "404"}
    if any(status.startswith("3") for status in statuses):
        allowed.add(200)  # The shared HTTP transport follows the declared redirect.
    if response.status not in allowed:
        raise GeneratedContractError(f"{label}: unexpected content response status {response.status}")
    if response.next_url:
        raise GeneratedContractError(f"{label}: content response unexpectedly advertises pagination")
    pending = str(response.status) in contract.get("pending_statuses", [])
    if pending and response.body:
        raise GeneratedContractError(f"{label}: pending response unexpectedly contains a body")
    row = {
        "status_code": response.status,
        "content_type": response.content_type,
        "byte_length": len(response.body),
        "pending": pending,
        "body": None if pending else response.body,
    }
    if contract.get("text_encoding"):
        try:
            row["body_text"] = None if pending else response.body.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise GeneratedContractError(f"{label}: content is not valid UTF-8") from exc
    return row


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


def _plan_class(cls: type, entity: dict) -> SimpleNamespace:
    """Use one compiled plan with the ordinary streaming producer."""
    return SimpleNamespace(
        ENTITY=entity,
        ARGUMENTS=entity["arguments"],
        TRAVERSAL=entity.get("traversal"),
        FIXED_SCHEMA=pa.schema([_arrow_field(column) for column in entity["columns"]]),
        SOURCES=cls.SOURCES,
        SCOPES=cls.SCOPES,
        FUNCTIONS=cls.FUNCTIONS,
    )


def _selected(entity: dict, arguments: dict) -> bool:
    if entity.get("default") is True:
        return True
    cohort = entity.get("cohort", {})
    selection = entity.get("selection", [*cohort.get("alternatives", []), cohort.get("parameter")])
    return any(arguments.get(name) is not None for name in selection) and all(
        arguments.get(name) in values for name, values in entity.get("select_values", {}).items()
    )


def _argument_constraints(definition: dict, value: Any, label: str) -> None:
    if value is None:
        return
    if definition["type"] in {"VARCHAR[]", "BIGINT[]"} and not value:
        raise GeneratedContractError(f"{label}: query array must not be empty")
    if "min_length" in definition:
        if definition["min_length"] == 1 and not value.strip():
            raise GeneratedContractError(f"{label}: empty resource argument")
        if len(value) < definition["min_length"]:
            raise GeneratedContractError(
                f"{label}: must contain at least {definition['min_length']} characters"
            )
    if "max_length" in definition and len(value) > definition["max_length"]:
        raise GeneratedContractError(f"{label}: must contain at most {definition['max_length']} characters")
    if "pattern" in definition and re.search(definition["pattern"], value) is None:
        raise GeneratedContractError(f"{label}: value does not match the required pattern")
    if "minimum" in definition and value < definition["minimum"]:
        raise GeneratedContractError(f"{label}: must be at least {definition['minimum']}")
    if "enum" in definition and value not in definition["enum"]:
        raise GeneratedContractError(f"{label}: value is outside the declared enum")


def _physical_arguments(entity: dict, arguments: dict) -> dict:
    """Validate the exact physical source contract without coercing scalar inputs."""
    definitions = {definition["name"]: definition for definition in entity["arguments"]}
    if arguments.keys() - definitions.keys():
        raise GeneratedContractError(f"{entity['name']}: unknown physical source argument")
    result = {}
    for name, definition in definitions.items():
        label = f"{entity['name']}.{name}"
        value = _decode(
            arguments.get(name, definition.get("default", _MISSING)),
            definition.get("schema", {"kind": "scalar", "type": definition["type"]}),
            label,
            nullable=definition.get("nullable", False),
        )
        _argument_constraints(definition, value, label)
        result[name] = value
    return result


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
    if "routes" in cls.ENTITY:
        selected = next(
            (index for index, route in enumerate(cls.ENTITY["routes"]) if _selected(route, arguments)), None
        )
        if selected is None:
            raise GeneratedContractError(f"{cls.ENTITY['name']}: select a retrieval population")
        route = cls.ENTITY["routes"][selected]
        state = _initial_state(_plan_class(cls, route), params)
        progress = json.loads(state.cursor_json)
        progress.update(route=selected, filters=[])
        consumed = {arg["name"] for arg in route["arguments"]}
        for selection in cls.ENTITY.get("filters", []):
            root = selection["root"]
            if root["cohort"]["parameter"] == route.get("cohort", {}).get("parameter") or not _selected(
                root, arguments
            ):
                continue
            child = _initial_state(_plan_class(cls, root), params)
            consumed.update(arg["name"] for arg in root["arguments"])
            progress["filters"].append(
                {**selection, "state": child.cursor_json, "done": child.done, "values": []}
            )
            if child.done:
                state.done = True
        if any(value is not None and name not in consumed for name, value in arguments.items()):
            raise GeneratedContractError(
                f"{cls.ENTITY['name']}: arguments do not apply to the selected population"
            )
        state.cursor_json = json.dumps(progress)
        return state
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
                    if arguments.get(name) is not None and any(
                        arguments.get(other) is None for other in required
                    ):
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
        if (
            exclusive
            and cohort_values != []
            and sum(arguments.get(name) is not None for name in exclusive) != 1
        ):
            raise GeneratedContractError(f"Specify exactly one of {', '.join(exclusive)}")
        for name, required in scope.get("requires_parameters", {}).items():
            if arguments.get(name) is not None and any(arguments.get(other) is None for other in required):
                raise GeneratedContractError(f"{name} requires {', '.join(required)}")
    for definition in cls.ARGUMENTS:
        name = definition["name"]
        _argument_constraints(definition, arguments[name], name)
    return GeneratedScanState(
        cursor_json=json.dumps(
            {
                "arguments": arguments,
                "frames": [],
                "seen": [],
                "cohort_values": cohort_values,
                "cohort_index": 0,
            },
            default=_json_value,
        ),
        done=cohort_values == [],
    )


def _decode_rows(
    entity: dict[str, Any], arguments: dict[str, Any], payloads: list[Any], *, offset: int = 0
) -> list[dict[str, Any]]:
    rows = []
    scalar_rows = any(column.get("source_value") is True for column in entity["columns"])
    tuple_length = entity["transport"].get("item_length")
    for ordinal, payload in enumerate(payloads, start=offset + 1):
        api.remaining_time()
        document = None
        if isinstance(payload, _DocumentRow):
            document, payload = payload.document, payload.row
        if tuple_length is not None and (not isinstance(payload, list) or len(payload) != tuple_length):
            raise GeneratedContractError(f"{entity['name']}: expected tuple of exactly {tuple_length} items")
        if not isinstance(payload, dict) and not scalar_rows and tuple_length is None:
            raise GeneratedContractError(f"{entity['name']}: expected an entity object")
        row = {}
        for column in entity["columns"]:
            label = f"{entity['name']}.{column['name']}"
            if "source_document_path" in column:
                value = _read_path(document, column["source_document_path"], label)
            elif "source_index" in column:
                value = payload[column["source_index"]]
            elif "source_ordinal" in column:
                value = ordinal
            elif "source_value" in column:
                value = payload
            elif "source_argument" in column:
                value = arguments[column["source_argument"]]
            elif "source_response" in column:
                value = payload[column["source_response"]]
            elif "source_entry" in column:
                value = payload[column["source_entry"]]
                if column["source_entry"] == "value":
                    value = _read_path(value, column.get("path", []), label)
            else:
                value = _read_path(payload, column["path"], label)
                if "on_types" in column:
                    parent = _read_path(payload, column["path"][:-1], label)
                    if parent is not None and parent is not _MISSING:
                        concrete = parent.get("__typename") if isinstance(parent, dict) else None
                        if concrete not in column["parent_types"]:
                            raise GeneratedContractError(f"{label}: missing or unknown GraphQL parent type")
                        if concrete not in column["on_types"]:
                            value = None
            row[column["name"]] = _decode(
                value,
                column["schema"],
                label,
                required=column.get("required", True),
                nullable=column.get("nullable", False),
            )
        for assertion in entity.get("policy", {}).get("row_assertions", []):
            if assertion["comparison"] not in {"github_login", "equal", "equal_if_present"}:
                raise ValueError("Unsupported generated row assertion comparison")
            actual = row[assertion["column"]]
            expected = arguments[assertion["argument"]]
            matches = (actual is not None and actual == expected) or (
                assertion["comparison"] == "equal_if_present" and actual is None
            )
            if assertion["comparison"] == "github_login":
                matches = (
                    isinstance(actual, str)
                    and isinstance(expected, str)
                    and actual.casefold() == expected.casefold()
                )
            if not matches:
                raise GeneratedContractError(
                    f"{entity['name']}: row assertion failed: "
                    f"{assertion['column']} must match {assertion['argument']}"
                )
        rows.append(row)
    return rows


def _identity(entity: dict[str, Any], row: dict[str, Any]) -> str:
    values = [row[name] for name in entity["grain"]]
    dictionary_keys = {column["name"] for column in entity["columns"] if column.get("source_entry") == "key"}
    empty_keys = {
        column["name"] for column in entity["columns"] if column.get("allow_empty_identity") is True
    }
    if any(
        value is None
        or isinstance(value, str)
        and not value.strip()
        and name not in dictionary_keys
        and not (value == "" and name in empty_keys)
        for name, value in zip(entity["grain"], values, strict=True)
    ):
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
        value = arguments[binding["parameter"]]
    elif "stage" in binding:
        value = context[binding["stage"]][binding["column"]]
    elif "literal" in binding:
        value = binding["literal"]
    else:
        raise ValueError("Unsupported generated traversal binding")
    transform = binding.get("transform")
    if transform == "decimal_string_to_bigint":
        return _decimal_identity(value)
    if transform:
        raise ValueError("Unsupported generated traversal transform")
    return value


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
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
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
    if schema["kind"] == "map":
        return {key: _restore_value(item, schema["value"]) for key, item in value.items()}
    if schema["type"] == "BLOB":
        return value if isinstance(value, bytes) else base64.b64decode(value, validate=True)
    if schema["type"] in ("DATE", "TIMESTAMP WITH TIME ZONE"):
        return _decode(value, schema, "retained ancestor value")
    return value


def _process(cls: type, params: Any, state: GeneratedScanState, out: Any) -> None:
    if state.done:
        out.finish()
        return
    if auth.reporting_of(params.attach_opaque_data) and state.deadline == 0:
        state.deadline = api.time.monotonic() + auth.operation_timeout_of(params.attach_opaque_data)
    progress = json.loads(state.cursor_json)
    if "routes" in cls.ENTITY:
        for selection in progress["filters"]:
            if selection["done"]:
                continue
            root = _plan_class(cls, selection["root"])
            child = GeneratedScanState(cursor_json=selection["state"], deadline=state.deadline)

            class SelectionOutput:
                def __init__(self, selected):
                    self.selected = selected

                def emit(self, batch, **kwargs):
                    self.selected["values"].extend(batch.column(self.selected["key"]).to_pylist())

                def finish(self):
                    pass

                def client_log(self, *args, **kwargs):
                    out.client_log(*args, **kwargs)

            _process(root, params, child, SelectionOutput(selection))
            selection.update(state=child.cursor_json, done=child.done)
            state.cursor_json = json.dumps(progress)
            if child.done and not selection["values"]:
                state.done = True
                out.finish()
            else:
                out.emit(
                    pa.RecordBatch.from_pylist([], schema=cls.FIXED_SCHEMA),
                    cache_control=CacheControl(no_store=True),
                )
            return
        plan = _plan_class(cls, cls.ENTITY["routes"][progress["route"]])
        plan.FIXED_SCHEMA = cls.FIXED_SCHEMA
        cls = plan
    with (
        api.reporting_operation(params.attach_opaque_data, deadline=state.deadline),
        api.reporting_to(emitter(out)),
    ):
        credentials = auth.for_call(params.secrets, params.attach_opaque_data)
        frames = progress["frames"]
        arguments = progress["arguments"]
        if not frames:
            frames.append(_frame(cls, 0, arguments, {}, credentials))
        depth = len(cls.TRAVERSAL["stages"]) if cls.TRAVERSAL else 1
        result_rows = []
        while frames:
            frame = frames[-1]
            leaf = len(frames) >= depth
            context = {ancestor["stage"]: ancestor["current"] for ancestor in frames[:-1]}
            stage = cls.TRAVERSAL["stages"][min(len(frames), depth) - 1] if cls.TRAVERSAL else {}
            if leaf and stage.get("children") and frame["position"] < len(frame["rows"]):
                frame["current"] = frame["rows"][frame["position"]]
                frame["position"] += 1
                context[frame["stage"]] = frame["current"]
                frames.append(_source_frame(frame["stage"], stage["children"], arguments, context))
                continue
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
            rows = _decode_rows(entity, frame["arguments"], payloads, offset=len(frame["seen"]))
            _unique_rows(entity, rows, frame["seen"])
            if cls.TRAVERSAL and not frame.get("resolver"):
                where = stage.get("where", {})
                where = {
                    **where,
                    **{
                        key: _restore_value(
                            progress["arguments"][parameter],
                            next(column["schema"] for column in entity["columns"] if column["name"] == key),
                        )
                        for key, parameter in stage.get("where_parameters", {}).items()
                        if progress["arguments"].get(parameter) is not None
                    },
                }
                rows = [row for row in rows if all(row[key] == value for key, value in where.items())]
            # Apply an actor selection at its declaring stage, before fetching
            # descendants such as reviews of an excluded author's PR.
            if not frame.get("resolver") and not stage.get("children"):
                for selection in progress.get("filters", []):
                    column = next(
                        column for column in cls.ENTITY["columns"] if column["name"] == selection["column"]
                    )
                    if column["source_stage"] == frame["stage"]:
                        allowed = set(selection["values"])
                        rows = [row for row in rows if row[column["source_column"]] in allowed]
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
                if stage.get("children"):
                    frame["rows"] = rows
                    frame["position"] = 0
                if cls.TRAVERSAL:
                    for row in rows:
                        context[frame["stage"]] = row
                        result_rows.append(
                            {
                                column["name"]: _restore_value(
                                    _read_path(
                                        context[column["source_stage"]][column["source_column"]],
                                        column.get("source_path", []),
                                        cls.ENTITY["name"] + "." + column["name"],
                                    ),
                                    column["schema"],
                                )
                                for column in cls.ENTITY["columns"]
                            }
                        )
                else:
                    result_rows = rows
                if cls.ENTITY.get("deduplicate"):
                    distinct = []
                    seen = set(progress["seen"])
                    for row in result_rows:
                        identity = _identity(cls.ENTITY, row)
                        if identity not in seen:
                            seen.add(identity)
                            progress["seen"].append(identity)
                            distinct.append(row)
                    result_rows = distinct
                else:
                    _unique_rows(cls.ENTITY, result_rows, progress["seen"])
                for selection in progress.get("filters", []):
                    allowed = set(selection["values"])
                    result_rows = [row for row in result_rows if row[selection["column"]] in allowed]
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
    if [arg["position"] for arg in arguments] != list(range(len(arguments))):
        raise ValueError("Generated functions require contiguous positional arguments")
    fields = []
    for argument in arguments:
        python_type = list[dict[str, Any]] if "schema" in argument else _SCALARS[argument["type"]][1]
        if argument["type"] in {"VARCHAR[]", "BIGINT[]"}:
            python_type = list[_SCALARS[argument["type"][:-2]][1]]
        if argument.get("nullable"):
            python_type |= None
        declaration = (
            argument["name"],
            Annotated[
                python_type,
                Arg(
                    argument["position"],
                    doc=argument.get("description") or argument["name"],
                    arrow_type=(
                        _arrow_type(argument["schema"])
                        if "schema" in argument
                        else _SCALARS[argument["type"]][0]
                    ),
                ),
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
                "FUNCTIONS": {function["name"]: function for function in contract.get("functions", [])}
                if contract
                else {},
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
