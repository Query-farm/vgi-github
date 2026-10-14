"""Compile pinned upstream schemas and a declarative selection into runtime contracts.

This module performs no HTTP requests and registers no runtime functions. Unsupported
selected schema shapes fail generation; they are never silently converted to JSON text.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Any

from graphql import (
    GraphQLList,
    GraphQLNonNull,
    Undefined,
    build_schema,
    coerce_input_value,
    get_named_type,
    is_enum_type,
    is_input_object_type,
    is_interface_type,
    is_object_type,
    is_scalar_type,
    parse,
    validate,
)


class SchemaError(ValueError):
    """A selected source contract cannot be represented safely."""


SCALARS = {"VARCHAR", "BIGINT", "DOUBLE", "BOOLEAN", "DATE", "TIMESTAMP WITH TIME ZONE"}
GRAPHQL_SCALARS = {
    "String": "VARCHAR",
    "ID": "VARCHAR",
    "Int": "BIGINT",
    "Float": "DOUBLE",
    "Boolean": "BOOLEAN",
    "Date": "DATE",
    "DateTime": "TIMESTAMP WITH TIME ZONE",
    "GitTimestamp": "TIMESTAMP WITH TIME ZONE",
    "URI": "VARCHAR",
    "GitObjectID": "VARCHAR",
    "Base64String": "VARCHAR",
    "HTML": "VARCHAR",
}


def _fail(location: str, message: str) -> Any:
    raise SchemaError(f"{location}: {message}")


def _identifier(value: Any, location: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        _fail(location, "expected an identifier")
    return value


def _path(value: Any, location: str, *, empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not empty):
        _fail(location, "expected a field path array")
    return [_identifier(part, location) for part in value]


def _keys(value: Any, allowed: set[str], required: set[str], location: str) -> None:
    if not isinstance(value, dict):
        _fail(location, "expected an object")
    if unknown := value.keys() - allowed:
        _fail(location, f"unknown keys: {', '.join(sorted(unknown))}")
    if missing := required - value.keys():
        _fail(location, f"missing keys: {', '.join(sorted(missing))}")


def local_ref(document: dict, ref: str, location: str = "schema") -> dict:
    """Resolve a JSON pointer without following further references."""
    if not isinstance(ref, str) or not ref.startswith("#/"):
        _fail(location, f"external reference is unsupported: {ref!r}")
    value: Any = document
    try:
        for part in ref[2:].split("/"):
            value = value[part.replace("~1", "/").replace("~0", "~")]
    except (KeyError, TypeError) as exc:
        raise SchemaError(f"{location}: unresolved reference {ref}") from exc
    if not isinstance(value, dict):
        _fail(location, f"reference is not an object: {ref}")
    return value


def reference_closure(document: dict, node: Any) -> dict:
    """Preserve the original graph, including cyclic refs/variants, for drift hashing."""
    refs: dict[str, dict] = {}

    def visit(value: Any, *, property_map: bool = False) -> None:
        if isinstance(value, dict):
            if "$ref" in value and not property_map:
                ref = value["$ref"]
                if ref not in refs:
                    target = local_ref(document, ref)
                    refs[ref] = copy.deepcopy(target)
                    visit(target)
            for key, item in value.items():
                # Example/default/enum values are arbitrary instance data. A
                # literal "$ref" inside them is not an OpenAPI reference.
                if property_map or key not in {"$ref", "example", "examples", "default", "enum", "const"}:
                    visit(
                        item,
                        property_map=not property_map
                        and key in {"properties", "patternProperties", "$defs", "definitions"},
                    )
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(node)
    return {"root": copy.deepcopy(node), "references": {key: refs[key] for key in sorted(refs)}}


def closure_hash(document: dict, node: Any) -> str:
    encoded = json.dumps(reference_closure(document, node), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _resolved(document: dict, node: dict, location: str, trail: tuple[str, ...] = ()) -> dict:
    if not isinstance(node, dict):
        _fail(location, "expected a schema object")
    if "$ref" in node:
        ref = node["$ref"]
        if ref in trail:
            _fail(location, f"selected recursive reference {ref}")
        target = _resolved(document, local_ref(document, ref, location), location, (*trail, ref))
        node = {**target, **{key: value for key, value in node.items() if key != "$ref"}}
    if "allOf" in node:
        merged = {key: copy.deepcopy(value) for key, value in node.items() if key != "allOf"}
        for part in node["allOf"]:
            part = _resolved(document, part, location, trail)
            if part.get("type", "object") != "object":
                _fail(location, "only object allOf intersections are supported")
            for name, value in part.get("properties", {}).items():
                previous = merged.setdefault("properties", {}).get(name)
                if previous is not None and previous != value:
                    _fail(location, f"conflicting allOf property {name!r}")
                merged["properties"][name] = value
            merged["required"] = sorted(set(merged.get("required", [])) | set(part.get("required", [])))
            for key, value in part.items():
                if key not in {"properties", "required", "description", "title", "example", "examples"}:
                    if key in merged and merged[key] != value:
                        _fail(location, f"conflicting allOf {key}")
                    merged[key] = value
        node = merged
    return node


def _sql_type(schema: dict) -> str:
    if schema["kind"] == "scalar":
        return schema["type"]
    if schema["kind"] == "list":
        return f"{_sql_type(schema['item'])}[]"
    return (
        "STRUCT("
        + ", ".join(
            '"' + field["name"].replace('"', '""') + '" ' + _sql_type(field["schema"])
            for field in schema["fields"]
        )
        + ")"
    )


def _openapi_type(
    document: dict, node: dict, location: str, selection: dict | None = None, trail: tuple[str, ...] = ()
) -> dict:
    if "$ref" in node:
        ref = node["$ref"]
        if ref in trail:
            _fail(location, f"selected recursive reference {ref}; narrow the selection")
        trail = (*trail, ref)
    node = _resolved(document, node, location)
    if any(key in node for key in ("oneOf", "anyOf", "not")):
        _fail(location, "selected variants (oneOf/anyOf/not) require an explicit supported contract")
    kind = node.get("type", "object" if "properties" in node else None)
    nullable = node.get("nullable", False)
    if isinstance(kind, list):
        nullable = nullable or "null" in kind
        non_null = [item for item in kind if item != "null"]
        if len(non_null) != 1:
            _fail(location, "selected multi-type variant is unsupported")
        kind = non_null[0]
    if not isinstance(nullable, bool):
        _fail(location, "nullable must be boolean")
    if kind == "object":
        properties = node.get("properties", {})
        if not properties:
            _fail(location, "unbounded or empty object requires a selected structured contract")
        if selection is not None and (not isinstance(selection, dict) or not selection):
            _fail(location, "object selection must be a nonempty field tree")
        selected = selection if selection is not None else dict.fromkeys(properties, True)
        fields = []
        for name, child in selected.items():
            if name not in properties:
                _fail(location, f"unknown selected property {name!r}")
            if child is not True and not isinstance(child, dict):
                _fail(f"{location}.{name}", "selection must be true or a nested field tree")
            schema = _openapi_type(
                document, properties[name], f"{location}.{name}", None if child is True else child, trail
            )
            fields.append(
                {
                    "name": name,
                    "required": name in node.get("required", []),
                    "nullable": schema["nullable"],
                    "schema": schema,
                }
            )
        return {"kind": "struct", "fields": fields, "nullable": nullable}
    if kind == "array":
        if "items" not in node:
            _fail(location, "array requires an item schema")
        return {
            "kind": "list",
            "item": _openapi_type(document, node["items"], location + "[]", selection, trail),
            "nullable": nullable,
        }
    if selection is not None:
        _fail(location, "a scalar cannot have a nested selection")
    mapping = {"integer": "BIGINT", "number": "DOUBLE", "boolean": "BOOLEAN", "string": "VARCHAR"}
    if kind not in mapping:
        _fail(location, f"unsupported selected type {kind!r}")
    sql_type = mapping[kind]
    if kind == "string" and node.get("format") == "date-time":
        sql_type = "TIMESTAMP WITH TIME ZONE"
    elif kind == "string" and node.get("format") == "date":
        sql_type = "DATE"
    elif kind == "string" and node.get("format") in {"binary", "byte"}:
        _fail(location, "encoded/binary response fields need an explicit binary contract")
    result = {"kind": "scalar", "type": sql_type, "nullable": nullable}
    if "enum" in node:
        result["enum"] = copy.deepcopy(node["enum"])
    return result


def _rest_field(document: dict, node: dict, path: list[str], location: str) -> tuple[dict, bool, bool]:
    required, parent_nullable = True, False
    for name in path:
        node = _resolved(document, node, location)
        if "oneOf" in node or "anyOf" in node:
            _fail(location, "cannot traverse a selected variant")
        parent_nullable |= node.get("nullable", False)
        if name not in node.get("properties", {}):
            _fail(location, f"unknown selected property {name!r}")
        required &= name in node.get("required", [])
        node = node["properties"][name]
    return node, required, parent_nullable


def _entity_base(entity: dict) -> dict:
    name = _identifier(entity.get("name"), "entity.name")
    arguments = []
    names = set()
    for index, item in enumerate(entity.get("arguments", [])):
        _keys(
            item,
            {
                "name",
                "type",
                "nullable",
                "position",
                "description",
                "default",
                "min_length",
                "minimum",
                "example",
            },
            {"name", "type"},
            name,
        )
        arg_name = _identifier(item["name"], f"{name}.argument")
        if arg_name.lower() in names:
            _fail(name, f"duplicate argument {arg_name}")
        names.add(arg_name.lower())
        if item["type"] not in SCALARS:
            _fail(name, f"unsupported argument type {item['type']!r}")
        if item.get("position", index) != index:
            _fail(name, "argument positions must match their declared order")
        if not isinstance(item.get("nullable", False), bool):
            _fail(name, "argument nullable must be boolean")
        if "default" in item and (item["default"] is not None or not item.get("nullable")):
            _fail(name, "only nullable arguments may declare a NULL default")
        if "min_length" in item and (
            item["type"] != "VARCHAR" or type(item["min_length"]) is not int or item["min_length"] < 0
        ):
            _fail(name, "min_length requires a nonnegative integer and VARCHAR argument")
        if "minimum" in item and (item["type"] != "BIGINT" or type(item["minimum"]) is not int):
            _fail(name, "minimum requires a BIGINT argument and integer bound")
        if "example" in item:
            value, kind = item["example"], item["type"]
            valid = {
                "VARCHAR": lambda value: isinstance(value, str),
                "BIGINT": lambda value: type(value) is int and -(2**63) <= value < 2**63,
                "DOUBLE": lambda value: type(value) in (int, float) and math.isfinite(value),
                "BOOLEAN": lambda value: type(value) is bool,
                "DATE": lambda value: isinstance(value, str) and date.fromisoformat(value) is not None,
                "TIMESTAMP WITH TIME ZONE": lambda value: (
                    isinstance(value, str)
                    and datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
                ),
            }
            try:
                matches = valid[kind](value)
            except (ValueError, OverflowError):
                matches = False
            if not matches:
                _fail(name, f"example must be a non-NULL scalar matching {kind}")
            if "min_length" in item and len(value.strip()) < item["min_length"]:
                _fail(name, "example must satisfy min_length")
            if "minimum" in item and value < item["minimum"]:
                _fail(name, "example must satisfy minimum")
        arguments.append({**item, "position": index, "nullable": item.get("nullable", False)})
    return {
        "name": name,
        "description": entity.get("description", ""),
        "arguments": arguments,
        "columns": [],
        "grain": copy.deepcopy(entity.get("grain", [])),
        **{key: copy.deepcopy(entity[key]) for key in ("semantics", "policy") if key in entity},
    }


def _column(base: dict, column: dict, schema: dict | None = None, *, required: bool = True) -> dict:
    location = f"{base['name']}.{column.get('name', '?')}"
    _keys(column, {"name", "path", "source_argument", "selection", "description"}, {"name"}, location)
    name = _identifier(column["name"], location)
    if ("path" in column) == ("source_argument" in column):
        _fail(location, "specify exactly one of path and source_argument")
    result = {"name": name, "description": column.get("description", ""), "required": required}
    if "source_argument" in column:
        args = {arg["name"]: arg for arg in base["arguments"]}
        argument = args.get(column["source_argument"])
        if argument is None:
            _fail(location, "unknown source_argument")
        if "selection" in column:
            _fail(location, "source_argument cannot have a selection")
        schema = {"kind": "scalar", "type": argument["type"], "nullable": argument["nullable"]}
        result["source_argument"] = argument["name"]
    else:
        result["path"] = _path(column["path"], location)
    if schema is None:
        _fail(location, "missing compiled column schema")
    result.update(type=_sql_type(schema), nullable=schema["nullable"], schema=schema)
    return result


def _complete(base: dict) -> dict:
    columns = {column["name"].lower(): column for column in base["columns"]}
    if not columns or len(columns) != len(base["columns"]):
        _fail(base["name"], "columns must be nonempty and unique ignoring case")
    if not base["grain"] or len(set(base["grain"])) != len(base["grain"]):
        _fail(base["name"], "grain must be nonempty and unique")
    for name in base["grain"]:
        column = columns.get(name.lower())
        if (
            column is None
            or column["name"] != name
            or column["nullable"]
            or not column["required"]
            or column["schema"]["kind"] != "scalar"
        ):
            _fail(base["name"], f"grain column {name!r} must be a required non-null scalar")
    if "policy" in base:
        policy = base["policy"]
        _keys(policy, {"row_assertions"}, {"row_assertions"}, base["name"] + ".policy")
        assertions = policy["row_assertions"]
        if not isinstance(assertions, list) or not assertions:
            _fail(base["name"], "row_assertions must be a nonempty list")
        arguments = {argument["name"]: argument for argument in base["arguments"]}
        seen = set()
        for assertion in assertions:
            _keys(
                assertion,
                {"column", "argument", "comparison"},
                {"column", "argument", "comparison"},
                base["name"],
            )
            column_name = _identifier(assertion["column"], base["name"])
            argument_name = _identifier(assertion["argument"], base["name"])
            column = columns.get(column_name.lower())
            argument = arguments.get(argument_name)
            if assertion["comparison"] != "github_login":
                _fail(base["name"], "unsupported row assertion comparison")
            if (
                column is None
                or column["name"] != column_name
                or column["schema"]["kind"] != "scalar"
                or column["type"] != "VARCHAR"
                or argument is None
                or argument["type"] != "VARCHAR"
                or argument["nullable"]
            ):
                _fail(base["name"], "row assertions require a VARCHAR column and a non-null VARCHAR argument")
            identity = column_name, argument_name, assertion["comparison"]
            if identity in seen:
                _fail(base["name"], "duplicate row assertion")
            seen.add(identity)
    return base


def _binding(binding: dict, base: dict, expected: str, nullable: bool, location: str) -> dict:
    _keys(binding, {"argument", "transform", "literal", "cursor"}, set(), location)
    if sum(key in binding for key in ("argument", "literal", "cursor")) != 1:
        _fail(location, "binding requires exactly one argument, literal or cursor")
    if "argument" in binding:
        argument = next((arg for arg in base["arguments"] if arg["name"] == binding["argument"]), None)
        if argument is None:
            _fail(location, "binding refers to an undeclared argument")
        if "transform" in binding:
            if (
                binding["transform"] not in {"repository_owner", "repository_name"}
                or argument["type"] != "VARCHAR"
            ):
                _fail(location, "repository transforms require a VARCHAR argument")
            actual = "VARCHAR"
        else:
            actual = argument["type"]
        if actual != expected or (argument["nullable"] and not nullable):
            _fail(
                location,
                f"argument contract does not match {expected}{' nullable' if nullable else ' NOT NULL'}",
            )
    elif "transform" in binding:
        _fail(location, "only argument bindings can apply a transform")
    if "cursor" in binding and (binding["cursor"] is not True or expected != "VARCHAR" or not nullable):
        _fail(location, "cursor requires a nullable VARCHAR argument")
    if "literal" in binding:
        value = binding["literal"]
        valid = (value is None and nullable) or {
            "VARCHAR": lambda: isinstance(value, str),
            "BIGINT": lambda: isinstance(value, int) and not isinstance(value, bool),
            "DOUBLE": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
            "BOOLEAN": lambda: isinstance(value, bool),
            "DATE": lambda: isinstance(value, str),
            "TIMESTAMP WITH TIME ZONE": lambda: isinstance(value, str),
        }[expected]()
        if not valid:
            _fail(location, f"literal does not match {expected}")
    return copy.deepcopy(binding)


def compile_rest_entity(document: dict, entity: dict) -> dict:
    """Compile one reviewed GET selection from an OpenAPI document."""
    base = _entity_base(entity)
    transport = entity["transport"]
    _keys(
        transport,
        {
            "kind",
            "product",
            "operation_id",
            "path_bindings",
            "query_bindings",
            "result_path",
            "pagination",
            "response_status",
            "result_shape",
            "response_variants",
        },
        {"kind", "operation_id"},
        base["name"],
    )
    matches = [
        (path, item, item["get"])
        for path, item in document.get("paths", {}).items()
        if "get" in item and item["get"].get("operationId") == transport["operation_id"]
    ]
    if len(matches) != 1:
        _fail(base["name"], "operation_id must select exactly one GET operation")
    path, path_item, operation = matches[0]
    status = transport.get("response_status", "200")
    response = operation.get("responses", {}).get(status)
    if response is None:
        _fail(base["name"], f"missing response status {status}")
    response = _resolved(document, response, base["name"])
    node = response.get("content", {}).get("application/json", {}).get("schema")
    if node is None:
        _fail(base["name"], "selected response needs an application/json schema")
    original = node
    result_path = _path(transport.get("result_path", []), base["name"], empty=True)
    node, _, _ = _rest_field(document, node, result_path, base["name"])
    node = _resolved(document, node, base["name"])
    shape = transport.get("result_shape", "array")
    if shape == "array":
        if node.get("type") != "array" or "items" not in node:
            _fail(base["name"], "selected REST result must be an array")
        row = node["items"]
    elif shape == "object" and node.get("type", "object") == "object":
        row = node
    else:
        _fail(base["name"], "REST result_shape must match an array or object schema")
    rows = [row]
    if "response_variants" in transport:
        if transport["response_variants"] != "common_fields" or shape != "object" or "oneOf" not in row:
            _fail(base["name"], "common_fields requires an explicit object oneOf response")
        rows = row["oneOf"]
        if not rows:
            _fail(base["name"], "response variants must be nonempty")
    for column in entity.get("columns", []):
        if "source_argument" in column:
            base["columns"].append(_column(base, column))
            continue
        field_path = _path(column.get("path"), base["name"])
        schemas, required = [], True
        for variant in rows:
            field, present, parent_nullable = _rest_field(document, variant, field_path, base["name"])
            required &= present
            schema = _openapi_type(
                document, field, base["name"] + "." + column["name"], column.get("selection")
            )
            schema["nullable"] |= parent_nullable
            schemas.append(schema)
        schema = _merge_schemas(schemas, base["name"] + "." + column["name"])
        base["columns"].append(_column(base, column, schema, required=required))
    parameters = {}
    for item in [*path_item.get("parameters", []), *operation.get("parameters", [])]:
        item = _resolved(document, item, base["name"])
        parameters[item["in"], item["name"]] = item
    normalized = {}
    for place, key in (("path", "path_bindings"), ("query", "query_bindings")):
        normalized[key] = {}
        for name, binding in transport.get(key, {}).items():
            parameter = parameters.get((place, name))
            if parameter is None:
                _fail(base["name"], f"unknown {place} parameter {name!r}")
            descriptor = _openapi_type(document, parameter.get("schema", {}), f"{base['name']}.{name}")
            if descriptor["kind"] != "scalar":
                _fail(base["name"], "only scalar transport parameters are supported")
            normalized[key][name] = _binding(binding, base, descriptor["type"], descriptor["nullable"], name)
            if "literal" in binding and "enum" in descriptor and binding["literal"] not in descriptor["enum"]:
                _fail(base["name"], f"literal outside the allowed enum for {name}")
        for (parameter_place, name), parameter in parameters.items():
            if parameter_place == place and parameter.get("required") and name not in normalized[key]:
                _fail(base["name"], f"required {place} parameter {name!r} is unmapped")
    pagination = transport.get("pagination", {"kind": "link" if shape == "array" else "none"})
    _keys(pagination, {"kind"}, {"kind"}, base["name"])
    if pagination["kind"] != ("link" if shape == "array" else "none"):
        _fail(base["name"], "REST arrays require Link pagination; singleton objects require none")
    base["transport"] = {
        "kind": "rest",
        "operation_id": transport["operation_id"],
        "path": path,
        "method": "GET",
        "product": transport.get("product", "api.github.com"),
        **normalized,
        "result_path": result_path,
        "result_shape": shape,
        "pagination": copy.deepcopy(pagination),
    }
    base["source"] = {
        "response_sha256": closure_hash(document, original),
        "result_nullable": node.get("nullable", False),
        "item_nullable": _resolved(document, row, base["name"]).get("nullable", False),
        "response_schema": reference_closure(document, original),
    }
    return _complete(base)


def _merge_schemas(schemas: list[dict], location: str) -> dict:
    """Union null/presence domains only; differing concrete types never coerce."""
    first = schemas[0]
    if any(_sql_type(value) != _sql_type(first) for value in schemas[1:]):
        _fail(location, "scope/response variants must have identical selected concrete types")
    result = copy.deepcopy(first)
    result["nullable"] = any(value["nullable"] for value in schemas)
    if first["kind"] == "list":
        result["item"] = _merge_schemas([value["item"] for value in schemas], location + "[]")
    elif first["kind"] == "struct":
        for index, field in enumerate(result["fields"]):
            candidates = [value["fields"][index] for value in schemas]
            field["required"] = all(value["required"] for value in candidates)
            field["schema"] = _merge_schemas(
                [value["schema"] for value in candidates], location + "." + field["name"]
            )
            field["nullable"] = field["schema"]["nullable"]
    elif all("enum" in value for value in schemas):
        result["enum"] = list(dict.fromkeys(item for value in schemas for item in value["enum"]))
    else:
        result.pop("enum", None)
    return result


def _graphql_type(
    value: Any, location: str, selection: dict | None = None, trail: tuple[str, ...] = ()
) -> dict:
    nullable = not isinstance(value, GraphQLNonNull)
    value = value.of_type if not nullable else value
    if isinstance(value, GraphQLList):
        return {
            "kind": "list",
            "item": _graphql_type(value.of_type, location + "[]", selection, trail),
            "nullable": nullable,
        }
    if is_object_type(value):
        if value.name in trail:
            _fail(location, f"selected recursive GraphQL object {value.name}; narrow the selection")
        if not selection:
            _fail(location, "GraphQL object columns require an explicit field selection")
        fields = []
        for name, child in selection.items():
            if name not in value.fields:
                _fail(location, f"unknown GraphQL field {name!r}")
            field = value.fields[name]
            if field.args:
                _fail(location, "nested selected fields with arguments require a separate entity")
            descriptor = _graphql_type(
                field.type, location + "." + name, None if child is True else child, (*trail, value.name)
            )
            fields.append(
                {"name": name, "required": True, "nullable": descriptor["nullable"], "schema": descriptor}
            )
        return {"kind": "struct", "fields": fields, "nullable": nullable}
    if selection is not None:
        _fail(location, "scalar GraphQL columns cannot have nested selections")
    if is_enum_type(value):
        return {"kind": "scalar", "type": "VARCHAR", "enum": list(value.values), "nullable": nullable}
    if is_scalar_type(value) and value.name in GRAPHQL_SCALARS:
        return {"kind": "scalar", "type": GRAPHQL_SCALARS[value.name], "nullable": nullable}
    _fail(location, f"unsupported selected GraphQL type {value}")


def _selection_merge(tree: dict, path: list[str], tail: dict | None = None) -> None:
    for name in path:
        tree = tree.setdefault(name, {})
    if tail:
        for name, value in tail.items():
            _selection_merge(tree, [name], None if value is True else value)


def _selection_sql(tree: dict) -> str:
    return " ".join(
        name + (" { " + _selection_sql(child) + " }" if child else "") for name, child in tree.items()
    )


def _graphql_input_binding(kind, binding: dict, base: dict, location: str, depth: int = 0) -> dict:
    """Bind reviewed input objects from public scalar arguments, with schema checks."""
    if depth > 8:
        _fail(location, "GraphQL input binding exceeds eight object levels")
    raw = kind.of_type if isinstance(kind, GraphQLNonNull) else kind
    if is_input_object_type(raw):
        _keys(binding, {"object"}, {"object"}, location)
        values = binding["object"]
        if not isinstance(values, dict) or len(values) > 32:
            _fail(location, "input object needs at most 32 reviewed field bindings")
        unknown = values.keys() - raw.fields.keys()
        if unknown:
            _fail(location, f"unknown input fields: {', '.join(sorted(unknown))}")
        for name, field in raw.fields.items():
            if (
                isinstance(field.type, GraphQLNonNull)
                and field.default_value is Undefined
                and name not in values
            ):
                _fail(location, f"required input field {name} is unmapped")
        return {
            "object": {
                name: _graphql_input_binding(
                    raw.fields[name].type, value, base, location + "." + name, depth + 1
                )
                for name, value in values.items()
            }
        }
    descriptor = _graphql_type(kind, location)
    if descriptor["kind"] != "scalar":
        _fail(location, "GraphQL input bindings require scalar leaves")
    result = _binding(binding, base, descriptor["type"], descriptor["nullable"], location)
    if "literal" in binding:
        errors = []
        coerce_input_value(
            binding["literal"], kind, on_error=lambda path, value, error: errors.append(str(error))
        )
        if errors:
            _fail(location, f"invalid GraphQL literal: {errors[0]}")
    return result


def compile_graphql_entity(sdl: str | Any, entity: dict) -> dict:
    """Generate and validate a query from schema field paths and selected output columns."""
    schema = build_schema(sdl) if isinstance(sdl, str) else sdl
    base = _entity_base(entity)
    transport = entity["transport"]
    _keys(
        transport,
        {"kind", "field_path", "field_arguments", "result_path", "pagination"},
        {"kind", "field_path", "field_arguments", "result_path", "pagination"},
        base["name"],
    )
    field_path = _path(transport["field_path"], base["name"])
    result_path = _path(transport["result_path"], base["name"])
    pagination = transport["pagination"]
    _keys(pagination, {"kind", "page_info_path"}, {"kind", "page_info_path"}, base["name"])
    if pagination["kind"] != "cursor":
        _fail(base["name"], "GraphQL pilot supports cursor pagination only")
    page_info_path = _path(pagination["page_info_path"], base["name"])
    current = schema.query_type
    variables, declarations, fields = {}, {}, []
    seen_field_arguments = set()
    for name in field_path:
        if not is_object_type(current) or name not in current.fields:
            _fail(base["name"], f"unknown query field {name!r}")
        field = current.fields[name]
        supplied = transport["field_arguments"].get(name, {})
        if name in transport["field_arguments"]:
            seen_field_arguments.add(name)
        calls = []
        for argument_name, binding in supplied.items():
            if argument_name not in field.args:
                _fail(base["name"], f"unknown GraphQL argument {name}.{argument_name}")
            argument = field.args[argument_name]
            if not isinstance(binding, dict):
                _fail(base["name"], f"GraphQL binding {name}.{argument_name}: expected an object")
            variable = "cursor" if binding.get("cursor") else f"{name}_{argument_name}"
            if variable in variables:
                _fail(base["name"], f"ambiguous GraphQL variable {variable}")
            variables[variable] = _graphql_input_binding(argument.type, binding, base, variable)
            declarations[variable] = str(argument.type)
            calls.append(f"{argument_name}: ${variable}")
        fields.append(name + ("(" + ", ".join(calls) + ")" if calls else ""))
        current = get_named_type(field.type)
    if seen_field_arguments != transport["field_arguments"].keys():
        _fail(base["name"], "field_arguments includes a field outside field_path")
    connection = current
    for name in result_path:
        if not is_object_type(current) or name not in current.fields:
            _fail(base["name"], f"unknown GraphQL result field {name!r}")
        value = current.fields[name].type
        current = get_named_type(value)
    raw = value.of_type if isinstance(value, GraphQLNonNull) else value
    if not isinstance(raw, GraphQLList):
        _fail(base["name"], "selected GraphQL result must be a list")
    selection = {}
    for column in entity.get("columns", []):
        if "source_argument" in column:
            base["columns"].append(_column(base, column))
            continue
        path = _path(column.get("path"), base["name"])
        target = current
        # A nullable list entry is not an entity; the runtime rejects non-object
        # rows instead of silently discarding them or inventing a NULL grain.
        parent_nullable = False
        for index, name in enumerate(path):
            interface_field = is_interface_type(target)
            if not (is_object_type(target) or interface_field) or name not in target.fields:
                _fail(base["name"], f"unknown GraphQL selected field {name!r}")
            field = target.fields[name]
            if field.args:
                _fail(base["name"], "selected fields with arguments require a separate entity")
            target = get_named_type(field.type)
            if interface_field and (
                index != len(path) - 1
                or not (is_scalar_type(target) or is_enum_type(target))
                or isinstance(
                    field.type.of_type if isinstance(field.type, GraphQLNonNull) else field.type, GraphQLList
                )
            ):
                _fail(base["name"], "interface selections require a common scalar field")
            if index < len(path) - 1:
                unwrapped = field.type.of_type if isinstance(field.type, GraphQLNonNull) else field.type
                if isinstance(unwrapped, GraphQLList):
                    _fail(
                        base["name"], "selected paths cannot traverse lists; select the list column instead"
                    )
                parent_nullable |= not isinstance(field.type, GraphQLNonNull)
        descriptor = _graphql_type(field.type, base["name"] + "." + column["name"], column.get("selection"))
        descriptor["nullable"] |= parent_nullable
        base["columns"].append(_column(base, column, descriptor))
        _selection_merge(selection, result_path + path, column.get("selection"))
    page_type = connection
    for name in page_info_path:
        if not is_object_type(page_type) or name not in page_type.fields:
            _fail(base["name"], f"unknown pageInfo field {name!r}")
        page_type = get_named_type(page_type.fields[name].type)
    if not is_object_type(page_type) or not {"hasNextPage", "endCursor"} <= page_type.fields.keys():
        _fail(base["name"], "pageInfo must provide hasNextPage and endCursor")
    if (
        str(page_type.fields["hasNextPage"].type) != "Boolean!"
        or str(page_type.fields["endCursor"].type) != "String"
    ):
        _fail(base["name"], "pageInfo requires Boolean! hasNextPage and nullable String endCursor")
    if "cursor" not in variables:
        _fail(base["name"], "cursor pagination requires an explicit cursor binding")
    _selection_merge(selection, page_info_path, {"hasNextPage": True, "endCursor": True})
    body = _selection_sql(selection)
    for field in reversed(fields):
        body = field + " { " + body + " }"
    operation_name = "Generated_" + base["name"]
    args = ", ".join(f"${name}: {kind}" for name, kind in declarations.items())
    document = f"query {operation_name}" + (f"({args})" if args else "") + " { " + body + " }"
    errors = validate(schema, parse(document))
    if errors:
        _fail(
            base["name"],
            "generated GraphQL query is invalid: " + "; ".join(error.message for error in errors),
        )
    base["transport"] = {
        "kind": "graphql",
        "document": document,
        "operation_name": operation_name,
        "variables": variables,
        "result_path": field_path + result_path,
        "pagination": {
            "kind": "cursor",
            "page_info_path": field_path + page_info_path,
            "cursor_variable": "cursor",
        },
    }
    base["source"] = {
        "field_path": field_path,
        "result_type": current.name,
        "result_nullable": not isinstance(value, GraphQLNonNull),
        "item_nullable": not isinstance(raw.of_type, GraphQLNonNull),
    }
    return _complete(base)


def compile_contract(openapi_specs: dict[str, dict], graphql_sdl: str, overlay: dict) -> dict:
    """Compile the limited explicitly selected entities, never the complete API surface."""
    _keys(
        overlay,
        {
            "format",
            "version",
            "entities",
            "sources",
            "model",
            "scopes",
            "functions",
            "relationships",
            "shared_dimensions",
            "crossfield",
            "cohorts",
        },
        {"version", "entities"},
        "overlay",
    )
    if "format" in overlay and overlay["format"] != "vgi-github-semantic-overlay":
        _fail("overlay", "unsupported format")
    if overlay["version"] != 1:
        _fail("overlay", "unsupported version")
    if not isinstance(overlay["entities"], list) or not overlay["entities"]:
        _fail("overlay", "entities must be a nonempty list")
    entities = []
    graphql_schema = None
    for entity in overlay["entities"]:
        _keys(
            entity,
            {"name", "description", "arguments", "columns", "grain", "transport", "semantics", "policy"},
            {"name", "arguments", "columns", "grain", "transport"},
            "entity",
        )
        kind = entity["transport"].get("kind")
        if kind == "rest":
            product = entity["transport"].get("product", "api.github.com")
            if product not in openapi_specs:
                _fail(entity["name"], f"missing OpenAPI product {product!r}")
            entities.append(compile_rest_entity(openapi_specs[product], entity))
        elif kind == "graphql":
            if graphql_schema is None:
                graphql_schema = build_schema(graphql_sdl)
            entities.append(compile_graphql_entity(graphql_schema, entity))
        else:
            _fail(entity["name"], f"unknown transport kind {kind!r}")
    if len({entity["name"].lower() for entity in entities}) != len(entities):
        _fail("overlay", "entity names must be unique ignoring case")
    contract = {"format": "vgi-github-entities", "version": 1, "entities": entities}
    if "functions" in overlay:
        from .graph import compile_functions
        from .cohorts import compile_cohorts

        return compile_cohorts(compile_functions(contract, overlay), overlay.get("cohorts", {}))
    if set(overlay) & {"scopes", "relationships", "shared_dimensions"}:
        _fail("overlay", "scopes and relationship metadata require public function declarations")
    return contract
