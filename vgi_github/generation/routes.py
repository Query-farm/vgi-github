"""Compose alternative retrieval plans into one public business entity.

Each plan is compiled through the ordinary traversal and cohort contracts. Routes
share an exact output schema and grain; they are never concatenated or unioned.
"""

from copy import deepcopy

from .cohorts import compile_cohorts
from .graph import compile_functions
from .schema import _complete, _identifier, _keys, _merge_schemas, _sql_type


def _route_schema(schemas, path, nullable_fields, used):
    """Preserve distinct fields when a reviewed route cannot supply them.

    Each source still validates its own full selected schema. Only the public
    shape gains nullable fields; concrete types are never inferred or coerced.
    """
    kinds = {value["kind"] for value in schemas}
    if kinds == {"list"}:
        return {
            **deepcopy(schemas[0]),
            "nullable": any(value["nullable"] for value in schemas),
            "item": _route_schema([value["item"] for value in schemas], path + "[]", nullable_fields, used),
        }
    if kinds != {"struct"}:
        return _merge_schemas(schemas, path)
    if any(value.get("variant") != schemas[0].get("variant") for value in schemas):
        raise ValueError("Route variants must preserve identical concrete alternatives and discriminators")
    definitions = [{field["name"]: field for field in value["fields"]} for value in schemas]
    fields = []
    for name in dict.fromkeys(name for value in definitions for name in value):
        field_path = path + "." + name
        candidates = [value[name] for value in definitions if name in value]
        absent = len(candidates) != len(schemas)
        if absent:
            if field_path not in nullable_fields:
                raise ValueError(
                    f"Route field {field_path} requires explicit nullable_struct_fields approval"
                )
            used.add(field_path)
        schema = _route_schema([field["schema"] for field in candidates], field_path, nullable_fields, used)
        schema["nullable"] |= absent
        fields.append(
            {
                **deepcopy(candidates[0]),
                "schema": schema,
                "nullable": schema["nullable"],
                "required": not absent and all(field["required"] for field in candidates),
            }
        )
    return {**deepcopy(schemas[0]), "fields": fields, "nullable": any(value["nullable"] for value in schemas)}


def compile_routes(contract: dict, overlay: dict) -> dict:
    expanded = deepcopy(overlay)
    expanded["functions"] = []
    routed = {}
    roots = {}
    options = {}
    for definition in overlay["functions"]:
        if "routes" not in definition:
            expanded["functions"].append(deepcopy(definition))
            continue
        _keys(
            definition,
            {
                "name",
                "description",
                "grain",
                "semantics",
                "routes",
                "filters",
                "cohort_root",
                "nullable_struct_fields",
                "nullable_route_fields",
            },
            {"name", "description", "grain", "semantics", "routes"},
            "routed function",
        )
        if not isinstance(definition["routes"], list) or not definition["routes"]:
            raise ValueError("A routed entity requires at least one retrieval plan")
        names = []
        for index, route in enumerate(definition["routes"]):
            _keys(
                route,
                {
                    "name",
                    "arguments",
                    "columns",
                    "traversal",
                    "select",
                    "select_values",
                    "default",
                    "deduplicate",
                    "population",
                },
                {"name", "arguments", "columns", "traversal"},
                definition["name"],
            )
            if "default" in route and (
                route["default"] is not True
                or index != len(definition["routes"]) - 1
                or "select" in route
                or "select_values" in route
            ):
                raise ValueError("A default route must be the final route, explicitly true, without select")
            name = definition["name"] + "__" + _identifier(route["name"], "route")
            names.append(name)
            options[name] = {
                key: deepcopy(route[key])
                for key in ("select", "select_values", "default", "deduplicate", "population")
                if key in route
            }
            if definition.get("cohort_root") == route["name"]:
                roots[definition["name"]] = name
            expanded["functions"].append(
                {
                    **{key: deepcopy(definition[key]) for key in ("description", "grain", "semantics")},
                    **{key: deepcopy(route[key]) for key in ("arguments", "columns", "traversal")},
                    "name": name,
                }
            )
        if len(set(names)) != len(names):
            raise ValueError("Route names must be unique")
        if "cohort_root" in definition and definition["name"] not in roots:
            raise ValueError("cohort_root must name one of the entity's routes")
        routed[definition["name"]] = names
    compiled = compile_cohorts(compile_functions(contract, expanded), overlay.get("cohorts", {}), roots)
    functions = {value["name"]: value for value in compiled["functions"]}
    functions.update({name: functions[route] for name, route in roots.items()})
    public = []
    for definition in overlay["functions"]:
        name = definition["name"]
        if name not in routed:
            public.append(functions[name])
            continue
        routes = [functions[key] for key in routed[name]]
        for route in routes:
            option = options[route["name"]]
            cohort = route.get("cohort")
            selection = option.pop("select", None)
            if option.get("default"):
                if cohort or any(not argument["nullable"] for argument in route["arguments"]):
                    raise ValueError("A default route must be callable without required selection arguments")
                selection = []
            elif selection is None and cohort:
                selection = [*cohort["alternatives"], cohort["parameter"]]
            if (
                not isinstance(selection, list)
                or not selection
                and not option.get("default")
                or len(set(selection)) != len(selection)
                or any(key not in {arg["name"] for arg in route["arguments"]} for key in selection)
            ):
                raise ValueError(
                    f"{route['name']}: each route must declare valid selection parameters or a cohort root"
                )
            if "select_values" in option:
                conditions = option["select_values"]
                arguments = {argument["name"]: argument for argument in route["arguments"]}
                if not isinstance(conditions, dict) or not conditions:
                    raise ValueError("select_values requires a nonempty map of selection enum values")
                for parameter, values in conditions.items():
                    argument = arguments.get(parameter, {})
                    declared = argument.get("enum", [])
                    if (
                        parameter not in selection
                        or not declared
                        or not isinstance(values, list)
                        or not values
                        or any(
                            not any(type(value) is type(item) and value == item for item in declared)
                            for value in values
                        )
                        or len({(type(value).__name__, repr(value)) for value in values}) != len(values)
                    ):
                        raise ValueError("select_values must contain distinct declared selection enum values")
            if "deduplicate" in option and not isinstance(option["deduplicate"], bool):
                raise ValueError("Route deduplicate must be boolean")
            if "population" in option and (
                not isinstance(option["population"], str) or not option["population"].strip()
            ):
                raise ValueError("Route population must be a nonempty description")
            route.update(selection=selection, **option)
        fields = [{column["name"]: column for column in route["columns"]} for route in routes]
        nullable_route_fields = definition.get("nullable_route_fields", [])
        if (
            not isinstance(nullable_route_fields, list)
            or any(not isinstance(field, str) or not field for field in nullable_route_fields)
            or len(nullable_route_fields) != len(set(nullable_route_fields))
        ):
            raise ValueError("nullable_route_fields must name distinct public fields")
        all_fields = dict.fromkeys(field for route_fields in fields for field in route_fields)
        missing_fields = {
            field for field in all_fields if any(field not in route_fields for route_fields in fields)
        }
        if missing_fields != set(nullable_route_fields):
            raise ValueError(
                "Routes must expose the same named public columns except explicit nullable_route_fields"
            )
        columns = []
        nullable_fields = definition.get("nullable_struct_fields", [])
        if (
            not isinstance(nullable_fields, list)
            or any(not isinstance(field, str) or not field for field in nullable_fields)
            or len(nullable_fields) != len(set(nullable_fields))
        ):
            raise ValueError("nullable_struct_fields must name distinct nested field paths")
        used = set()
        for field in all_fields:
            supplied = [value[field] for value in fields if field in value]
            first = supplied[0]
            schema = _route_schema([value["schema"] for value in supplied], field, set(nullable_fields), used)
            schema["nullable"] |= field in missing_fields
            columns.append(
                {
                    **{
                        key: deepcopy(value)
                        for key, value in first.items()
                        if key not in {"source_stage", "source_column"}
                    },
                    "schema": schema,
                    "type": _sql_type(schema),
                    "nullable": schema["nullable"],
                    "required": field not in missing_fields and all(value["required"] for value in supplied),
                    **(
                        {"allow_empty_identity": True}
                        if any(value.get("allow_empty_identity") for value in supplied)
                        else {}
                    ),
                }
            )
        if set(nullable_fields) != used:
            raise ValueError("nullable_struct_fields must name fields absent from at least one route")
        arguments = {}
        for route in routes:
            for argument in route["arguments"]:
                value = {key: deepcopy(item) for key, item in argument.items() if key != "position"}
                value.update(nullable=True, default=None)
                prior = arguments.setdefault(value["name"], value)
                if {key: item for key, item in prior.items() if key not in {"description", "example"}} != {
                    key: item for key, item in value.items() if key not in {"description", "example"}
                }:
                    raise ValueError("Route parameters must have identical definitions")
        filters = deepcopy(definition.get("filters", []))
        for selection in filters:
            _keys(selection, {"function", "column", "key"}, {"function", "column", "key"}, name)
            root = functions.get(selection["function"])
            if root is None or "cohort" not in root or len(root["traversal"]["stages"]) != 1:
                raise ValueError("Selection filters require a single-stage cohort root")
            source = fields[0].get(selection["column"])
            target = next((column for column in root["columns"] if column["name"] == selection["key"]), None)
            if (
                not source
                or not target
                or source["type"] != target["type"]
                or root["grain"] != [selection["key"]]
            ):
                raise ValueError("Selection filters must match the complete typed root identity")
            for argument in root["arguments"]:
                value = {key: deepcopy(item) for key, item in argument.items() if key != "position"}
                value.update(nullable=True, default=None)
                prior = arguments.setdefault(value["name"], value)
                if {key: item for key, item in prior.items() if key not in {"description", "example"}} != {
                    key: item for key, item in value.items() if key not in {"description", "example"}
                }:
                    raise ValueError("Selection filter parameters must have identical definitions")
            selection["root"] = deepcopy(root)
        public.append(
            _complete(
                {
                    "name": name,
                    "description": definition["description"],
                    "grain": deepcopy(definition["grain"]),
                    "semantics": deepcopy(definition["semantics"]),
                    "columns": columns,
                    "arguments": [
                        dict(value, position=index) for index, value in enumerate(arguments.values())
                    ],
                    "routes": routes,
                    "filters": filters,
                }
            )
        )
    compiled["functions"] = public
    return compiled
