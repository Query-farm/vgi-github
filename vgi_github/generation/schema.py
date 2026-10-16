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
    GraphQLString,
    Undefined,
    build_schema,
    coerce_input_value,
    get_named_type,
    is_enum_type,
    is_input_object_type,
    is_interface_type,
    is_object_type,
    is_scalar_type,
    is_union_type,
    parse,
    validate,
)


class SchemaError(ValueError):
    """A selected source contract cannot be represented safely."""


SCALARS = {"VARCHAR", "BIGINT", "DOUBLE", "BOOLEAN", "DATE", "TIMESTAMP WITH TIME ZONE"}
LIST_ARGUMENTS = {"VARCHAR[]", "BIGINT[]"}
GRAPHQL_SCALARS = {
    "String": "VARCHAR",
    "ID": "VARCHAR",
    "Int": "BIGINT",
    "BigInt": "BIGINT",
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
    if schema["kind"] == "map":
        return f"MAP(VARCHAR, {_sql_type(schema['value'])})"
    return (
        "STRUCT("
        + ", ".join(
            '"' + field["name"].replace('"', '""') + '" ' + _sql_type(field["schema"])
            for field in schema["fields"]
        )
        + ")"
    )


def _variant_schema(branches: dict, nullable: bool, *, discriminator=None, mode="oneOf") -> dict:
    """Represent alternatives as native fields, without coercing their values."""
    tag = {"kind": "scalar", "type": "VARCHAR", "nullable": False}
    if discriminator is None:
        tag = {"kind": "list", "item": tag, "nullable": False}
    fields = [{"name": discriminator or "matched_types", "schema": tag, "required": True, "nullable": False}]
    for name, descriptor in branches.items():
        fields.append(
            {
                "name": name,
                "schema": {**descriptor, "nullable": True},
                "required": True,
                "nullable": True,
            }
        )
    return {
        "kind": "struct",
        "fields": fields,
        "nullable": nullable,
        "variant": {"discriminator": discriminator, "mode": mode, "names": list(branches)},
    }


def _map_value_node(node: dict, location: str) -> dict:
    """Only homogeneous dictionaries with an explicit value contract are maps."""
    if node.get("properties"):
        _fail(location, "mixed fixed properties and dynamic map entries require a separate contract")
    if node.get("patternProperties") or "propertyNames" in node:
        _fail(location, "constrained dictionary keys require a separate contract")
    value = node.get("additionalProperties")
    if not isinstance(value, dict) or not value:
        _fail(location, "map requires an explicitly typed additionalProperties value schema")
    return value


def _openapi_type(
    document: dict,
    node: dict,
    location: str,
    selection: dict | None = None,
    trail: tuple[str, ...] = (),
    *,
    tagged: bool = False,
    discriminator: dict | None = None,
) -> dict:
    if "$ref" in node:
        ref = node["$ref"]
        if ref in trail:
            _fail(location, f"selected recursive reference {ref}; narrow the selection")
        trail = (*trail, ref)
    node = _resolved(document, node, location)
    if tagged and ("oneOf" in node or "anyOf" in node):
        mode = "oneOf" if "oneOf" in node else "anyOf"
        alternatives = node[mode]
        names = [f"variant_{index + 1}" for index in range(len(alternatives))]
        if not alternatives or selection is not None and set(selection) != set(names):
            _fail(location, "tagged selection must include every numbered source variant")
        branches = {}
        for name, value in zip(names, alternatives, strict=True):
            selected = selection[name] if selection is not None else None
            branches[name] = _openapi_type(
                document,
                value,
                location + "." + name,
                None if selected is True else selected,
                trail,
                tagged=True,
            )
        descriptor = _variant_schema(branches, node.get("nullable", False), mode=mode)
        if discriminator is not None:
            _keys(discriminator, {"path", "mapping", "comment"}, {"path", "mapping", "comment"}, location)
            discriminator_path = _path(discriminator["path"], location)
            mapping = discriminator["mapping"]
            if (
                not isinstance(mapping, dict)
                or not mapping
                or any(
                    not isinstance(key, str) or not key.strip() or target not in names
                    for key, target in mapping.items()
                )
                or set(mapping.values()) != set(names)
            ):
                _fail(location, "reviewed discriminator mapping must cover every numbered variant")
            if not isinstance(discriminator["comment"], str) or not discriminator["comment"].strip():
                _fail(location, "reviewed discriminator mapping requires an evidence comment")
            for name, variant in zip(names, alternatives, strict=True):
                field, _, _ = _rest_field(document, variant, discriminator_path, location)
                selected = _openapi_type(document, field, location)
                if selected["kind"] != "scalar" or selected["type"] != "VARCHAR":
                    _fail(location, "reviewed discriminator path must select a string in every variant")
                if "enum" in selected and any(
                    event not in selected["enum"] for event, target in mapping.items() if target == name
                ):
                    _fail(location, "reviewed discriminator mapping contradicts the pinned field enum")
            descriptor["variant"]["source_discriminator"] = copy.deepcopy(discriminator)
        return descriptor
    if discriminator is not None:
        _fail(location, "reviewed discriminator requires a tagged oneOf/anyOf selection")
    if any(key in node for key in ("oneOf", "anyOf", "not")):
        _fail(location, "selected variants (oneOf/anyOf/not) require an explicit supported contract")
    kind = node.get("type", "object" if "properties" in node or "additionalProperties" in node else None)
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
            value = _map_value_node(node, location)
            return {
                "kind": "map",
                "key": {"kind": "scalar", "type": "VARCHAR", "nullable": False},
                "value": _openapi_type(document, value, location + "{}", selection, trail, tagged=tagged),
                "nullable": nullable,
            }
        if selection is None and node.get("additionalProperties", False) is not False:
            _fail(location, "mixed fixed properties and dynamic map entries require an explicit projection")
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
                document,
                properties[name],
                f"{location}.{name}",
                None if child is True else child,
                trail,
                tagged=tagged,
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
            "item": _openapi_type(document, node["items"], location + "[]", selection, trail, tagged=tagged),
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


def _rest_variant_fields(document: dict, node: dict, path: list[str], location: str):
    """Select compatible fields through reviewed object alternatives, retaining absence."""

    def walk(value, remaining, required=True, nullable=False):
        value = _resolved(document, value, location)
        nullable |= value.get("nullable", False)
        alternatives = value.get("oneOf", value.get("anyOf"))
        if remaining and alternatives is not None:
            return [result for item in alternatives for result in walk(item, remaining, required, nullable)]
        if not remaining:
            return [(value, required, nullable)]
        name, *tail = remaining
        if name not in value.get("properties", {}):
            return [None]
        return walk(value["properties"][name], tail, required and name in value.get("required", []), nullable)

    candidates = walk(node, path)
    present = [value for value in candidates if value is not None]
    if not present:
        _fail(location, f"unknown selected property path {path!r}")
    return present, all(value is not None and value[1] for value in candidates)


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
                "max_length",
                "pattern",
                "minimum",
                "example",
                "enum",
            },
            {"name", "type"},
            name,
        )
        arg_name = _identifier(item["name"], f"{name}.argument")
        if arg_name.lower() in names:
            _fail(name, f"duplicate argument {arg_name}")
        names.add(arg_name.lower())
        if item["type"] not in SCALARS | LIST_ARGUMENTS:
            _fail(name, f"unsupported argument type {item['type']!r}")
        if item.get("position", index) != index:
            _fail(name, "argument positions must match their declared order")
        if not isinstance(item.get("nullable", False), bool):
            _fail(name, "argument nullable must be boolean")
        if "default" in item and (item["default"] is not None or not item.get("nullable")):
            _fail(name, "only nullable arguments may declare a NULL default")
        if "min_length" in item and (
            item["type"] != "VARCHAR"
            or type(item["min_length"]) is not int
            or not 0 <= item["min_length"] < 2**63
        ):
            _fail(name, "min_length requires a nonnegative integer and VARCHAR argument")
        if "max_length" in item and (
            item["type"] != "VARCHAR"
            or type(item["max_length"]) is not int
            or not 0 <= item["max_length"] < 2**63
        ):
            _fail(name, "max_length requires a nonnegative integer and VARCHAR argument")
        if item.get("max_length", item.get("min_length", 0)) < item.get("min_length", 0):
            _fail(name, "max_length must be at least min_length")
        if "pattern" in item:
            if item["type"] != "VARCHAR" or not isinstance(item["pattern"], str):
                _fail(name, "pattern requires a regular expression and VARCHAR argument")
            try:
                if len(item["pattern"].encode("utf-8")) > 4096:
                    _fail(name, "pattern exceeds 4096 UTF-8 bytes")
                re.compile(item["pattern"])
            except (re.error, UnicodeEncodeError):
                _fail(name, "pattern must be a valid regular expression")
        if "minimum" in item and (item["type"] != "BIGINT" or type(item["minimum"]) is not int):
            _fail(name, "minimum requires a BIGINT argument and integer bound")
        if "enum" in item:
            values = item["enum"]
            expected = {"VARCHAR": str, "BIGINT": int, "BOOLEAN": bool}.get(item["type"])
            if (
                expected is None
                or not isinstance(values, list)
                or not values
                or any(type(value) is not expected for value in values)
                or len(set(values)) != len(values)
            ):
                _fail(
                    name,
                    "enum requires distinct non-NULL values matching a VARCHAR, BIGINT or BOOLEAN argument",
                )
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
                matches = (
                    isinstance(value, list)
                    and bool(value)
                    and all(valid[kind[:-2]](entry) for entry in value)
                    if kind in LIST_ARGUMENTS
                    else valid[kind](value)
                )
            except (ValueError, OverflowError):
                matches = False
            if not matches:
                _fail(name, f"example must be a non-NULL scalar matching {kind}")
            if "min_length" in item and (
                len(value) < item["min_length"] or item["min_length"] == 1 and not value.strip()
            ):
                _fail(name, "example must satisfy min_length")
            if "max_length" in item and len(value) > item["max_length"]:
                _fail(name, "example must satisfy max_length")
            if "pattern" in item and re.search(item["pattern"], value) is None:
                _fail(name, "example must satisfy pattern")
            if "minimum" in item and value < item["minimum"]:
                _fail(name, "example must satisfy minimum")
            if "enum" in item and value not in item["enum"]:
                _fail(name, "example must satisfy enum")
        argument = {**item, "position": index, "nullable": item.get("nullable", False)}
        if item["type"] in LIST_ARGUMENTS:
            argument["schema"] = {
                "kind": "list",
                "nullable": argument["nullable"],
                "item": {"kind": "scalar", "type": item["type"][:-2], "nullable": False},
            }
        arguments.append(argument)
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
    _keys(
        column,
        {
            "name",
            "path",
            "source_argument",
            "source_ordinal",
            "source_response",
            "source_entry",
            "source_value",
            "source_document_path",
            "source_index",
            "allow_empty_identity",
            "selection",
            "description",
            "on_types",
            "variant_paths",
            "representation",
            "discriminator",
        },
        {"name"},
        location,
    )
    name = _identifier(column["name"], location)
    if "variant_paths" in column and (column["variant_paths"] is not True or "path" not in column):
        _fail(location, "variant_paths requires true on a selected response path")
    if "representation" in column and (
        column["representation"] != "tagged" or "path" not in column and column.get("source_entry") != "value"
    ):
        _fail(location, "representation requires tagged on a selected response path")
    if "discriminator" in column and column.get("representation") != "tagged":
        _fail(location, "discriminator requires an explicitly tagged response column")
    selectors = (
        "source_argument",
        "source_ordinal",
        "source_response",
        "source_entry",
        "source_value",
        "source_document_path",
        "source_index",
    )
    if sum(key in column for key in selectors) + ("path" in column and "source_entry" not in column) != 1:
        _fail(location, "specify exactly one response path or source selector")
    result = {"name": name, "description": column.get("description", ""), "required": required}
    if "source_index" in column:
        if (
            type(column["source_index"]) is not int
            or column["source_index"] < 0
            or any(key in column for key in ("selection", "on_types", "variant_paths", "representation"))
        ):
            _fail(location, "source_index requires a nonnegative scalar tuple index")
        result["source_index"] = column["source_index"]
    elif "source_document_path" in column:
        if any(key in column for key in ("on_types", "variant_paths", "representation", "discriminator")):
            _fail(location, "source_document_path cannot select row variants")
        result["source_document_path"] = _path(column["source_document_path"], location)
    elif "source_value" in column:
        if column["source_value"] is not True or any(
            key in column for key in ("path", "selection", "on_types", "variant_paths", "representation")
        ):
            _fail(location, "source_value requires true and selects the complete scalar array item")
        result["source_value"] = True
    elif "source_entry" in column:
        entry = column["source_entry"]
        if entry not in {"key", "value"} or "on_types" in column or "variant_paths" in column:
            _fail(location, "source_entry must select a dictionary key or value")
        result["source_entry"] = entry
        if entry == "key":
            if any(key in column for key in ("path", "selection", "representation", "discriminator")):
                _fail(location, "dictionary keys cannot select nested response fields")
        else:
            result["path"] = _path(column.get("path", []), location, empty=True)
    elif "source_response" in column:
        if "selection" in column or "on_types" in column:
            _fail(location, "source_response cannot select JSON or GraphQL fields")
        result["source_response"] = column["source_response"]
    elif "source_ordinal" in column:
        if column["source_ordinal"] is not True or "selection" in column or "on_types" in column:
            _fail(location, "source_ordinal requires true and cannot select response fields")
        schema = {"kind": "scalar", "type": "BIGINT", "nullable": False}
        result["source_ordinal"] = True
    elif "source_argument" in column:
        args = {arg["name"]: arg for arg in base["arguments"]}
        argument = args.get(column["source_argument"])
        if argument is None:
            _fail(location, "unknown source_argument")
        if "selection" in column:
            _fail(location, "source_argument cannot have a selection")
        if column.get("allow_empty_identity") and argument.get("min_length", 0) > 0:
            _fail(location, "allow_empty_identity contradicts the source argument minimum length")
        schema = copy.deepcopy(
            argument.get(
                "schema", {"kind": "scalar", "type": argument["type"], "nullable": argument["nullable"]}
            )
        )
        result["source_argument"] = argument["name"]
    else:
        result["path"] = _path(
            column["path"],
            location,
            empty=bool(column.get("selection"))
            or column.get("representation") == "tagged"
            or schema is not None
            and schema["kind"] == "map",
        )
    if schema is None:
        _fail(location, "missing compiled column schema")
    if (
        "discriminator" in column
        and schema.get("variant", {}).get("source_discriminator") != column["discriminator"]
    ):
        _fail(location, "discriminator requires a compiled REST tagged variant")
    result.update(type=_sql_type(schema), nullable=schema["nullable"], schema=schema)
    if "allow_empty_identity" in column:
        if column["allow_empty_identity"] is not True or result["type"] != "VARCHAR":
            _fail(location, "allow_empty_identity requires true on a VARCHAR column")
        result["allow_empty_identity"] = True
    return result


def _complete(base: dict) -> dict:
    columns = {column["name"].lower(): column for column in base["columns"]}
    if not columns or len(columns) != len(base["columns"]):
        _fail(base["name"], "columns must be nonempty and unique ignoring case")
    policy = base.get("policy", {})
    if policy:
        _keys(
            policy,
            {"row_assertions", "required_non_null_fields", "require_one_row"},
            set(),
            base["name"] + ".policy",
        )
    if "require_one_row" in policy:
        transport = base.get("transport", {})
        if (
            policy["require_one_row"] is not True
            or transport.get("pagination", {}).get("kind") != "none"
            or transport.get("kind") not in {"rest", "graphql"}
            or transport["kind"] == "rest"
            and transport.get("result_shape") != "object"
        ):
            _fail(base["name"], "require_one_row requires true on an unpaginated single-object source")
    if "required_non_null_fields" in policy:
        qualified = policy["required_non_null_fields"]
        if (
            not isinstance(qualified, list)
            or not qualified
            or any(not isinstance(name, str) for name in qualified)
            or len(set(qualified)) != len(qualified)
            or any(name.lower() not in columns or columns[name.lower()]["name"] != name for name in qualified)
        ):
            _fail(base["name"], "required_non_null_fields must name distinct selected columns")
        # This is a reviewed source qualification, not a claim that the upstream
        # schema requires the field. The original response schema is retained in
        # provenance; the decoder rejects missing/null identities before emission.
        for name in qualified:
            column = columns[name.lower()]
            column["required"] = True
            column["nullable"] = False
            column["schema"]["nullable"] = False
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
    if "row_assertions" in policy:
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
            if assertion["comparison"] not in {"github_login", "equal", "equal_if_present"}:
                _fail(base["name"], "unsupported row assertion comparison")
            if (
                column is None
                or column["name"] != column_name
                or column["schema"]["kind"] != "scalar"
                or argument is None
                or column["type"] != argument["type"]
                or (assertion["comparison"] == "github_login" and column["type"] != "VARCHAR")
                or argument["nullable"]
            ):
                _fail(
                    base["name"],
                    "row assertions require a VARCHAR column and a non-null VARCHAR argument"
                    if assertion["comparison"] == "github_login"
                    else "row assertions require matching scalar types and a non-null argument",
                )
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
                binding["transform"]
                not in {
                    "repository_owner",
                    "repository_name",
                    "decimal_string_to_bigint",
                }
                or argument["type"] != "VARCHAR"
            ):
                _fail(location, "reviewed binding transforms require a VARCHAR argument")
            actual = "BIGINT" if binding["transform"] == "decimal_string_to_bigint" else "VARCHAR"
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
        validators = {
            "VARCHAR": lambda: isinstance(value, str),
            "BIGINT": lambda: isinstance(value, int) and not isinstance(value, bool),
            "DOUBLE": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
            "BOOLEAN": lambda: isinstance(value, bool),
            "DATE": lambda: isinstance(value, str),
            "TIMESTAMP WITH TIME ZONE": lambda: isinstance(value, str),
        }
        valid = (value is None and nullable) or validators.get(expected, lambda: False)()
        if expected in LIST_ARGUMENTS and isinstance(value, list) and value:
            valid = all(
                type(item) is str
                if expected == "VARCHAR[]"
                else type(item) is int and -(2**63) <= item < 2**63
                for item in value
            )
        if not valid:
            _fail(location, f"literal does not match {expected}")
    return copy.deepcopy(binding)


def _rest_bindings(document: dict, path_item: dict, operation: dict, transport: dict, base: dict) -> dict:
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
            parameter_schema = _resolved(document, parameter.get("schema", {}), base["name"])
            alternatives = parameter_schema.get("oneOf", parameter_schema.get("anyOf"))
            if alternatives is not None:
                descriptors = [_openapi_type(document, alternative, name) for alternative in alternatives]
                if not descriptors or any(item["kind"] != "scalar" for item in descriptors):
                    _fail(base["name"], "parameter variants must be explicit scalar alternatives")
                accepted = []
                for candidate in descriptors:
                    try:
                        _binding(binding, base, candidate["type"], candidate["nullable"], name)
                    except SchemaError:
                        continue
                    accepted.append(candidate)
                if len(accepted) != 1:
                    _fail(base["name"], f"{name} binding must select exactly one scalar parameter variant")
                descriptor = accepted[0]
            else:
                descriptor = _openapi_type(document, parameter_schema, f"{base['name']}.{name}")
            if descriptor["kind"] == "list":
                if (
                    place != "query"
                    or _sql_type(descriptor) not in LIST_ARGUMENTS
                    or parameter.get("style", "form") != "form"
                    or parameter.get("explode", True) is not True
                    or parameter.get("allowReserved", False) is not False
                    or any(key in parameter_schema for key in ("minItems", "maxItems", "uniqueItems"))
                ):
                    _fail(base["name"], "query arrays require an unconstrained scalar form/explode contract")
                normalized.setdefault("query_parameter_schemas", {})[name] = {
                    **descriptor,
                    "nullable": not parameter.get("required", False) or descriptor["nullable"],
                }
            elif descriptor["kind"] != "scalar":
                _fail(base["name"], "transport parameters require a scalar or reviewed query array")
            normalized[key][name] = _binding(
                binding,
                base,
                _sql_type(descriptor),
                descriptor["nullable"] or (place == "query" and not parameter.get("required", False)),
                name,
            )
            if "literal" in binding and "enum" in descriptor and binding["literal"] not in descriptor["enum"]:
                _fail(base["name"], f"literal outside the allowed enum for {name}")
        for (parameter_place, name), parameter in parameters.items():
            if parameter_place == place and parameter.get("required") and name not in normalized[key]:
                _fail(base["name"], f"required {place} parameter {name!r} is unmapped")
    if "allow_empty_path_parameters" in transport:
        names = transport["allow_empty_path_parameters"]
        if (
            not isinstance(names, list)
            or not names
            or any(not isinstance(name, str) for name in names)
            or len(names) != len(set(names))
        ):
            _fail(base["name"], "allow_empty_path_parameters requires distinct bound path parameter names")
        for name in names:
            parameter = parameters.get(("path", name))
            if parameter is None or name not in normalized["path_bindings"]:
                _fail(base["name"], "allow_empty_path_parameters requires a bound path parameter")
            descriptor = _resolved(document, parameter.get("schema", {}), base["name"])
            if (
                descriptor.get("type") != "string"
                or descriptor.get("minLength", 0) != 0
                or "enum" in descriptor
                and "" not in descriptor["enum"]
                or "pattern" in descriptor
                and re.search(descriptor["pattern"], "") is None
                or "transform" in normalized["path_bindings"][name]
            ):
                _fail(base["name"], "empty path opt-in requires an unconstrained empty VARCHAR binding")
        normalized["allow_empty_path_parameters"] = list(names)
    return normalized


def _compile_rest_content(
    document: dict, entity: dict, base: dict, path: str, path_item: dict, operation: dict
) -> dict:
    """Compile an HTTP representation envelope without inventing JSON properties."""
    transport = entity["transport"]
    if set(transport) & {
        "item_length",
        "result_path",
        "result_shape",
        "response_status",
        "response_variants",
        "response_assertions",
        "response_media_type",
        "response_variant",
        "accept",
        "empty_response_statuses",
    }:
        _fail(base["name"], "content responses cannot select JSON result fields or assertions")
    content = transport["content"]
    _keys(
        content,
        {"accept", "response_statuses", "pending_statuses", "text_encoding"},
        {"accept", "response_statuses"},
        base["name"],
    )
    statuses = content["response_statuses"]
    if (
        not isinstance(statuses, list)
        or not statuses
        or len(set(statuses)) != len(statuses)
        or any(
            not isinstance(status, str) or not re.fullmatch(r"[23][0-9]{2}|404", status)
            for status in statuses
        )
    ):
        _fail(
            base["name"],
            "content response_statuses must be distinct successful/redirect statuses or explicit 404",
        )
    accept = content["accept"]
    if not isinstance(accept, str) or not accept or any(char in accept for char in "\r\n"):
        _fail(base["name"], "content accept requires one media type without newlines")
    responses = {}
    declared_media = set()
    for status in statuses:
        response = operation.get("responses", {}).get(status)
        if response is None:
            _fail(base["name"], f"missing response status {status}")
        response = _resolved(document, response, base["name"])
        responses[status] = response
        declared_media.update(response.get("content", {}))
        if (
            status.startswith("3")
            and not any(key.lower() == "location" for key in response.get("headers", {}))
            and not re.search(r"\bredirect(?:s|ed)?\b", operation.get("description", ""), re.IGNORECASE)
        ):
            _fail(
                base["name"],
                "content redirects require a declared Location header or pinned redirect documentation",
            )
    if (
        accept not in declared_media
        and accept not in operation.get("description", "")
        and not (
            accept == "application/vnd.github+json"
            and (any(status.startswith("3") for status in statuses) or set(statuses) <= {"204", "404"})
        )
    ):
        _fail(base["name"], "content accept must be declared by the pinned response or operation description")
    pending = content.get("pending_statuses", [])
    if (
        not isinstance(pending, list)
        or len(set(pending)) != len(pending)
        or any(
            status != "202" or status not in responses or responses[status].get("content")
            for status in pending
        )
    ):
        _fail(base["name"], "pending_statuses requires a declared bodyless 202 response")
    if "text_encoding" in content and content["text_encoding"] != "utf-8":
        _fail(base["name"], "content text_encoding supports explicit strict utf-8 only")
    descriptors = {
        "status_code": ("BIGINT", False),
        "content_type": ("VARCHAR", False),
        "byte_length": ("BIGINT", False),
        "pending": ("BOOLEAN", False),
        "body": ("BLOB", bool(pending)),
    }
    if content.get("text_encoding"):
        descriptors["body_text"] = ("VARCHAR", bool(pending))
    for column in entity.get("columns", []):
        if "source_argument" in column:
            base["columns"].append(_column(base, column))
        elif column.get("source_response") in descriptors:
            kind, nullable = descriptors[column["source_response"]]
            base["columns"].append(
                _column(base, column, {"kind": "scalar", "type": kind, "nullable": nullable})
            )
        else:
            _fail(base["name"], "content columns require source_argument or an available source_response")
    pagination = transport.get("pagination", {"kind": "none"})
    if pagination != {"kind": "none"}:
        _fail(base["name"], "content responses require pagination none")
    base["transport"] = {
        "kind": "rest",
        "operation_id": transport["operation_id"],
        "path": path,
        "method": "GET",
        "product": transport.get("product", "api.github.com"),
        **_rest_bindings(document, path_item, operation, transport, base),
        "pagination": pagination,
        "content": copy.deepcopy(content),
    }
    base["source"] = {
        "response_sha256": closure_hash(document, responses),
        "response_schema": reference_closure(document, responses),
        "representation": "http_content",
        "result_nullable": False,
        "item_nullable": False,
    }
    return _complete(base)


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
            "response_assertions",
            "content",
            "allow_empty_path_parameters",
            "response_media_type",
            "response_variant",
            "accept",
            "empty_response_statuses",
            "authentication",
            "item_length",
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
    if "authentication" in transport and (
        transport["authentication"] != "anonymous"
        or "does not accept authentication" not in operation.get("description", "").lower()
        or "content" in transport
    ):
        _fail(
            base["name"],
            "anonymous authentication requires pinned operation documentation and JSON transport",
        )
    if "content" in transport:
        return _compile_rest_content(document, entity, base, path, path_item, operation)
    status = transport.get("response_status", "200")
    response = operation.get("responses", {}).get(status)
    if response is None:
        _fail(base["name"], f"missing response status {status}")
    response = _resolved(document, response, base["name"])
    media_type = transport.get("response_media_type", "application/json")
    accept = transport.get("accept", media_type if "response_media_type" in transport else None)
    if not isinstance(media_type, str) or not (
        media_type == "application/json"
        or media_type.startswith("application/")
        and media_type.endswith("+json")
        or media_type.startswith("application/")
        and accept == media_type + "+json"
    ):
        _fail(base["name"], "selected response media must declare a JSON representation")
    node = response.get("content", {}).get(media_type, {}).get("schema")
    if node is None:
        _fail(base["name"], f"selected response needs a pinned {media_type} schema")
    if accept is not None and (
        not isinstance(accept, str)
        or not accept
        or any(character in accept for character in "\r\n")
        or accept not in response.get("content", {})
        and accept not in operation.get("description", "")
    ):
        _fail(base["name"], "JSON Accept media must be pinned in response content or operation documentation")
    original = node
    projection = {"media_type": media_type}
    if "response_variant" in transport:
        variant = transport["response_variant"]
        _keys(variant, {"kind", "index", "comment"}, {"kind", "index", "comment"}, base["name"])
        alternatives = (
            _resolved(document, node, base["name"]).get(variant["kind"])
            if isinstance(variant["kind"], str)
            else None
        )
        if (
            not isinstance(variant["kind"], str)
            or variant["kind"] not in {"oneOf", "anyOf"}
            or type(variant["index"]) is not int
            or not isinstance(alternatives, list)
            or not 0 <= variant["index"] < len(alternatives)
            or not isinstance(variant["comment"], str)
            or not variant["comment"].strip()
            or accept is None
        ):
            _fail(base["name"], "response_variant requires a reviewed pinned alternative and explicit media")
        node = alternatives[variant["index"]]
        if _resolved(document, node, base["name"]).get("type") != "array":
            _fail(base["name"], "selected response_variant must be a top-level array schema")
        projection["variant"] = copy.deepcopy(variant)
    result_path = _path(transport.get("result_path", []), base["name"], empty=True)
    node, _, _ = _rest_field(document, node, result_path, base["name"])
    node = _resolved(document, node, base["name"])
    shape = transport.get("result_shape", "array")
    if "empty_response_statuses" in transport:
        empty_statuses = transport["empty_response_statuses"]
        empty_response = operation.get("responses", {}).get("204")
        if (
            empty_statuses != ["204"]
            or empty_response is None
            or _resolved(document, empty_response, base["name"]).get("content")
            or shape not in {"object", "array"}
            or base.get("policy", {}).get("require_one_row")
        ):
            _fail(
                base["name"],
                "empty_response_statuses requires a pinned bodyless 204 object or array alternative",
            )
    if shape == "array":
        if node.get("type") != "array" or "items" not in node:
            _fail(base["name"], "selected REST result must be an array")
        row = node["items"]
    elif shape == "object" and node.get("type", "object") == "object":
        row = node
    elif shape == "object_entries" and node.get("type", "object") == "object":
        if node.get("nullable", False):
            _fail(base["name"], "object_entries requires a non-null dictionary population")
        row = _map_value_node(node, base["name"])
    else:
        _fail(base["name"], "REST result_shape must match an array, object or typed object_entries schema")
    if "item_length" in transport:
        row_type = _resolved(document, row, base["name"])
        length = transport["item_length"]
        if (
            shape != "array"
            or type(length) is not int
            or not 1 <= length <= 32
            or row_type.get("type") != "array"
            or "items" not in row_type
            or length < row_type.get("minItems", 0)
            or length > row_type.get("maxItems", 32)
            or not any("source_index" in column for column in entity.get("columns", []))
        ):
            _fail(base["name"], "item_length requires a reviewed scalar tuple array of 1 to 32 items")
    rows = [row]
    if "response_variants" in transport:
        if transport["response_variants"] != "common_fields" or shape != "object" or "oneOf" not in row:
            _fail(base["name"], "common_fields requires an explicit object oneOf response")
        rows = row["oneOf"]
        if not rows:
            _fail(base["name"], "response variants must be nonempty")
    for column in entity.get("columns", []):
        if "source_index" in column:
            index = column["source_index"]
            if (
                "item_length" not in transport
                or type(index) is not int
                or not 0 <= index < transport["item_length"]
            ):
                _fail(base["name"], "source_index must be within the reviewed item_length")
            schema = _openapi_type(document, _resolved(document, row, base["name"])["items"], base["name"])
            if schema["kind"] != "scalar":
                _fail(base["name"], "source_index requires homogeneous typed scalar tuple items")
            base["columns"].append(_column(base, column, schema))
            continue
        if "source_document_path" in column:
            if shape != "array" or "response_variant" in transport:
                _fail(base["name"], "source_document_path requires an unambiguous JSON array response")
            field, required, parent_nullable = _rest_field(
                document, original, _path(column["source_document_path"], base["name"]), base["name"]
            )
            schema = _openapi_type(
                document, field, base["name"] + "." + column["name"], column.get("selection")
            )
            schema["nullable"] |= parent_nullable
            base["columns"].append(_column(base, column, schema, required=required))
            continue
        if "source_argument" in column or "source_ordinal" in column:
            if shape == "object_entries" and "source_ordinal" in column:
                _fail(base["name"], "object_entries uses dictionary keys, not source ordinals")
            base["columns"].append(_column(base, column))
            continue
        if "source_value" in column:
            schema = _openapi_type(document, row, base["name"] + "." + column["name"])
            if shape != "array" or schema["kind"] != "scalar":
                _fail(base["name"], "source_value requires an explicitly typed scalar array result")
            base["columns"].append(_column(base, column, schema))
            continue
        if shape == "object_entries":
            if column.get("source_entry") == "key":
                base["columns"].append(
                    _column(base, column, {"kind": "scalar", "type": "VARCHAR", "nullable": False})
                )
                continue
            if column.get("source_entry") != "value":
                _fail(base["name"], "object_entries columns require source_entry key/value selectors")
        elif "source_entry" in column:
            _fail(base["name"], "source_entry requires object_entries transport")
        field_path = _path(
            column.get("path", []),
            base["name"],
            empty=True,
        )
        schemas, required = [], True
        for variant in rows:
            if column.get("variant_paths"):
                fields, present = _rest_variant_fields(document, variant, field_path, base["name"])
            else:
                field, present, parent_nullable = _rest_field(document, variant, field_path, base["name"])
                fields = [(field, present, parent_nullable)]
            required &= present
            for field, _, parent_nullable in fields:
                if column.get("allow_empty_identity"):
                    descriptor = _resolved(document, field, base["name"])
                    if (
                        descriptor.get("minLength", 0) > 0
                        or "enum" in descriptor
                        and "" not in descriptor["enum"]
                        or "pattern" in descriptor
                        and re.search(descriptor["pattern"], "") is None
                    ):
                        _fail(base["name"], "allow_empty_identity contradicts the pinned string constraints")
                schema = _openapi_type(
                    document,
                    field,
                    base["name"] + "." + column["name"],
                    column.get("selection"),
                    tagged=column.get("representation") == "tagged",
                    discriminator=column.get("discriminator"),
                )
                schema["nullable"] |= parent_nullable
                schemas.append(schema)
        schema = _merge_schemas(schemas, base["name"] + "." + column["name"])
        base["columns"].append(_column(base, column, schema, required=required))
    if shape == "object_entries" and not any(
        column.get("source_entry") == "key" and column["name"] in base["grain"] for column in base["columns"]
    ):
        _fail(base["name"], "object_entries grain must include its selected dictionary key")
    normalized = _rest_bindings(document, path_item, operation, transport, base)
    pagination = transport.get("pagination", {"kind": "link" if shape == "array" else "none"})
    _keys(
        pagination,
        {
            "kind",
            "total_count_path",
            "reject_at_rows",
            "expected_count_argument",
            "unselected_collection_path",
        },
        {"kind"},
        base["name"],
    )
    if pagination["kind"] not in {"link", "none"} or (shape != "array" and pagination["kind"] != "none"):
        _fail(base["name"], "REST arrays require Link or explicit no pagination; objects require none")
    if shape == "array" and pagination["kind"] == "none":
        parameters = [
            _resolved(document, item, base["name"])
            for item in [*path_item.get("parameters", []), *operation.get("parameters", [])]
        ]
        if any(item.get("in") == "query" and item.get("name") in {"page", "per_page"} for item in parameters):
            _fail(base["name"], "REST arrays with page controls require Link pagination")
    if "unselected_collection_path" in pagination:
        collection_path = _path(pagination["unselected_collection_path"], base["name"])
        collection, _, _ = _rest_field(document, original, collection_path, base["name"])
        if shape != "object" or _resolved(document, collection, base["name"]).get("type") != "array":
            _fail(base["name"], "unselected_collection_path requires a pinned array in a singleton envelope")
        for column in base["columns"]:
            if "path" not in column:
                continue
            selected_path = [*result_path, *column["path"]]
            common = min(len(selected_path), len(collection_path))
            if selected_path[:common] == collection_path[:common]:
                _fail(base["name"], "unselected_collection_path cannot overlap selected response fields")
    if "reject_at_rows" in pagination and (
        shape != "array" or type(pagination["reject_at_rows"]) is not int or pagination["reject_at_rows"] < 1
    ):
        _fail(base["name"], "reject_at_rows requires a positive integer on a paginated array")
    if "expected_count_argument" in pagination:
        expected = next(
            (
                argument
                for argument in base["arguments"]
                if argument["name"] == pagination["expected_count_argument"]
            ),
            None,
        )
        if shape != "array" or expected is None or expected["type"] != "BIGINT" or expected["nullable"]:
            _fail(
                base["name"], "expected_count_argument requires an array and non-null BIGINT source argument"
            )
    if "total_count_path" in pagination:
        count_path = _path(pagination["total_count_path"], base["name"])
        count_field, count_required, count_nullable = _rest_field(
            document, original, count_path, base["name"]
        )
        count_type = _openapi_type(document, count_field, base["name"])
        if (
            shape != "array"
            or count_type != {"kind": "scalar", "type": "BIGINT", "nullable": False}
            or not count_required
            or count_nullable
        ):
            _fail(
                base["name"],
                "pagination total_count_path requires a required non-null integer response field "
                "and array result",
            )
    assertions = transport.get("response_assertions", [])
    if not isinstance(assertions, list):
        _fail(base["name"], "response_assertions requires a list")
    for assertion in assertions:
        _keys(
            assertion,
            {"path", "comparison", "value", "when_present"},
            {"path", "comparison", "value"},
            base["name"],
        )
        selected, required, _ = _rest_field(
            document, original, _path(assertion["path"], base["name"]), base["name"]
        )
        if "when_present" in assertion and (
            assertion["when_present"] is not True or required or assertion["comparison"] != "length_lt"
        ):
            _fail(base["name"], "when_present requires true on a pinned optional array length assertion")
        if assertion["comparison"] == "length_lt":
            selected = _resolved(document, selected, base["name"])
            if (
                selected.get("type") != "array"
                or type(assertion["value"]) is not int
                or assertion["value"] < 1
            ):
                _fail(base["name"], "length_lt requires an array and a positive integer bound")
        elif assertion["comparison"] == "equal":
            selected = _openapi_type(document, selected, base["name"])
            if selected["kind"] != "scalar":
                _fail(base["name"], "equal response assertion requires a scalar field")
            _binding({"literal": assertion["value"]}, base, selected["type"], False, base["name"])
        else:
            _fail(base["name"], "unsupported response assertion comparison")
    base["transport"] = {
        "kind": "rest",
        "operation_id": transport["operation_id"],
        "path": path,
        "method": "GET",
        **({"response_status": status} if status != "200" else {}),
        **({"authentication": transport["authentication"]} if "authentication" in transport else {}),
        "product": transport.get("product", "api.github.com"),
        **normalized,
        "result_path": result_path,
        "result_shape": shape,
        "pagination": copy.deepcopy(pagination),
        **({"item_length": transport["item_length"]} if "item_length" in transport else {}),
        **({"accept": accept} if accept is not None else {}),
        **(
            {"empty_response_statuses": copy.deepcopy(transport["empty_response_statuses"])}
            if "empty_response_statuses" in transport
            else {}
        ),
        **({"response_assertions": copy.deepcopy(assertions)} if assertions else {}),
    }
    base["source"] = {
        "response_sha256": closure_hash(document, original),
        "result_nullable": node.get("nullable", False),
        "item_nullable": _resolved(document, row, base["name"]).get("nullable", False),
        "response_schema": reference_closure(document, original),
        **(
            {"response_projection": projection}
            if "response_variant" in transport or "response_media_type" in transport
            else {}
        ),
    }
    return _complete(base)


def _merge_schemas(schemas: list[dict], location: str) -> dict:
    """Union null/presence domains only; differing concrete types never coerce."""
    first = schemas[0]
    if any(_sql_type(value) != _sql_type(first) for value in schemas[1:]):
        _fail(location, "scope/response variants must have identical selected concrete types")
    if any(value.get("encoding") != first.get("encoding") for value in schemas[1:]):
        _fail(location, "scope/response variants must have identical selected wire encodings")
    result = copy.deepcopy(first)
    result["nullable"] = any(value["nullable"] for value in schemas)
    if first["kind"] == "list":
        result["item"] = _merge_schemas([value["item"] for value in schemas], location + "[]")
    elif first["kind"] == "map":
        result["value"] = _merge_schemas([value["value"] for value in schemas], location + "{}")
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


def _validate_graphql_selected_field(field, location):
    """Scalar leaves may use upstream defaults; collections still need explicit routes."""
    if not field.args:
        return
    value = field.type.of_type if isinstance(field.type, GraphQLNonNull) else field.type
    if (is_scalar_type(value) or is_enum_type(value)) and all(
        not isinstance(argument.type, GraphQLNonNull) or argument.default_value is not Undefined
        for argument in field.args.values()
    ):
        return
    _fail(location, "selected fields with arguments require a separate entity")


def _graphql_type(
    value: Any,
    location: str,
    selection: dict | None = None,
    trail: tuple[str, ...] = (),
    *,
    schema_model=None,
) -> dict:
    nullable = not isinstance(value, GraphQLNonNull)
    value = value.of_type if not nullable else value
    if isinstance(value, GraphQLList):
        return {
            "kind": "list",
            "item": _graphql_type(
                value.of_type, location + "[]", selection, trail, schema_model=schema_model
            ),
            "nullable": nullable,
        }
    if is_union_type(value) or is_interface_type(value):
        if schema_model is None or not selection or selection.get("__typename") is not True:
            _fail(location, "abstract GraphQL columns require __typename and explicit concrete selections")
        possibilities = schema_model.get_possible_types(value)
        expected = {"__typename", *("... on " + kind.name for kind in possibilities)}
        if set(selection) != expected:
            _fail(location, "abstract GraphQL selection must retain every concrete type")
        branches = {
            kind.name: _graphql_type(
                GraphQLNonNull(kind),
                location + "." + kind.name,
                selection["... on " + kind.name],
                trail,
                schema_model=schema_model,
            )
            for kind in possibilities
        }
        return _variant_schema(branches, nullable, discriminator="__typename")
    if is_object_type(value):
        if value.name in trail:
            _fail(location, f"selected recursive GraphQL object {value.name}; narrow the selection")
        if not selection:
            _fail(location, "GraphQL object columns require an explicit field selection")
        fields = []
        for name, child in selection.items():
            if name == "__typename" and child is True:
                fields.append(
                    {
                        "name": name,
                        "required": True,
                        "nullable": False,
                        "schema": {"kind": "scalar", "type": "VARCHAR", "nullable": False},
                    }
                )
                continue
            if name not in value.fields:
                _fail(location, f"unknown GraphQL field {name!r}")
            field = value.fields[name]
            _validate_graphql_selected_field(field, location + "." + name)
            descriptor = _graphql_type(
                field.type,
                location + "." + name,
                None if child is True else child,
                (*trail, value.name),
                schema_model=schema_model,
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
        return {
            "kind": "scalar",
            "type": GRAPHQL_SCALARS[value.name],
            "nullable": nullable,
            **({"encoding": "decimal_string"} if value.name == "BigInt" else {}),
        }
    _fail(location, f"unsupported selected GraphQL type {value}")


def graphql_selection_paths(schema, parent, path, *, on_types=None, location="GraphQL selection"):
    """Expand common union paths into legal fragments while preserving response paths.

    Return the leaf type, query path (including fragments), ancestor nullability
    and guaranteed presence. This is also used by pinned-schema extraction.
    """

    def walk(value, remaining, query_path, nullable=False, required=True):
        if not remaining:
            return [(value, query_path, nullable, required)]
        raw = value.of_type if isinstance(value, GraphQLNonNull) else value
        if isinstance(raw, GraphQLList):
            _fail(location, "selected paths cannot traverse lists; select the list column instead")
        kind = get_named_type(value)
        name, *tail = remaining
        if (
            name == "__typename"
            and not tail
            and (is_object_type(kind) or is_interface_type(kind) or is_union_type(kind))
        ):
            return [(GraphQLNonNull(GraphQLString), [*query_path, name], nullable, required)]
        restricted = on_types is not None and not tail
        if is_union_type(kind) or restricted:
            if not (is_union_type(kind) or is_interface_type(kind)):
                _fail(location, "on_types requires an interface or union parent")
            possibilities = {member.name: member for member in schema.get_possible_types(kind)}
            selected = on_types if restricted else list(possibilities)
            if (
                not isinstance(selected, list)
                or not selected
                or len(set(selected)) != len(selected)
                or set(selected) - possibilities.keys()
            ):
                _fail(location, "on_types must select distinct possible concrete types")
            result = []
            for member in selected:
                concrete = possibilities[member]
                if name not in concrete.fields:
                    _fail(location, f"union path field {name!r} is absent on {member}")
                field = concrete.fields[name]
                _validate_graphql_selected_field(field, location + "." + name)
                result.extend(
                    walk(
                        field.type,
                        tail,
                        [*query_path, "... on " + member, name],
                        nullable or bool(tail) and not isinstance(field.type, GraphQLNonNull),
                        required and set(selected) == possibilities.keys(),
                    )
                )
            return result
        if not (is_object_type(kind) or is_interface_type(kind)) or name not in kind.fields:
            _fail(location, f"unknown GraphQL selected field {name!r}")
        field = kind.fields[name]
        _validate_graphql_selected_field(field, location + "." + name)
        return walk(
            field.type,
            tail,
            [*query_path, name],
            nullable or bool(tail) and not isinstance(field.type, GraphQLNonNull),
            required,
        )

    return walk(parent, path, [])


def _selection_merge(tree: dict, path: list[str], tail: dict | None = None) -> None:
    for name in path:
        tree = tree.setdefault(name, {})
    if tail:
        for name, value in tail.items():
            _selection_merge(tree, [name], None if value is True else value)


def _selection_sql(tree: dict, aliases: dict | None = None, concrete: str | None = None) -> str:
    # GraphQL compares return types even across mutually exclusive fragments.
    # Type-qualified response names keep Issue.state and PullRequest.state legal
    # while the decoder restores their schema-derived public field names.
    fields = []
    for name, child in tree.items():
        fragment = name.startswith("... on ")
        wire = name
        if aliases is not None and concrete and not fragment and name != "__typename":
            wire = "_vgi_" + concrete + "_" + name
            aliases[wire] = name
            wire += ": " + name
        rendered = _selection_sql(child, aliases, name[7:] if fragment else None) if child else ""
        fields.append(wire + (" { " + rendered + " }" if child else ""))
    return " ".join(fields)


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
    if descriptor.get("encoding") == "decimal_string":
        result["encoding"] = "decimal_string"
        if (
            "literal" in binding
            and binding["literal"] is not None
            and not (-(2**63) <= binding["literal"] < 2**63)
        ):
            _fail(location, "GraphQL BigInt literal exceeds signed 64-bit range")
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
        {
            "kind",
            "field_path",
            "field_arguments",
            "field_types",
            "result_path",
            "pagination",
            "nullable_path_policy",
        },
        {"kind", "field_path", "field_arguments", "result_path", "pagination"},
        base["name"],
    )
    field_path = _path(transport["field_path"], base["name"])
    result_path = _path(transport["result_path"], base["name"], empty=True)
    pagination = transport["pagination"]
    _keys(pagination, {"kind", "page_info_path"}, {"kind"}, base["name"])
    singleton = pagination["kind"] == "none"
    if pagination["kind"] not in {"cursor", "none"}:
        _fail(base["name"], "GraphQL supports cursor connections or singleton objects")
    if singleton and (result_path or "page_info_path" in pagination):
        _fail(base["name"], "GraphQL singleton paths must select the object directly")
    page_info_path = [] if singleton else _path(pagination.get("page_info_path"), base["name"])
    current = schema.query_type
    variables, declarations, fields = {}, {}, []
    seen_field_arguments = set()
    nullable_paths = []
    field_types = transport.get("field_types", {})
    if not isinstance(field_types, dict) or set(field_types) - set(field_path):
        _fail(base["name"], "field_types must narrow fields in field_path")
    for field_index, name in enumerate(field_path):
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
        value = field.type
        if not isinstance(value, GraphQLNonNull):
            nullable_paths.append(field_path[: field_index + 1])
        current = get_named_type(value)
        if name in field_types:
            if not (is_interface_type(current) or is_union_type(current)):
                _fail(base["name"], "field_types requires an interface or union return type")
            target = schema.get_type(field_types[name])
            if target not in schema.get_possible_types(current):
                _fail(base["name"], "field_types must name a possible implementation")
            current = target
            value = GraphQLNonNull(target) if isinstance(value, GraphQLNonNull) else target
            fields.append("... on " + target.name)
    if seen_field_arguments != transport["field_arguments"].keys():
        _fail(base["name"], "field_arguments includes a field outside field_path")
    if "nullable_path_policy" in transport and (
        transport["nullable_path_policy"] != "error" or not nullable_paths
    ):
        _fail(base["name"], "nullable_path_policy requires error on a nullable GraphQL traversal")
    connection = current
    for name in result_path:
        if not is_object_type(current) or name not in current.fields:
            _fail(base["name"], f"unknown GraphQL result field {name!r}")
        value = current.fields[name].type
        current = get_named_type(value)
    raw = value.of_type if isinstance(value, GraphQLNonNull) else value
    if singleton:
        if not (is_object_type(raw) or is_interface_type(raw) or is_union_type(raw)):
            _fail(base["name"], "GraphQL singleton paths must return an object, interface or union")
    elif not isinstance(raw, GraphQLList):
        _fail(base["name"], "selected GraphQL result must be a list")
    selection = {}
    for column in entity.get("columns", []):
        if "source_argument" in column or "source_ordinal" in column:
            base["columns"].append(_column(base, column))
            continue
        path = _path(column.get("path"), base["name"], empty=bool(column.get("selection")))
        leaves = graphql_selection_paths(
            schema,
            GraphQLNonNull(current),
            path,
            on_types=column.get("on_types"),
            location=base["name"],
        )
        descriptors = []
        required = True
        for leaf, query_path, parent_nullable, present in leaves:
            descriptor = _graphql_type(
                leaf,
                base["name"] + "." + column["name"],
                column.get("selection"),
                schema_model=schema,
            )
            descriptor["nullable"] |= parent_nullable or not present
            descriptors.append(descriptor)
            required &= present
            _selection_merge(selection, result_path + query_path, column.get("selection"))
        descriptor = _merge_schemas(descriptors, base["name"] + "." + column["name"])
        compiled_column = _column(base, column, descriptor, required=required)
        if "on_types" in column:
            parent_types = set()
            parents = graphql_selection_paths(
                schema, GraphQLNonNull(current), path[:-1], location=base["name"]
            )
            for parent, parent_path, _, _ in parents:
                parent_type = get_named_type(parent)
                parent_types.update(kind.name for kind in schema.get_possible_types(parent_type))
                _selection_merge(selection, result_path + parent_path + ["__typename"])
            compiled_column["on_types"] = copy.deepcopy(column["on_types"])
            compiled_column["parent_types"] = sorted(parent_types)
        base["columns"].append(compiled_column)
    if not singleton:
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
    elif "cursor" in variables:
        _fail(base["name"], "GraphQL singleton lookups cannot bind a cursor")
    response_aliases = {}
    body = _selection_sql(selection, response_aliases)
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
        "pagination": {"kind": "none"}
        if singleton
        else {
            "kind": "cursor",
            "page_info_path": field_path + page_info_path,
            "cursor_variable": "cursor",
        },
        "nullable_paths": nullable_paths,
        **({"nullable_path_policy": "error"} if "nullable_path_policy" in transport else {}),
        **({"response_aliases": response_aliases} if response_aliases else {}),
    }
    base["source"] = {
        "field_path": field_path,
        **({"field_types": copy.deepcopy(field_types)} if field_types else {}),
        "result_type": current.name,
        "result_nullable": not isinstance(value, GraphQLNonNull),
        "item_nullable": False if singleton else not isinstance(raw.of_type, GraphQLNonNull),
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
        from .routes import compile_routes

        return compile_routes(contract, overlay)
    if set(overlay) & {"scopes", "relationships", "shared_dimensions"}:
        _fail("overlay", "scopes and relationship metadata require public function declarations")
    return contract
