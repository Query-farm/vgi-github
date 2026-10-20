"""Emit connected entities and approved calculations; saved reports are optional."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy

from vgi_github.generation.coverage import audit_coverage
from vgi_github.generation.examples import analysis_documentation, research_artifacts, research_documentation
from vgi_github.generation.native_overlay import apply_native_overlay
from vgi_github.generation.schema import _binding

ENGINE = "94abd4ed366569345faf5dc1e254ae6ca7311a76"
NAMESPACE = uuid.UUID("9952d457-873c-5e13-965e-07fbdc1cfe2b")
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*\Z")


def json_text(value):
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def quote(value):
    return "'" + value.replace("'", "''") + "'"


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid generated semantic identifier: {value!r}")
    return value


def _text_category(field, columns, detail_fields):
    if set(field) != {"name", "kind", "source", "rules", "otherwise", "comment"}:
        raise ValueError("Text categories require a reviewed source, ordered rules and explicit otherwise")
    source = columns.get(field["source"]) if isinstance(field["source"], str) else None
    if not source or source["type"] != "VARCHAR" or field["source"] not in detail_fields:
        raise ValueError("Text categories require a declared VARCHAR source exposed as a detail field")
    if (
        not isinstance(field["otherwise"], str)
        or not field["otherwise"].strip()
        or len(field["otherwise"]) > 64
    ):
        raise ValueError("Text categories require a nonempty bounded otherwise category")
    rules = field["rules"]
    if not isinstance(rules, list) or not 1 <= len(rules) <= 32:
        raise ValueError("Text categories require between 1 and 32 ordered rules")
    ids = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"id", "match", "value", "category"}:
            raise ValueError("Text category rules require id, match, literal value and category")
        rule_id = identifier(rule["id"])
        if rule_id in ids:
            raise ValueError("Text category rule IDs must be unique")
        ids.add(rule_id)
        if not isinstance(rule["match"], str) or rule["match"] not in {"exact", "prefix", "contains"}:
            raise ValueError("Text categories only support exact, prefix and contains matches")
        if not isinstance(rule["value"], str) or not rule["value"].strip() or len(rule["value"]) > 256:
            raise ValueError("Text category match values must be nonempty bounded strings")
        if (
            not isinstance(rule["category"], str)
            or not rule["category"].strip()
            or len(rule["category"]) > 64
        ):
            raise ValueError("Text category labels must be nonempty bounded strings")


def _text_category_sql(dataset, field):
    source = f"LOWER({dataset}.{field['source']})"
    clauses = []
    for rule in field["rules"]:
        value = f"LOWER({quote(rule['value'])})"
        condition = (
            f"{source} = {value}"
            if rule["match"] == "exact"
            else f"{'STARTSWITH' if rule['match'] == 'prefix' else 'CONTAINS'}({source}, {value})"
        )
        clauses.append(f"WHEN {condition} THEN {quote(rule['category'])}")
    return "CASE " + " ".join(clauses) + " ELSE " + quote(field["otherwise"]) + " END"


def _native_semantics(entity):
    """Compose author-owned Crossfield definitions without interpreting their SQL.

    Schema validation and native ATTACH/compilation own definition validity. Here
    we only protect generated ownership, names and the explicit approval lists.
    """
    native = entity["semantics"].get("crossfield", {})
    if not isinstance(native, dict) or set(native) - {
        "fields",
        "metrics",
        "field_semantics",
        "metric_semantics",
    }:
        raise ValueError("crossfield requires native fields, metrics and their semantics maps")
    for label, values in native.items():
        if not isinstance(values, dict):
            raise ValueError(f"crossfield.{label} must be a mapping")
        for name, value in values.items():
            identifier(name)
            if not isinstance(value, dict) or not value:
                raise ValueError(f"crossfield.{label}.{name} must be a nonempty native definition")
    if set(native.get("metric_semantics", {})) != set(native.get("metrics", {})):
        raise ValueError("Every native metric requires its own Crossfield metric_semantics entry")
    for name, metadata in native.get("metric_semantics", {}).items():
        if metadata.get("dataset", entity["name"]) != entity["name"]:
            raise ValueError(f"Native metric {name} must belong to its declaring entity")
        if not isinstance(metadata.get("comment"), str) or not metadata["comment"].strip():
            raise ValueError(f"Native metric {name} needs a population comment")
    return native


def _metric_inventory(entity):
    native = _native_semantics(entity)
    return [(recipe["name"], recipe["comment"]) for recipe in entity["semantics"]["metrics"]] + [
        (name, native["metric_semantics"][name]["comment"]) for name in native.get("metrics", {})
    ]


def _columns(entity):
    columns = {column["name"]: column for column in entity["columns"]}
    for field in entity["semantics"].get("derived_fields", []):
        if not isinstance(field, dict) or not {"name", "kind", "comment"} <= set(field):
            raise ValueError(
                "Derived fields require a reviewed elapsed-hours, UTC date or text-category recipe"
            )
        name = identifier(field["name"])
        if name in columns or not isinstance(field["comment"], str) or not field["comment"].strip():
            raise ValueError("Derived field names must be distinct and documented")
        if field["kind"] == "elapsed":
            if set(field) != {"name", "kind", "start", "end", "unit", "comment"} or field["unit"] != "h":
                raise ValueError("Elapsed fields require a reviewed elapsed-hours recipe")
            if any(
                columns.get(field[key], {}).get("type") != "TIMESTAMP WITH TIME ZONE"
                for key in ("start", "end")
            ):
                raise ValueError("Elapsed fields require exact timestamp-with-time-zone source columns")
            sql_type, nullable = "DOUBLE", True
        elif field["kind"] == "date":
            if (
                set(field) - {"name", "kind", "source", "timezone", "comment", "granularity"}
                or not {"source", "timezone"} <= set(field)
                or field["timezone"] != "UTC"
            ):
                raise ValueError("Date fields require an explicit UTC timezone and reviewed date recipe")
            if field.get("granularity", "day") not in {"day", "week", "month"}:
                raise ValueError("Date fields only support day, week and month granularity")
            source = columns.get(field["source"])
            if not source or source["type"] != "TIMESTAMP WITH TIME ZONE":
                raise ValueError("Date fields require exact timestamp-with-time-zone source columns")
            sql_type, nullable = "DATE", source["nullable"] or not source["required"]
        elif field["kind"] == "text_category":
            _text_category(field, columns, entity["semantics"]["detail_fields"])
            sql_type, nullable = "VARCHAR", False
        else:
            raise ValueError(
                "Derived fields require a reviewed elapsed-hours, UTC date or text-category recipe"
            )
        columns[name] = {
            "name": name,
            "type": sql_type,
            "nullable": nullable,
            "required": True,
            "schema": {"kind": "scalar", "type": sql_type, "nullable": nullable},
            "description": field["comment"],
            "derived": field,
        }
    for name, definition in _native_semantics(entity).get("fields", {}).items():
        if name in columns:
            raise ValueError(f"Native field {name} collides with a generated source or recipe field")
        sql_type = definition.get("type")
        if not isinstance(sql_type, str) or not sql_type.strip():
            raise ValueError(f"Native field {name} needs its Crossfield type for the generated inventory")
        columns[name] = {
            "name": name,
            "type": sql_type,
            # No generator inference about native expression nullability or types.
            "nullable": True,
            "required": True,
            "schema": {"kind": "native", "type": sql_type, "nullable": True},
            "native": definition,
        }
    return columns


def _recipe(entity, recipe, columns):
    if set(recipe) - {"name", "kind", "field", "where", "comment"} or recipe.get("kind") not in {
        "count",
        "count_distinct",
        "median",
    }:
        raise ValueError("Only reviewed count, distinct-count and median recipes are supported")
    name = identifier(recipe["name"])
    if not isinstance(recipe.get("comment"), str) or not recipe["comment"].strip():
        raise ValueError(f"Metric {name} needs a population comment")
    if recipe["kind"] == "count":
        if "field" in recipe:
            raise ValueError("Count recipes count entity rows, not nullable field values")
        expression, additivity, unit = "COUNT(*)", "additive", None
    elif recipe["kind"] == "count_distinct":
        column = columns.get(recipe.get("field"))
        if not column or column["schema"]["kind"] != "scalar":
            raise ValueError("Distinct count requires a declared scalar field")
        expression = f"COUNT(DISTINCT {entity['name']}.{column['name']})"
        additivity, unit = "non_additive", None
    else:
        column = columns.get(recipe.get("field"))
        if not column or column["type"] not in {"BIGINT", "DOUBLE"}:
            raise ValueError("Median requires a declared numeric field")
        expression = f"MEDIAN({entity['name']}.{column['name']})"
        additivity, unit = "non_additive", column.get("derived", {}).get("unit")
    where = recipe.get("where")
    population = None
    if where is not None:
        if not isinstance(where, dict) or set(where) - {"field", "op", "value", "values"}:
            raise ValueError(f"Invalid population recipe for {name}")
        column = columns.get(where.get("field"))
        if not column or column["schema"]["kind"] != "scalar":
            raise ValueError(f"Metric {name} population must reference a declared scalar column")
        field = entity["name"] + "." + column["name"]
        if where.get("op") in {"is_null", "is_not_null"} and set(where) == {"field", "op"}:
            population = field + (" IS NULL" if where["op"] == "is_null" else " IS NOT NULL")
        else:
            if where.get("op") == "eq" and set(where) == {"field", "op", "value"}:
                values = [where["value"]]
            elif where.get("op") == "in" and set(where) == {"field", "op", "values"}:
                values = where["values"]
            else:
                raise ValueError(f"Metric {name} has an unsupported population operation")
            if not isinstance(values, list) or not values or len(values) > 100:
                raise ValueError(f"Metric {name} needs a bounded nonempty population domain")
            if column["type"] != "VARCHAR" or any(not isinstance(value, str) for value in values):
                raise ValueError(f"Metric {name} requires an exact VARCHAR population domain")
            population = field + (
                " = " + quote(values[0])
                if where["op"] == "eq"
                else " IN (" + ", ".join(quote(value) for value in values) + ")"
            )
    return expression, population, additivity, unit


def validate_semantics(contract, overlay):
    if overlay.get("format") != "vgi-github-semantic-overlay" or overlay.get("version") != 1:
        raise ValueError("Unsupported semantic overlay format/version")
    if set(overlay) - {"crossfield", "cohorts"} != {
        "format",
        "version",
        "model",
        "entities",
        "scopes",
        "functions",
        "relationships",
        "shared_dimensions",
    }:
        raise ValueError("Unknown or missing connected semantic overlay property")
    configuration = overlay["model"]
    if set(configuration) != {"name", "id", "comment", "instance_id", "api_origin"}:
        raise ValueError("Invalid connected model configuration")
    identifier(configuration["name"])
    if configuration["id"] == "queryfarm.github.reporting":
        raise ValueError("The connected model must retain its separate identity until qualification")
    if any(not isinstance(value, str) or not value.strip() for value in configuration.values()):
        raise ValueError("Model configuration values must be nonempty strings")
    functions = {entity["name"]: entity for entity in contract["functions"]}
    metrics, reports, public_names, fields = set(), set(), set(), {}
    for entity in functions.values():
        identifier(entity["name"])
        columns, policy = _columns(entity), entity["semantics"]
        if set(policy) - {
            "detail_fields",
            "dimensions",
            "metrics",
            "detail_report",
            "derived_fields",
            "sql_names",
            "crossfield",
        } or not {"detail_fields", "dimensions", "metrics"} <= set(policy):
            raise ValueError(f"Entity {entity['name']} requires explicit semantic approvals")
        for key in ("detail_fields", "dimensions"):
            approved = policy[key]
            if not isinstance(approved, list) or len(set(approved)) != len(approved):
                raise ValueError(f"Invalid {key} approvals for {entity['name']}")
            if not set(approved).issubset(columns):
                raise ValueError(f"Unknown column in {entity['name']} {key}")
        for name, column in columns.items():
            identifier(name)
            fields[entity["name"] + "." + name] = column
        for field in policy["dimensions"]:
            if columns[field]["schema"]["kind"] not in {"scalar", "native"}:
                raise ValueError("Nested values cannot become aggregate dimensions")
        for field, sql_name in policy.get("sql_names", {}).items():
            if field not in policy["dimensions"] or identifier(sql_name) in public_names:
                raise ValueError("SQL names require a unique approved dimension")
            public_names.add(sql_name)
        if "detail_report" in policy:
            report = policy["detail_report"]
            if set(report) != {"name", "comment"} or not report["comment"]:
                raise ValueError("Optional detail report requires a name and population comment")
            if identifier(report["name"]) in reports:
                raise ValueError(f"Duplicate report {report['name']}")
            reports.add(report["name"])
        native = _native_semantics(entity)
        if not set(native.get("field_semantics", {})).issubset(columns):
            raise ValueError("Native field_semantics must reference a field in its declaring entity")
        for recipe in policy["metrics"]:
            _recipe(entity, recipe, columns)
        for metric_name, _ in _metric_inventory(entity):
            if metric_name in metrics:
                raise ValueError(f"Duplicate metric {metric_name}")
            metrics.add(metric_name)
    relationships = set()
    for relation in contract["relationships"]:
        required = {"name", "from", "to", "from_columns", "to_columns"}
        if not required <= set(relation) or set(relation) - required - {
            "optional",
            "retrievals",
            "analytical",
        }:
            raise ValueError("Relationships require named many-to-one key mappings")
        if "optional" in relation and type(relation["optional"]) is not bool:
            raise ValueError("Relationship optional must be a boolean")
        if "analytical" in relation and type(relation["analytical"]) is not bool:
            raise ValueError("Relationship analytical must be a boolean")
        name = identifier(relation["name"])
        if name in relationships or relation["from"] not in functions or relation["to"] not in functions:
            raise ValueError("Relationship names and entity references must be valid and unique")
        relationships.add(name)
        if relation["to_columns"] != functions[relation["to"]]["grain"] or len(
            relation["from_columns"]
        ) != len(relation["to_columns"]):
            raise ValueError(f"Relationship {name}: targets must cover the complete entity grain")
        for left, right in zip(relation["from_columns"], relation["to_columns"], strict=True):
            source, target = (
                fields.get(relation["from"] + "." + left),
                fields.get(relation["to"] + "." + right),
            )
            if (
                not source
                or not target
                or source["type"] != target["type"]
                or source["schema"]["kind"] != "scalar"
            ):
                raise ValueError(
                    "Relationship keys require declared scalar columns with matching exact types"
                )
        for retrieval in relation.get("retrievals", []):
            if (
                not {"direction", "route", "bindings"} <= set(retrieval)
                or set(retrieval) - {"direction", "route", "bindings", "when", "when_not_null", "when_null"}
                or retrieval["direction"]
                not in {
                    "forward",
                    "reverse",
                }
            ):
                raise ValueError("Relationship retrievals require a direction, route and parameter bindings")
            start, target = (
                (relation["from"], relation["to"])
                if retrieval["direction"] == "forward"
                else (relation["to"], relation["from"])
            )
            entity = functions[target]
            if "when" in retrieval:
                conditions = retrieval["when"]
                if not isinstance(conditions, dict) or not conditions:
                    raise ValueError("Relationship retrieval conditions require scalar field equalities")
                for column, value in conditions.items():
                    field = fields.get(start + "." + column)
                    if field is None or field["schema"]["kind"] != "scalar":
                        raise ValueError("Relationship retrieval conditions require declared scalar fields")
                    _binding({"literal": value}, {}, field["type"], field["nullable"], name)
            for guard in ("when_null", "when_not_null"):
                if guard not in retrieval:
                    continue
                columns = retrieval[guard]
                if (
                    not isinstance(columns, list)
                    or not columns
                    or any(not isinstance(column, str) for column in columns)
                    or len(set(columns)) != len(columns)
                    or any(start + "." + column not in fields for column in columns)
                ):
                    raise ValueError("Relationship null guards require distinct declared typed fields")
                if any(
                    column in retrieval.get("when", {})
                    and ((retrieval["when"][column] is None) != (guard == "when_null"))
                    for column in columns
                ):
                    raise ValueError("Relationship retrieval conditions contradict their null guards")
            if set(retrieval.get("when_null", [])) & set(retrieval.get("when_not_null", [])):
                raise ValueError("Relationship retrieval conditions cannot require both NULL and non-NULL")
            route_name = target + "__" + retrieval["route"] if "routes" in entity else target
            route = next(
                (route for route in entity.get("routes", [entity]) if route["name"] == route_name), None
            )
            if route is None or ("routes" not in entity and retrieval["route"] != target):
                raise ValueError(
                    f"Relationship retrieval refers to an unknown target route: {name} -> {route_name}"
                )
            parameters = {arg["name"]: arg for arg in route["arguments"]}
            bindings = retrieval["bindings"]
            if not isinstance(bindings, dict) or not bindings:
                raise ValueError("Relationship retrieval requires parameter bindings")
            for parameter, column in bindings.items():
                if isinstance(column, dict):
                    if set(column) != {"literal"} or parameter not in parameters:
                        raise ValueError("Relationship retrieval literal must bind a known parameter")
                    argument = parameters[parameter]
                    _binding(column, {}, argument["type"], argument["nullable"], name)
                    if "enum" in argument and column["literal"] not in argument["enum"]:
                        raise ValueError("Relationship retrieval literal is outside the parameter enum")
                    continue
                if not isinstance(column, str):
                    raise ValueError("Relationship retrieval bindings require a source field or literal")
                field = fields.get(start + "." + column)
                if (
                    parameter not in parameters
                    or field is None
                    or parameters[parameter]["type"] != field["type"]
                ):
                    raise ValueError(
                        "Relationship retrieval bindings must preserve exact source field and parameter types"
                    )
            if not {arg["name"] for arg in route["arguments"] if not arg["nullable"]} <= bindings.keys():
                raise ValueError("Relationship retrieval must bind all required route parameters")
            if (
                "selection" in route
                and not route.get("default")
                and not set(route["selection"]).intersection(bindings)
            ):
                raise ValueError("Relationship retrieval bindings must select their route")
    edges = {name: [] for name in functions}
    for relation in contract["relationships"]:
        if relation.get("analytical", True):
            edges[relation["from"]].append(relation["to"])
    complete, active = set(), set()

    def visit(name):
        if name in active:
            raise ValueError("Semantic relationships must not form a cycle")
        if name in complete:
            return
        active.add(name)
        for child in edges[name]:
            visit(child)
        active.remove(name)
        complete.add(name)

    for name in edges:
        visit(name)
    assigned = set()
    for identity, members in contract["shared_dimensions"].items():
        if not isinstance(identity, str) or not identity.strip() or not members:
            raise ValueError("Shared dimensions need an explicit identity and members")
        if len(set(members)) != len(members) or any(
            member not in fields or member in assigned or fields[member]["schema"]["kind"] != "scalar"
            for member in members
        ):
            raise ValueError("Shared dimensions require unique declared scalar members")
        if len({fields[member]["type"] for member in members}) != 1:
            raise ValueError("Shared dimensions must preserve exact scalar types")
        assigned.update(members)


def _parameter_constraints(contract):
    """Preserve each scope rule only on public datasets that execute that scope."""
    grouped = {}
    for entity in contract["functions"]:
        if "routes" in entity:
            alternatives = set()

            def shared_requirements(trigger, dependencies, routes=entity["routes"]):
                # Native presence constraints apply to the whole dataset, not to
                # an individual route. A parameter can also be an optional
                # context argument on another route selected by a different key.
                # Keep only implications that every such valid route guarantees.
                dependencies = set(dependencies) - {trigger}
                for peer in routes:
                    if trigger not in {arg["name"] for arg in peer["arguments"]}:
                        continue
                    guaranteed = {arg["name"] for arg in peer["arguments"] if not arg["nullable"]}
                    guaranteed.add(trigger)
                    rules = [
                        (parameter, required)
                        for stage in peer["traversal"]["stages"]
                        for parameter, required in contract["scopes"]
                        .get(stage.get("scope"), {})
                        .get("requires_parameters", {})
                        .items()
                    ]
                    while True:
                        previous = guaranteed.copy()
                        for parameter, required in rules:
                            if parameter in guaranteed:
                                guaranteed.update(required)
                        if guaranteed == previous:
                            break
                    dependencies.intersection_update(guaranteed)
                return tuple(sorted(dependencies))

            for selection in entity.get("filters", []):
                cohort = selection["root"]["cohort"]
                key = ("at_most_one", "", tuple(sorted([*cohort["alternatives"], cohort["parameter"]])))
                grouped.setdefault(key, set()).add(entity["name"])
            for route in entity["routes"]:
                cohort = route.get("cohort")
                parameters = tuple(sorted(route["selection"]))
                alternatives.update(parameters)
                if cohort:
                    cohort_parameters = tuple(sorted([*cohort["alternatives"], cohort["parameter"]]))
                    grouped.setdefault(("at_most_one", "", cohort_parameters), set()).add(entity["name"])
                required = {arg["name"] for arg in route["arguments"] if not arg["nullable"]}
                for trigger in parameters:
                    dependencies = shared_requirements(trigger, required)
                    if dependencies:
                        grouped.setdefault(("requires", trigger, dependencies), set()).add(entity["name"])
                for stage in route["traversal"]["stages"]:
                    scope = contract["scopes"].get(stage.get("scope"), {})
                    for trigger, required in scope.get("requires_parameters", {}).items():
                        dependencies = shared_requirements(trigger, required)
                        if dependencies:
                            key = ("requires", trigger, dependencies)
                            grouped.setdefault(key, set()).add(entity["name"])
            if not any(route.get("default") for route in entity["routes"]):
                grouped.setdefault(("at_least_one", "", tuple(sorted(alternatives))), set()).add(
                    entity["name"]
                )
            continue
        cohort = entity.get("cohort")
        if cohort:
            key = ("exactly_one", "", tuple(sorted([*cohort["alternatives"], cohort["parameter"]])))
            grouped.setdefault(key, set()).add(entity["name"])
        for stage in entity["traversal"]["stages"]:
            if "scope" not in stage:
                continue
            scope = contract["scopes"][stage["scope"]]
            exclusive = scope.get("exclusive_parameters", [])
            if exclusive and (not cohort or set(exclusive) != set(cohort["alternatives"])):
                key = ("exactly_one", "", tuple(sorted(exclusive)))
                grouped.setdefault(key, set()).add(entity["name"])
            for trigger, required in scope.get("requires_parameters", {}).items():
                key = ("requires", trigger, tuple(sorted(required)))
                grouped.setdefault(key, set()).add(entity["name"])
    return [
        {
            "kind": kind,
            "parameters": list(parameters),
            "datasets": sorted(datasets),
            **({"when": trigger} if kind == "requires" else {}),
        }
        for (kind, trigger, parameters), datasets in sorted(grouped.items())
    ]


def build_model(contract, overlay):
    validate_semantics(contract, overlay)
    config = overlay["model"]
    model_id, model_name = config["id"], config["name"]
    policy = {
        "policy_version": 1,
        "metrics": [],
        "dimensions": [],
        "filter_dimensions": [],
        "detail_fields": [],
        "metric_semantics": {},
        "field_semantics": {},
        "dataset_semantics": {},
        "invocation_sources": [],
        "relationships": [],
        "relationship_semantics": {},
        "allow_semantic_joins": True,
        "tags": {
            "github.relationship_retrievals": json.dumps(
                {
                    relation["name"]: relation["retrievals"]
                    for relation in contract["relationships"]
                    if relation.get("retrievals")
                },
                sort_keys=True,
            )
        },
    }
    model = {
        "crossfield": 1,
        "name": model_name,
        "id": model_id,
        "comment": config["comment"],
        "invocations": {"version": 1, "input_contracts": {}, "sources": {}},
        "metrics": {},
        "policy": policy,
        "relationships": [
            {
                key: value
                for key, value in relation.items()
                if key not in {"optional", "retrievals", "analytical"}
            }
            for relation in contract["relationships"]
        ],
        "semantic_query": {
            "parameters": {},
            "constraints": _parameter_constraints(contract),
            "request": {"version": 1, "source_bindings": {}},
        },
    }
    shared = {
        member: identity for identity, members in contract["shared_dimensions"].items() for member in members
    }
    reports = []
    for entity in contract["functions"]:
        name, reviewed, arguments = entity["name"], entity["semantics"], entity["arguments"]
        fields, result_columns = {}, []
        columns = _columns(entity)
        for field_name, column in columns.items():
            full = name + "." + field_name
            field = {"dimension": field_name in reviewed["dimensions"] or full in shared}
            if "native" in column:
                definition = column["native"]
                if "dimension" in definition and definition["dimension"] != field["dimension"]:
                    raise ValueError(f"Native field {full} conflicts with its dimension approval")
                field.update(deepcopy(definition))
            elif "derived" in column:
                definition = column["derived"]
                if definition["kind"] == "date":
                    granularity = definition.get("granularity", "day")
                    expression = f"CAST({name}.{definition['source']} AS DATE)"
                    if granularity != "day":
                        expression = f"CAST(DATE_TRUNC({quote(granularity)}, {expression}) AS DATE)"
                    field.update(
                        expression=expression,
                        type="DATE",
                        is_time=True,
                        timezone="UTC",
                        calendar="gregorian",
                        granularity=granularity,
                    )
                elif definition["kind"] == "text_category":
                    field.update(expression=_text_category_sql(name, definition), type="VARCHAR")
                else:
                    field.update(
                        expression=(
                            f"DATEDIFF('millisecond', {name}.{definition['start']}, "
                            f"{name}.{definition['end']}) / 3600000.0"
                        ),
                        type="DOUBLE",
                        unit="h",
                    )
            else:
                field["source_column"] = field_name
                result_columns.append(
                    {
                        "name": field_name,
                        "type": column["type"],
                        "nullable": column["nullable"] or not column["required"],
                    }
                )
            if "native" not in column and column["type"] == "TIMESTAMP WITH TIME ZONE":
                field["timezone"] = "UTC"
            fields[field_name] = field
            if field_name in reviewed["detail_fields"]:
                policy["detail_fields"].append(full)
            if field_name in reviewed["dimensions"]:
                policy["dimensions"].append(full)
                policy["filter_dimensions"].append(full)
            metadata = {"comment": column.get("description") or f"Declared {field_name} field from {name}."}
            if full in shared:
                metadata["shared_dimension"] = shared[full]
            if field_name in reviewed.get("sql_names", {}):
                metadata["sql_name"] = reviewed["sql_names"][field_name]
            native_metadata = _native_semantics(entity).get("field_semantics", {}).get(field_name, {})
            for key in ("shared_dimension", "sql_name"):
                if key in metadata and key in native_metadata and metadata[key] != native_metadata[key]:
                    raise ValueError(f"Native field {full} conflicts with generated {key}")
            metadata.update(deepcopy(native_metadata))
            policy["field_semantics"][full] = metadata
        model["invocations"]["sources"][name] = {
            "id": model_id + "/sources/" + name,
            "dataset": {
                "name": name,
                "id": model_id + "/datasets/" + name,
                "grain": entity["grain"],
                "fields": fields,
            },
            "binding_key": "github_source",
            "provider_id": "queryfarm.vgi.github",
            "instance_id": config["instance_id"],
            "function": {
                "schema": "generated",
                "name": name,
                "arguments": [
                    {
                        "id": arg["name"],
                        "physical_name": arg["name"],
                        "position": arg["position"],
                        "type": arg["type"],
                        "nullable": arg["nullable"],
                        "binding": "scalar",
                    }
                    for arg in arguments
                ],
            },
            "profile": "producer_sync_v1",
            "result_columns": result_columns,
            "assertions": {
                "authority": model_id,
                "read_only": True,
                "execution_safe_bind": True,
                "input_from_args": False,
                "independent_rows": True,
                "requires_optimizer": False,
                "async": False,
            },
            "consistency": {"kind": "live_explicit", "authority": model_id},
            "settings": [],
            "required_secrets": [],
            "attachment_tags": {
                "vgi_github_reporting": "true",
                "vgi_github_operation_timeout_seconds": "120",
                "vgi_github_api_origin": config["api_origin"],
            },
            "transport": {
                "finite_timeout_ms": 125000,
                "cooperative_cancellation": True,
                "authority": "queryfarm.vgi.posix-subprocess",
            },
        }
        policy["invocation_sources"].append(name)
        route_comments = [
            f"Route {route['name']}, "
            + ("default" if route.get("default") else "selected by " + ", ".join(route["selection"]))
            + f": {route['population']}"
            for route in entity.get("routes", [])
            if "population" in route
        ]
        policy["dataset_semantics"][name] = {
            "comment": " ".join([entity["description"], *route_comments]),
            "key_evidence": "declared",
            "tags": {
                "github.retrieval_routes": json.dumps(
                    [
                        {
                            key: route[key]
                            for key in ("name", "selection", "select_values", "default", "population")
                            if key in route
                        }
                        for route in entity.get("routes", [])
                    ],
                    sort_keys=True,
                )
            },
        }
        for recipe in reviewed["metrics"]:
            metric_name = recipe["name"]
            expression, population, additivity, unit = _recipe(entity, recipe, columns)
            model["metrics"][metric_name] = {"expression": expression}
            metadata = {"dataset": name, "additivity": additivity, "comment": recipe["comment"]}
            metadata["missing"] = "zero" if recipe["kind"] in {"count", "count_distinct"} else "null"
            if population:
                metadata.update(
                    population=population,
                    population_id=name + "/" + hashlib.sha256(population.encode()).hexdigest()[:12],
                )
            if unit:
                metadata["unit"] = unit
            policy["metrics"].append(metric_name)
            policy["metric_semantics"][metric_name] = metadata
        native = _native_semantics(entity)
        for metric_name, definition in native.get("metrics", {}).items():
            model["metrics"][metric_name] = deepcopy(definition)
            policy["metrics"].append(metric_name)
            policy["metric_semantics"][metric_name] = {
                "dataset": name,
                **deepcopy(native["metric_semantics"][metric_name]),
            }
        request = {
            "version": 1,
            "source_bindings": {
                name: {"arguments": {arg["name"]: {"parameter": arg["name"]} for arg in arguments}}
            },
        }
        parameters = [
            {
                "name": arg["name"],
                "type": arg["type"],
                "nullable": arg["nullable"],
                "comment": arg.get("description") or arg["name"],
            }
            for arg in arguments
        ]
        for arg, parameter in zip(arguments, parameters, strict=True):
            public = {key: value for key, value in parameter.items() if key != "name"}
            if "default" in arg:
                public["default"] = arg["default"]
            if "min_length" in arg:
                if arg["min_length"] == 1:
                    public["non_empty"] = True
                else:
                    public["min_length"] = arg["min_length"]
            for bound in ("max_length", "pattern"):
                if bound in arg:
                    public[bound] = arg[bound]
            if "minimum" in arg:
                public["minimum"] = arg["minimum"]
            if "example" in arg:
                public["example"] = arg["example"]
            if "enum" in arg:
                public["comment"] += (
                    " Allowed values: " + json.dumps(arg["enum"]) + ". Validated before retrieval."
                )
            existing = model["semantic_query"]["parameters"].setdefault(parameter["name"], public)
            if existing != public:
                raise ValueError(f"Inconsistent shared semantic parameter {parameter['name']}")
        model["semantic_query"]["request"]["source_bindings"].update(request["source_bindings"])
        if "detail_report" in reviewed:
            report = reviewed["detail_report"]
            detail = {**request, "detail_dataset": name}
            select = ", ".join(f'{name}."{field}" AS "{field}"' for field in reviewed["detail_fields"])
            sql = (
                "SELECT "
                + select
                + " FROM crossfield_pipeline("
                + quote(model_name)
                + ","
                + quote(json.dumps(detail, separators=(",", ":")))
            )
            sql += "".join(",$" + arg["name"] for arg in arguments) + ")"
            reports.append(
                {
                    "name": report["name"],
                    "report_id": str(uuid.uuid5(NAMESPACE, report["name"])),
                    "semantic_sql": sql,
                    "parameters": parameters,
                    "comment": report["comment"],
                    "tags": {"source": name, "consistency": "live"},
                }
            )
    for relation in contract["relationships"]:
        if relation.get("analytical", True):
            policy["relationships"].append(relation["name"])
        policy["relationship_semantics"][relation["name"]] = {
            "optional": relation.get("optional", False),
            "key_evidence": "declared",
            "authority": model_id,
        }
    apply_native_overlay(model, overlay.get("crossfield", {}))
    return model, reports


def documentation(contract, overlay, coverage_audit=None):
    lines = [
        "# Connected generated GitHub model",
        "",
        overlay["model"]["comment"],
        "",
        "[coverage.json](coverage.json) compares this model with every pinned REST GET operation "
        "and the complete query-reachable GraphQL type graph. It records implemented routes, "
        "unselected API fields, possible opposite-direction fields and upstream schema errors. "
        "These schema candidates do not establish equivalent populations or approved retrieval paths; "
        "the audit does not execute live endpoints.",
        "",
        "Start with an organization, a user or a repository. Organizations connect to visible members, "
        "teams and repository activity; users connect to authored pull requests, issues, discussions "
        "and comments across visible repositories. "
        "Ownership, membership, authorship and reviewing are separate roles. Each metric retains "
        "its own entity grain, and every public source also supports callable detail.",
        "",
        "[research.sql](research.sql) is the runnable researcher workflow: compare contribution types "
        "over UTC periods, count active days and repositories, and inspect source evidence. "
        "Title categories use explicit model-owned rules; repository language supplies context. "
        "Neither is an inferred interest or employee-performance score.",
        "",
        "```sql",
        "-- Load the matching native extensions described in ../../docs/CROSSFIELD_SPEC.md first.",
        "SET TimeZone='UTC';",
        "ATTACH 'github' AS generated_source (TYPE vgi,",
        "  LOCATION '/path/to/.venv/bin/python -m vgi_github.generated_worker', reporting true);",
        "ATTACH 'models/generated-pilot/github-generated.package.json' AS engineering",
        '  (TYPE crossfield, BINDINGS \'{"github_source":{"catalog":"generated_source",',
        '    "provider_id":"queryfarm.vgi.github","instance_id":"github.com"}}\');',
        "SET crossfield_mode='strict';",
        "",
        "-- Organization inventory: no repository argument is needed.",
        "SELECT organization_login, organization_member_count, team_count, repository_count",
        "FROM engineering.semantic.github(organization => 'Query-farm')",
        "GROUP BY organization_login;",
        "",
        "SELECT team_slug, team_count, team_membership_count",
        "FROM engineering.semantic.github(organization => 'Query-farm')",
        "GROUP BY team_slug ORDER BY team_slug;",
        "",
        "-- User activity includes PRs in repositories the user does not own.",
        "SELECT user_login, user_count, pull_request_count, merged_prs,",
        "       median_merge_hours",
        "FROM engineering.semantic.github(user => 'octocat') GROUP BY user_login;",
        "",
        "SELECT pull_request_repository_name, pull_request_count, merged_prs",
        "FROM engineering.semantic.github(user => 'octocat')",
        "GROUP BY pull_request_repository_name ORDER BY pull_request_repository_name;",
        "",
        "SELECT pull_request_merged_day, merged_prs, median_merge_hours",
        "FROM engineering.semantic.github(user => 'octocat')",
        "WHERE pull_request_merged_day >= DATE '2026-09-01'",
        "  AND pull_request_merged_day < DATE '2026-10-01'",
        "GROUP BY pull_request_merged_day ORDER BY pull_request_merged_day;",
        "",
        "SELECT * FROM engineering.detail.organization_memberships(organization => 'Query-farm');",
        "SELECT * FROM engineering.detail.users(user => 'octocat');",
        "",
        "-- Existing repository and owner scopes remain available.",
        "SELECT repository_name, repository_count, pull_request_count, merged_prs,",
        "       median_merge_hours, submitted_review_count, approved_review_count",
        "FROM engineering.semantic.github(owner => 'Query-farm') GROUP BY repository_name;",
        "",
        "SELECT author_login, pull_request_count, median_merge_hours",
        "FROM engineering.semantic.github(repository => 'Query-farm/crossfield') GROUP BY author_login;",
        "",
        "SELECT reviewer_login, submitted_review_count, approved_review_count",
        "FROM engineering.semantic.github(repository => 'Query-farm/crossfield') GROUP BY reviewer_login;",
        "",
        "-- Merge cohort: UTC dates, inclusive start and exclusive end.",
        "SELECT pull_request_merged_day, merged_prs, median_merge_hours",
        "FROM engineering.semantic.github(repository => 'Query-farm/crossfield')",
        "WHERE pull_request_merged_day >= DATE '2026-09-01'",
        "  AND pull_request_merged_day < DATE '2026-10-01'",
        "GROUP BY pull_request_merged_day ORDER BY pull_request_merged_day;",
        "",
        "SELECT review_submitted_day, reviewer_login, submitted_review_count",
        "FROM engineering.semantic.github(repository => 'Query-farm/crossfield')",
        "WHERE review_submitted_day >= DATE '2026-09-01'",
        "  AND review_submitted_day < DATE '2026-10-01'",
        "GROUP BY review_submitted_day, reviewer_login;",
        "",
        "SELECT review_id, reviewer_login, state, body FROM engineering.detail.pull_request_reviews(",
        "  repository => 'Query-farm/crossfield', pull_request_number => 1) ORDER BY review_id;",
        "",
        "-- Discover names, types, calling conventions and scope rules without fetching GitHub data.",
        "SELECT name, type, is_named, is_positional, is_const, example, constraints",
        "FROM crossfield_parameters()",
        "WHERE database_name='engineering' AND schema_name='semantic'",
        "  AND invocation_name='engineering.semantic.github' ORDER BY ordinal;",
        "```",
        "",
        "For repository inventory and label definitions, choose exactly one of `organization`, "
        "`owner`, `repository` and `repositories`. `organization` explicitly selects an organization's "
        "visible "
        "repositories. The existing `owner` route resolves account type; a user owner lists PUBLIC "
        "owned repositories, not that person's contributions or private user inventory. Optional "
        "`pull_request_number` requires `repository`. Invalid, empty or conflicting scope arguments "
        "fail before HTTP.",
        "",
        "The parameter catalog publishes example values as JSON and declares named, constant "
        "arguments. Examples are suggestions, never defaults: omitting `pull_request_number` "
        "still selects all PRs even though its example is `1`. The constraints include nonempty "
        "resource names, PR numbers of at least 1, mutually exclusive scope choices and the "
        "repository requirement for a PR number. Crossfield validates the rules for the selected "
        "datasets before provider execution; a user-only query does not require a repository. "
        "Detail entries publish the same rules for their own sources. NULL defaults count as "
        "absent when choosing a scope.",
        "",
        "The entity contracts below list each selectable population and retrieval route. Only sources "
        "needed by the selected measures, dimensions and filters are fetched. Requesting a profile "
        "does not enumerate repositories; zero-activity users and empty organizations remain "
        "visible when `user_count` or `organization_count` establishes the inventory population.",
        "",
        "For explicit cohorts use `users => [{'login': 'octocat'}, {'login': 'hubot'}]` or "
        "`repositories => [{'repository': 'Query-farm/crossfield'}, {'repository': 'Query-farm/vgi'}]`. "
        "Cohorts are mutually exclusive with their singular scope alternatives. NULL means absent; "
        "an empty list selects an empty population. Names must be nonempty and unique ignoring case. "
        "Source pages must respect their declared grain. Distinct-entity routes remove repeated targets "
        "across parents; membership routes retain each identity pair. Object numbers require one "
        "`repository`. Discovery publishes the exact LIST/STRUCT types and examples.",
        "",
        "`pull_requests` is one entity under either repository or author selection. Supply a repository "
        "scope, `user`/`users`, or both; both selects their intersection. Reviews and PR label/assignee "
        "memberships follow the same PR population. For reviews, `user` means PR author, never reviewer. "
        "One metric family (`pull_request_count`, `merged_prs`, `median_merge_hours`) works across scopes. "
        "Use `pull_request_repository_name` for the repository carried on each PR; `repository_name` "
        "belongs to the separately selected repository inventory. The former `authored_*` public names "
        "are removed. Issues, discussions and comments also expose reverse retrieval routes; the entity "
        "contracts below describe each selectable population and its visibility.",
        "",
        "Each selected function streams its own traversal. Separate functions may fetch the same "
        "ancestors; cross-function HTTP sharing awaits a paginated row-map interface in VGI. "
        "Native stages reuse their own parent relation without mixing independent fact grains.",
        "",
        "User PR discovery uses GitHub's cursor-paginated user connection across visible repositories. "
        "Each row must identify the selected canonical user as its author; missing or different "
        "authors fail rather than silently changing the population. Each discovered PR is hydrated "
        "through repository and PR REST lookups, adding two requests per PR to preserve the same "
        "complete fields under either scope. PR state is open/closed; a merge timestamp identifies "
        "merged PRs. This is authored-PR activity, "
        "not an all-contributions score, an events timeline or a capped search result. Authored issues, "
        "discussions and issue/discussion/commit comments use their own cursor-paginated user "
        "connections with the same author check. Issue comments include comments on pull requests; "
        "commit comments describe comments, not authored commits. Private or inaccessible content "
        "is outside the visible population. Deleted discussion subjects may lack repository context; "
        "the unknown-repository count makes those records visible.",
        "",
        "Active-day and distinct-repository metrics are non-additive counts: request the desired "
        "grouping directly instead of summing daily or category subtotals. DATE dimensions use UTC "
        "days; weekly periods start on ISO Monday and monthly periods on the first day. Ordered "
        "case-insensitive title-prefix rules label explicit conventions such as `docs:` or `fix:`; "
        "unmatched titles stay `unclassified`. Detail rows retain titles, bodies, timestamps and URLs "
        "for checking the evidence. Repository primary language is current repository context, "
        "not the language of an individual contribution.",
        "",
        "Membership means GitHub membership visible to the caller, not employment. Public-only "
        "credentials cannot establish a complete private roster. Team membership includes "
        "members inherited from child teams; nullable role/inheritance fields preserve what the "
        "pinned API actually supplies. `team_membership_count` counts team/account pairs. Someone "
        "in two teams contributes two memberships, but does not become two organization members. "
        "PR/review measures cannot be grouped through a team's membership: that attribution rule "
        "has not been approved. Organization members are not silently equated with all contributors.",
        "",
        "API meaning: [user activity](https://docs.github.com/en/graphql/reference/users#user), "
        "[organization membership](https://docs.github.com/en/rest/orgs/members#list-organization-members), "
        "[effective team membership](https://docs.github.com/en/rest/teams/members#list-team-members).",
        "",
        "Include `repository_count` to establish repository inventory as the grouping axis, including empty "
        "repositories. PR-only reports describe the PR population. Label counts describe "
        "definitions, not assignments. "
        "Review counts describe records, not distinct reviewers, latest decisions or merge eligibility.",
        "Count metrics return zero for an established group with no matching records. "
        "Median merge time remains NULL for an empty merged cohort.",
        "",
        "`pull_request_created_day`, `pull_request_merged_day` and `review_submitted_day` are approved "
        "DATE dimensions "
        "computed by DuckDB from the corresponding timestamp. "
        "They use Gregorian UTC calendar days, with a required `TimeZone='UTC'` session. "
        "Unmerged PRs have a NULL merge day; a missing review submission timestamp stays NULL. "
        "A merge-day filter selects PRs merged in the interval; a creation-day filter selects "
        "PRs created in it. Review-day filtering selects review activity and does not define "
        "a PR merge cohort. The model preserves these different populations and roles.",
        "",
        "Schema facts define types; declarative scopes select sources, traversals map parent "
        "fields to child inputs, "
        "and semantic relationships define approved many-to-one joins. Business recipes define "
        "populations and "
        "elapsed-hour calculations. Saved reports are optional; this package needs none.",
        "Relationship retrieval bindings are validated against source fields and target route parameters. "
        "The generated model publishes them in `policy.tags.github.relationship_retrievals`; "
        "dataset tags publish `github.retrieval_routes`. Supplying the declared parameters executes "
        "the corresponding provider route. These metadata tags describe navigation; analytical "
        "join planning continues to use the approved relationship keys and cardinalities.",
        "A retrieval's `when` equalities and `when_null`/`when_not_null` field guards must all hold "
        "before using its bindings. Unavailable identity evidence does not establish a navigable parent.",
        "Relationships marked `analytical: false` retain their declared keys and retrieval bindings "
        "but are not approved as analytical join paths. Actions jobs and attempts join through "
        "runs and workflows. Artifacts join directly to repositories so artifacts without run "
        "metadata retain their repository context. Artifact run associations remain available "
        "for retrieval and identity fields; analytical enrichment by run outcome is not approved.",
        "",
        research_documentation(),
        "",
        (
            analysis_documentation()
            if "mean_first_review_hours" in overlay.get("crossfield", {}).get("metrics", {})
            else ""
        ),
        "",
        "## Entity contracts",
        "",
    ]
    for entity in contract["functions"]:
        lines += [
            f"### `{entity['name']}`",
            "",
            entity["description"],
            "",
            "Grain: " + ", ".join(f"`{key}`" for key in entity["grain"]) + ".",
            "",
        ]
        if "routes" in entity:
            lines += ["| Retrieval route | Selection | Population |", "| --- | --- | --- |"]
            for route in entity["routes"]:
                selection = (
                    "Default"
                    if route.get("default")
                    else ", ".join(f"`{name}`" for name in route["selection"])
                )
                if route.get("select_values"):
                    selection += "; " + ", ".join(
                        f"`{key}` in {json.dumps(values)}" for key, values in route["select_values"].items()
                    )
                lines.append(
                    f"| `{route['name']}` | {selection} | {route.get('population', entity['description'])} |"
                )
            lines.append("")
        lines += ["| Column | SQL type | Nullable |", "| --- | --- | --- |"]
        for column in _columns(entity).values():
            nullable = (
                "native expression"
                if "native" in column
                else "yes"
                if column["nullable"] or not column["required"]
                else "no"
            )
            lines.append(f"| `{column['name']}` | `{column['type']}` | {nullable} |")
        lines += (
            ["", "Approved metrics:", ""]
            + [f"- `{name}`: {comment}" for name, comment in _metric_inventory(entity)]
            + [""]
        )
    lines += [
        "## Reproduce",
        "",
        "```sh",
        "python scripts/generate_semantic_catalog.py",
        "python scripts/generate_semantic_catalog.py --check",
        "python scripts/generate_semantic_catalog.py --verify-source-cache /path/to/full-source-cache",
        "```",
        "",
        "The source lock and retained licenses record immutable upstream inputs. Runtime never "
        "downloads schemas. "
        "The existing broad GitHub model/default worker remain available. This connected graph "
        "is deliberately "
        "bounded. Reads are live across sources, without a transactionally consistent GitHub "
        "snapshot. HTTP errors, "
        "malformed responses and duplicate identities fail the query. All advertised pages are "
        "followed without a generated row or page cap; operation deadlines still apply. "
        "Crossfield adds no row cap; SQL LIMIT controls presentation.",
    ]
    if coverage_audit is not None:
        summary = coverage_audit["summary"]
        measured = [
            "",
            "## Measured API coverage",
            "",
            f"The generated model selects {summary['rest_selected_operations']} of "
            f"{summary['rest_operations']} pinned REST read operations. The implementation scope "
            f"contains {summary['rest_in_scope_operations']} operations, of which "
            f"{summary['rest_in_scope_selected_operations']} are selected. "
            f"The {summary['rest_excluded_operations']} explicitly excluded operations remain in "
            "the ledger. [Coverage policy](../../generation/coverage-policy.json) records the "
            "user-selected scope and operation decisions; raw access does not count as semantic selection.",
            "",
        ]
        keys = coverage_audit.get("contract_keys", {})
        for product, value in keys.get("rest", {}).get("products", {}).items():
            counts = value["summary"]
            measured.extend(
                [
                    f"For `{product}`, {counts['in_scope_public_response_properties']} of "
                    f"{counts['in_scope_response_properties']} in-scope named response-property "
                    "declarations are projected into public entity fields. Shared declarations count "
                    "once; dynamic map keys are unenumerated. "
                    f"{counts['in_scope_bound_parameters']} of {counts['in_scope_parameters']} "
                    "operation parameters are bound, including literal and runtime pagination bindings. "
                    "A binding does not imply that every allowed parameter value is supported.",
                    "",
                ]
            )
        graph = keys.get("graphql", {}).get("summary")
        if graph:
            measured.extend(
                [
                    f"GraphQL queries fetch {graph['in_scope_fetched_fields']} of "
                    f"{graph['in_scope_read_fields']} in-scope read-field coordinates; "
                    f"{graph['in_scope_public_fields']} are projected into public fields. "
                    f"The policy explicitly excludes {graph['excluded_fields']} coordinates from the "
                    f"{graph['read_fields']} raw total. Raw measurements remain "
                    f"{graph['fetched_fields']} fetched and {graph['public_fields']} publicly projected "
                    "coordinates, including any excluded fields. Exclusions name exact owning types "
                    "or fields and do not remove shared user, repository or actor fields transitively.",
                    "",
                    f"GraphQL queries bind {graph['in_scope_bound_arguments']} of "
                    f"{graph['in_scope_declared_arguments']} in-scope field arguments; raw totals are "
                    f"{graph['bound_arguments']} bound of {graph['declared_arguments']} declared, with "
                    f"{graph['excluded_declared_arguments']} declared arguments excluded by their "
                    "owning field's scope. Fetching requires an actual query selection; public exposure "
                    "also requires a typed entity projection. Business information available through "
                    "REST and fields merely present in the selected schema do not increase these "
                    "GraphQL measurements. These measurements do not establish live endpoint "
                    "qualification or business-domain completeness.",
                    "",
                ]
            )
        for operation_id, decision in (
            coverage_audit.get("coverage_policy", {}).get("operation_decisions", {}).items()
        ):
            measured.extend([f"`{operation_id}`: {decision['reason']}", ""])
        for entity, limitation in (
            coverage_audit.get("coverage_policy", {}).get("entity_limitations", {}).items()
        ):
            measured.extend([f"`{entity}`: {limitation}", ""])
        lines[7:7] = measured
    return "\n".join(lines) + "\n"


def emit_artifacts(
    contract, overlay, provenance, *, api_inventory=None, selected_sdl=None, coverage_policy=None
):
    model, reports = build_model(contract, overlay)
    raw = json_text(model)
    documents = {"github-generated.crossfield.json": raw}
    package = {
        "format": "crossfield.package",
        "version": 2,
        "package_id": str(NAMESPACE),
        "revision": 11,
        "entrypoint": "github-generated.crossfield.json",
        "comment": model["comment"],
        "tags": {"owner": "Query Farm", "scope": "connected generation pilot"},
        "documents": [
            {"path": path, "content": content, "sha256": hashlib.sha256(content.encode()).hexdigest()}
            for path, content in documents.items()
        ],
        "reports": reports,
        "capabilities": {
            "engine_source_sha": ENGINE,
            "semantic_contract": {"min": 1, "max": 1},
            "parser_profile": "crossfield_builtin_v1",
            "lifecycle_min": 3,
        },
        "approval": {
            "authority": model["id"],
            "reference": "generation/pilot.json; independent native SQL tests",
        },
        "tag_metadata": {},
        "checks": [],
    }
    coverage = {
        "format": "vgi-github-generation-coverage",
        "version": 1,
        "scope": "connected pilot",
        "complete_worker_replacement": False,
        "sources": [entity["name"] for entity in contract["entities"]],
        "entities": [
            {
                "name": entity["name"],
                "metrics": [name for name, _ in _metric_inventory(entity)],
                "detail_relation": "detail." + entity["name"],
                "grain": entity["grain"],
            }
            for entity in contract["functions"]
        ],
        "relationships": contract["relationships"],
        "scopes": contract["scopes"],
        "provenance": provenance,
        "native_crossfield": {
            "metrics": list(overlay.get("crossfield", {}).get("metrics", {})),
            "derived_datasets": list(
                overlay.get("crossfield", {}).get("invocations", {}).get("derived_datasets", {})
            ),
        },
    }
    if api_inventory is not None:
        coverage["api_audit"] = audit_coverage(
            contract,
            api_inventory,
            selected_sdl,
            overlay.get("crossfield", {}).get("invocations", {}).get("derived_datasets", {}),
            policy=coverage_policy,
        )
    schemas = {
        "format": "vgi-github-generated-source-schemas",
        "version": 1,
        "entities": [
            {
                "name": entity["name"],
                "arguments": entity["arguments"],
                "columns": entity["columns"],
                "grain": entity["grain"],
            }
            for entity in contract["entities"]
        ],
    }
    return {
        "vgi_github/generated_entities.json": json_text({**contract, "provenance": provenance}),
        **research_artifacts(),
        **{"models/generated-pilot/" + path: content for path, content in documents.items()},
        "models/generated-pilot/github-generated.package.json": json_text(package),
        "models/generated-pilot/reports.json": json_text(reports),
        "models/generated-pilot/source_schemas.json": json_text(schemas),
        "models/generated-pilot/coverage.json": json_text(coverage),
        "models/generated-pilot/README.md": documentation(contract, overlay, coverage.get("api_audit")),
    }
