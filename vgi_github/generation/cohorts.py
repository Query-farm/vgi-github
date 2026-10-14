"""Compile typed cohort alternatives for a declared traversal's root argument.

The provider still emits a page at a time. A cohort changes the root population;
it does not join facts, infer membership, or cache results across invocations.
"""

from copy import deepcopy

from .schema import _identifier, _keys


def compile_cohorts(contract: dict, definitions: dict) -> dict:
    if not isinstance(definitions, dict):
        raise ValueError("cohorts must be a named root configuration object")
    functions = {function["name"]: function for function in contract["functions"]}
    assigned = set()
    for root, definition in definitions.items():
        _keys(definition, {"parameter", "argument", "field", "comment", "example", "resource"},
              {"parameter", "argument", "field", "comment", "example"}, f"cohorts.{root}")
        parent = functions.get(root)
        if parent is None or len(parent["traversal"]["stages"]) != 1:
            raise ValueError(f"Cohort {root} must name a single-stage public root")
        parameter = _identifier(definition["parameter"], f"cohorts.{root}")
        field = _identifier(definition["field"], f"cohorts.{root}")
        argument = definition["argument"]
        if definition.get("resource", "login") not in {"repository", "login"}:
            raise ValueError(f"Cohort {root} resource must be repository or login")
        source_arg = next((arg for arg in parent["arguments"] if arg["name"] == argument), None)
        if source_arg is None or source_arg["type"] != "VARCHAR":
            raise ValueError(f"Cohort {root} requires a declared VARCHAR resource argument")
        example = definition["example"]
        if not isinstance(example, list) or not example or any(
            not isinstance(row, dict) or set(row) != {field}
            or not isinstance(row[field], str) or not row[field].strip() for row in example
        ):
            raise ValueError(f"Cohort {root} example must contain nonempty {field} rows")
        if not isinstance(definition["comment"], str) or not definition["comment"].strip():
            raise ValueError(f"Cohort {root} requires a comment")
        root_stage = parent["traversal"]["stages"][0]
        alternatives = list(contract["scopes"].get(root_stage.get("scope"), {}).get(
            "exclusive_parameters", [argument]))
        if argument not in alternatives:
            raise ValueError(f"Cohort {root} argument must be a root scope alternative")
        for function in contract["functions"]:
            if function["traversal"]["stages"][0] != root_stage:
                continue
            if function["name"] in assigned:
                raise ValueError(f"Function {function['name']} has overlapping cohorts")
            assigned.add(function["name"])
            if any(arg["name"] == parameter for arg in function["arguments"]):
                raise ValueError(f"Cohort parameter {parameter} collides with a public argument")
            scalar = next(arg for arg in function["arguments"] if arg["name"] == argument)
            scalar.update(nullable=True, default=None)
            function["cohort"] = {**deepcopy(definition), "alternatives": alternatives}
            function["arguments"].append({
                "name": parameter, "position": len(function["arguments"]),
                "type": f'STRUCT("{field}" VARCHAR)[]', "nullable": True, "default": None,
                "description": definition["comment"], "example": deepcopy(example),
                "schema": {"kind": "list", "item": {"kind": "struct", "nullable": False,
                    "fields": [{"name": field, "type": "VARCHAR", "nullable": False,
                                "required": True, "schema": {"kind": "scalar", "type": "VARCHAR"}}]}},
            })
    return contract
