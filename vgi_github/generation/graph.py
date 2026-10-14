"""Validate and compile reusable scope decisions and connected producer traversals."""

from __future__ import annotations

import copy

from .schema import _binding, _complete, _entity_base, _fail, _identifier, _keys, _merge_schemas


def _scope_constraints(scope: dict, public: dict, location: str) -> tuple[set[str], dict]:
    _keys(
        scope,
        {"select", "exclusive_parameters", "requires_parameters", "comment"},
        {"select"},
        location,
    )
    exclusive = scope.get("exclusive_parameters", [])
    if (
        not isinstance(exclusive, list)
        or any(not isinstance(value, str) or value not in public for value in exclusive)
        or len(exclusive) != len(set(exclusive))
    ):
        _fail(location, "scope exclusivity must name distinct public parameters")
    dependencies = scope.get("requires_parameters", {})
    if not isinstance(dependencies, dict):
        _fail(location, "scope dependencies must be a named parameter object")
    for key, values in dependencies.items():
        if (
            key not in public
            or not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or value not in public or value == key for value in values)
            or len(values) != len(set(values))
        ):
            _fail(location, "scope dependency constraints require declared distinct parameters")
    return set(exclusive), dependencies


def _presence(present: set[str], absent: set[str], exclusive: set[str], dependencies: dict, location: str):
    """Propagate exactly-one and implication constraints without enumerating input combinations."""
    present, absent = set(present), set(absent)
    while True:
        previous = present.copy(), absent.copy()
        if present & absent:
            _fail(location, "scope branch has contradictory parameter presence constraints")
        if exclusive:
            selected = present & exclusive
            remaining = exclusive - absent
            if len(selected) > 1 or not remaining:
                _fail(location, "scope branch contradicts its exactly-one parameter constraint")
            if selected:
                absent.update(exclusive - selected)
            elif len(remaining) == 1:
                present.update(remaining)
        for parameter, required in dependencies.items():
            if parameter in present:
                present.update(required)
            if absent.intersection(required):
                absent.add(parameter)
        if previous == (present, absent):
            return present, absent


def compile_functions(contract: dict, overlay: dict) -> dict:
    sources = {entity["name"]: entity for entity in contract["entities"]}
    scopes = overlay.get("scopes", {})
    if not isinstance(scopes, dict):
        _fail("scopes", "expected a named scope object")
    functions = []
    used_scopes = set()
    for definition in overlay["functions"]:
        _keys(
            definition,
            {"name", "description", "arguments", "columns", "grain", "traversal", "semantics"},
            {"name", "arguments", "columns", "grain", "traversal", "semantics"},
            "function",
        )
        base = _entity_base(definition)
        location = base["name"]
        public = {argument["name"]: argument for argument in base["arguments"]}
        required_parameters = {name for name, argument in public.items() if not argument["nullable"]}
        traversal = definition["traversal"]
        _keys(traversal, {"stages", "output_stage"}, {"stages", "output_stage"}, location)
        stages = {}

        def leaf(node, nonnull, location=location, public=public, base=base, stages=stages):
            _keys(node, {"entity", "arguments"}, {"entity", "arguments"}, location)
            if node["entity"] not in sources:
                _fail(location, f"unknown source entity {node['entity']!r}")
            source = sources[node["entity"]]
            expected = {argument["name"]: argument for argument in source["arguments"]}
            if not isinstance(node["arguments"], dict):
                _fail(location, "source argument mappings must be an object")
            if set(node["arguments"]) != set(expected):
                _fail(location, f"source {source['name']} requires exactly its declared argument mappings")
            for name, binding in node["arguments"].items():
                target = expected[name]
                if not isinstance(binding, dict):
                    _fail(location, "source argument mappings must be objects")
                if set(binding) == {"parameter"}:
                    parameter = public.get(binding["parameter"])
                    if parameter is None:
                        _fail(location, "scope refers to an undeclared public parameter")
                    mapped = {
                        "arguments": [
                            {
                                **parameter,
                                "nullable": parameter["nullable"] and parameter["name"] not in nonnull,
                            }
                        ]
                    }
                    _binding(
                        {"argument": parameter["name"]}, mapped, target["type"], target["nullable"], location
                    )
                elif set(binding) == {"stage", "column"}:
                    stage = stages.get(binding["stage"])
                    if stage is None or binding["column"] not in stage:
                        _fail(location, "a traversal binding must reference an earlier stage column")
                    column = stage[binding["column"]]
                    nullable = column["nullable"] or not column["required"]
                    if column["type"] != target["type"] or nullable and not target["nullable"]:
                        _fail(location, "stage arguments must preserve exact types and non-null requirements")
                elif set(binding) == {"literal"}:
                    _binding(binding, base, target["type"], target["nullable"], location)
                else:
                    _fail(location, "source mappings require parameter, stage/column, or literal")
            if stages and not any(
                value.get("stage") == list(stages)[-1] for value in node["arguments"].values()
            ):
                _fail(location, "each child source must consume its immediate parent stage")
            return source

        def decision(
            node, nonnull, absent, exclusive, dependencies, location=location, public=public, leaf=leaf
        ):
            if not isinstance(node, dict):
                _fail(location, "scope decision must be an object")
            nonnull, absent = _presence(nonnull, absent, exclusive, dependencies, location)
            if "entity" in node:
                return [leaf(node, nonnull)]
            if "parameter" in node:
                _keys(
                    node,
                    {"parameter", "if_present", "if_absent"},
                    {"parameter", "if_present", "if_absent"},
                    location,
                )
                parameter = node["parameter"]
                if not isinstance(parameter, str) or parameter not in public:
                    _fail(location, "scope selector refers to an undeclared parameter")
                if parameter in nonnull or parameter in absent:
                    _fail(location, "scope selector repeats a parameter already fixed by branch constraints")
                return decision(
                    node["if_present"], nonnull | {parameter}, absent, exclusive, dependencies
                ) + decision(node["if_absent"], nonnull, absent | {parameter}, exclusive, dependencies)
            _keys(node, {"resolve", "field", "cases"}, {"resolve", "field", "cases"}, location)
            resolver = leaf(node["resolve"], nonnull)
            columns = {column["name"]: column for column in resolver["columns"]}
            field = columns.get(node["field"])
            if not field or field["type"] != "VARCHAR" or field["nullable"] or not field["required"]:
                _fail(location, "scope resolver discriminator must be a required non-null VARCHAR")
            if resolver["transport"].get("result_shape") != "object":
                _fail(location, "scope resolver must declare a singleton object response")
            if not isinstance(node["cases"], dict) or not node["cases"]:
                _fail(location, "scope resolver requires explicit nonempty cases")
            return [
                source
                for child in node["cases"].values()
                for source in decision(child, nonnull, absent, exclusive, dependencies)
            ]

        for stage in traversal["stages"]:
            _keys(stage, {"name", "entity", "arguments", "scope"}, {"name"}, location)
            name = _identifier(stage["name"], location)
            if name in stages:
                _fail(location, "traversal stage names must be unique")
            if "scope" in stage:
                if set(stage) != {"name", "scope"} or stage["scope"] not in scopes:
                    _fail(location, "scope stages require a declared scope and no inline entity")
                scope_name = stage["scope"]
                used_scopes.add(scope_name)
                scope = scopes[scope_name]
                exclusive, dependencies = _scope_constraints(scope, public, location)
                variants = decision(scope["select"], required_parameters, set(), exclusive, dependencies)
            else:
                variants = [
                    leaf({key: value for key, value in stage.items() if key != "name"}, required_parameters)
                ]
            fields = [{column["name"]: column for column in source["columns"]} for source in variants]
            if any(set(value) != set(fields[0]) for value in fields[1:]):
                _fail(location, "scope alternatives must expose the same named entity columns")
            columns = {}
            for field, first in fields[0].items():
                schema = _merge_schemas([value[field]["schema"] for value in fields], location + "." + field)
                columns[field] = {
                    **copy.deepcopy(first),
                    "schema": schema,
                    "nullable": schema["nullable"],
                    "required": all(value[field]["required"] for value in fields),
                }
            stages[name] = columns
        if not stages or traversal["output_stage"] != list(stages)[-1]:
            _fail(location, "output_stage must be the final nonempty traversal stage")
        for column in definition["columns"]:
            _keys(
                column,
                {"name", "source_stage", "source_column", "description"},
                {"name", "source_stage", "source_column"},
                location,
            )
            _identifier(column["name"], location)
            selected = stages.get(column["source_stage"], {}).get(column["source_column"])
            if selected is None:
                _fail(location, "public column references an unknown stage field")
            base["columns"].append(
                {
                    key: copy.deepcopy(value)
                    for key, value in selected.items()
                    if key not in {"path", "source_argument", "name", "description"}
                }
                | column
            )
        base["traversal"] = copy.deepcopy(traversal)
        functions.append(_complete(base))
    if len({function["name"].lower() for function in functions}) != len(functions):
        _fail("functions", "public function names must be unique")
    if used_scopes != scopes.keys():
        _fail("scopes", "every declared scope must be used by a public function")
    return {
        **contract,
        "scopes": copy.deepcopy(scopes),
        "functions": functions,
        "relationships": copy.deepcopy(overlay.get("relationships", [])),
        "shared_dimensions": copy.deepcopy(overlay.get("shared_dimensions", {})),
    }
