"""Inventory the complete pinned read API and measure selected-model coverage.

Schema navigation is evidence of an available API field, never approval of a
semantic relationship, identity, population, or executable retrieval route.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy

from graphql import (
    build_schema,
    get_named_type,
    is_interface_type,
    is_list_type,
    is_non_null_type,
    is_object_type,
    is_union_type,
    parse,
    validate_schema,
)
from graphql.validation.validate import validate_sdl

from vgi_github.generation.coverage_keys import (
    audit_contract_keys,
    graphql_exclusions,
    reachable_source_names,
)


def _collection(kind):
    return is_list_type(kind.of_type if is_non_null_type(kind) else kind)


def graphql_inventory(sdl):
    """Walk each query-reachable type once, including interface/union branches.

    Store field coordinates rather than enumerating infinitely many paths through
    recursive types. Preserve upstream SDL errors instead of hiding them behind
    the selected schema's successful validation.
    """
    document = parse(sdl)
    diagnostics = sorted({error.message for error in validate_sdl(document)})
    schema = build_schema(sdl, assume_valid_sdl=True)
    diagnostics = sorted(set(diagnostics) | {error.message for error in validate_schema(schema)})
    if schema.query_type is None:
        raise ValueError("Full GraphQL schema has no query root")
    pending = deque([(schema.query_type, [])])
    reached, fields, types = set(), [], []
    while pending:
        parent, path = pending.popleft()
        if parent.name in reached:
            continue
        reached.add(parent.name)
        variants = []
        if is_union_type(parent):
            variants = list(parent.types)
        elif is_interface_type(parent):
            variants = list(schema.get_possible_types(parent))
        types.append(
            {
                "name": parent.name,
                "example_path": path,
                "possible_types": sorted(kind.name for kind in variants),
            }
        )
        pending.extend((kind, [*path, "... on " + kind.name]) for kind in variants)
        for name, field in sorted(getattr(parent, "fields", {}).items()):
            target = get_named_type(field.type)
            composite = is_object_type(target) or is_interface_type(target) or is_union_type(target)
            item = target
            connection_path = []
            # Only unwrap a connection when its schema supplies the item path.
            if composite and target.name.endswith("Connection"):
                if "nodes" in getattr(target, "fields", {}):
                    item = get_named_type(target.fields["nodes"].type)
                    connection_path = ["nodes"]
                elif "edges" in getattr(target, "fields", {}):
                    edge = get_named_type(target.fields["edges"].type)
                    if "node" in getattr(edge, "fields", {}):
                        item = get_named_type(edge.fields["node"].type)
                        connection_path = ["edges", "node"]
            row = {
                "coordinate": parent.name + "." + name,
                "return_type": str(field.type),
                "named_type": target.name,
                "arguments": {key: str(value.type) for key, value in sorted(field.args.items())},
                "deprecated": field.deprecation_reason is not None,
                "navigation": composite,
            }
            if composite:
                row.update(
                    target_type=item.name,
                    collection=bool(connection_path) or _collection(field.type),
                    connection_path=connection_path,
                )
                pending.append((target, [*path, name]))
            fields.append(row)
    by_parent = {}
    alternatives = {row["name"]: row["possible_types"] for row in types}
    for row in fields:
        if row["navigation"]:
            by_parent.setdefault(row["coordinate"].split(".")[0], []).append(row)
    for row in fields:
        if not row["navigation"]:
            continue
        parent = row["coordinate"].split(".")[0]
        origins = set(alternatives.get(parent) or [parent])
        targets = alternatives.get(row["target_type"]) or [row["target_type"]]
        row["opposite_direction_candidates"] = sorted(
            {
                other["coordinate"]
                for target in targets
                for other in by_parent.get(target, [])
                if origins.intersection(alternatives.get(other["target_type"]) or [other["target_type"]])
            }
        )
    return {
        "query_root": schema.query_type.name,
        "excluded_roots": [
            root.name for root in (schema.mutation_type, schema.subscription_type) if root is not None
        ],
        "schema_diagnostics": diagnostics,
        "types": sorted(types, key=lambda row: row["name"]),
        "fields": sorted(fields, key=lambda row: row["coordinate"]),
    }


def rest_response_shapes(spec):
    """Record declared response roots and top-level collections, without guessing entities."""

    def resolve(value):
        seen = set()
        while "$ref" in value:
            ref = value["$ref"]
            if not ref.startswith("#/") or ref in seen:
                raise ValueError(f"Unresolvable REST response shape: {ref}")
            seen.add(ref)
            value = spec
            for part in ref[2:].split("/"):
                value = value[part.replace("~1", "/").replace("~0", "~")]
        return value

    def shape(raw):
        value = resolve(raw)
        result = {key: value[key] for key in ("type", "format", "nullable") if key in value}
        if "$ref" in raw:
            result["schema_ref"] = raw["$ref"]
        if "items" in value:
            item = resolve(value["items"])
            result["items"] = {key: item[key] for key in ("type", "format") if key in item}
            if "$ref" in value["items"]:
                result["items"]["schema_ref"] = value["items"]["$ref"]
        for keyword in ("oneOf", "anyOf", "allOf"):
            if keyword in value:
                # Keep exact alternatives, rather than choosing one business type.
                result[keyword] = [
                    {key: member[key] for key in ("$ref", "type", "format") if key in member}
                    for member in value[keyword]
                ]
        return result

    operations = {}
    for item in spec["paths"].values():
        if "get" not in item:
            continue
        operation = item["get"]
        responses = []
        for status, raw in sorted(operation.get("responses", {}).items()):
            if not str(status).startswith("2"):
                continue
            response = resolve(raw)
            if not response.get("content"):
                responses.append({"status": status, "body": "none"})
            for media, content in sorted(response.get("content", {}).items()):
                schema = content.get("schema", {})
                value = resolve(schema)
                collections = {
                    name: shape(member)
                    for name, member in sorted(value.get("properties", {}).items())
                    if resolve(member).get("type") == "array"
                }
                responses.append(
                    {"status": status, "media_type": media, "root": shape(schema), "collections": collections}
                )
        operations[operation["operationId"]] = responses
    return operations


def api_inventory(manifest, sdl, rest_method_counts, response_shapes=None):
    """The REST manifest is already checked against BOTH complete OpenAPI files."""
    return {
        "format": "vgi-github-api-inventory",
        "version": 1,
        "rest_revision": manifest["revision"],
        "rest": {
            "sources": deepcopy(manifest["sources"]),
            "method_counts": rest_method_counts,
            "operations": [
                {
                    key: deepcopy(operation[key])
                    for key in (
                        "operation_id",
                        "path",
                        "category",
                        "products",
                        "deprecated",
                        "parameters",
                        "response_schema_sha256",
                        "documentation_url",
                    )
                }
                | {
                    "parameters_by_product": deepcopy(operation.get("parameters_by_product", {})),
                    "response_shapes_by_product": {
                        product: deepcopy(shapes[operation["operation_id"]])
                        for product, shapes in (response_shapes or {}).items()
                        if product in operation["products"]
                    },
                }
                for operation in manifest["operations"]
            ],
        },
        "graphql": graphql_inventory(sdl),
    }


def _source_names(value):
    """Resolve only declared source leaves; never infer them from field names."""
    found = set()
    if isinstance(value, dict):
        if "entity" in value:
            found.add(value["entity"])
        for child in value.values():
            found.update(_source_names(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_source_names(child))
    return found


def audit_coverage(contract, inventory, selected_sdl, derived_datasets=None, *, policy=None):
    """Return coverage gaps as gaps, without claiming they passed execution."""
    reachable = reachable_source_names(contract)
    sources = {source["name"]: source for source in contract["entities"] if source["name"] in reachable}
    functions = {function["name"]: function for function in contract["functions"]}
    policy = policy or {}
    excluded = policy.get("excluded_rest_categories", {})
    excluded_operations = policy.get("excluded_rest_operations", {})
    excluded_graphql = graphql_exclusions(
        inventory["graphql"], policy.get("excluded_graphql_types"), policy.get("excluded_graphql_fields")
    )
    decisions = policy.get("operation_decisions", {})
    known_operations = {row["operation_id"] for row in inventory["rest"]["operations"]}
    known_categories = {row["category"] for row in inventory["rest"]["operations"]}
    if set(excluded) - known_categories or any(
        not isinstance(value, str) or not value.strip() for value in excluded.values()
    ):
        raise ValueError("Coverage exclusions require known REST categories and explicit reasons")
    if set(excluded_operations) - known_operations or any(
        not isinstance(value, str) or not value.strip() for value in excluded_operations.values()
    ):
        raise ValueError("Coverage operation exclusions require known REST operations and explicit reasons")
    if set(decisions) - known_operations:
        raise ValueError("Coverage decisions must name known REST operations")
    for decision in decisions.values():
        if decision.get("status") != "intentionally_unselected" or not decision.get("reason"):
            raise ValueError("Unselected operation decisions require a status and reason")
        if set(decision.get("alternative_entities", [])) - functions.keys():
            raise ValueError("Coverage alternatives must name implemented entities")
    rest_selected, graphql_selected = {}, {}
    graphql_fields = {row["coordinate"]: row for row in inventory["graphql"]["fields"]}
    for name, source in sources.items():
        transport = source["transport"]
        if transport["kind"] == "rest":
            key = transport["operation_id"], transport["product"]
            rest_selected.setdefault(key, []).append(name)
        else:
            parent = inventory["graphql"]["query_root"]
            for field in source["source"]["field_path"]:
                coordinate = parent + "." + field
                if coordinate not in graphql_fields:
                    raise ValueError(f"Selected GraphQL path is absent from full inventory: {coordinate}")
                graphql_selected.setdefault(coordinate, []).append(name)
                parent = (
                    source["source"]
                    .get("field_types", {})
                    .get(field, graphql_fields[coordinate]["named_type"])
                )
    rest = []
    seen_rest = set()
    for operation in inventory["rest"]["operations"]:
        selected = {}
        for product in operation["products"]:
            key = operation["operation_id"], product
            seen_rest.add(key)
            selected[product] = sorted(rest_selected.get(key, []))
        rest.append(
            {key: deepcopy(operation[key]) for key in ("operation_id", "path", "category", "products")}
            | {
                "selected_sources_by_product": selected,
                "response_shapes_by_product": operation["response_shapes_by_product"],
                "implementation_scope": "excluded"
                if operation["category"] in excluded or operation["operation_id"] in excluded_operations
                else "included",
                "exclusion_reason": excluded_operations.get(
                    operation["operation_id"], excluded.get(operation["category"])
                ),
                "selection_status": "selected"
                if any(selected.values())
                else decisions.get(operation["operation_id"], {}).get("status", "unselected"),
                "decision": deepcopy(decisions.get(operation["operation_id"])),
            }
        )
    if set(rest_selected) - seen_rest:
        raise ValueError("Selected REST operations are absent from full inventory")
    selected_schema = build_schema(selected_sdl)
    selected_fields = {
        parent.name + "." + name
        for parent in selected_schema.type_map.values()
        if not parent.name.startswith("__") and (is_object_type(parent) or is_interface_type(parent))
        for name in parent.fields
    }
    if selected_fields - graphql_fields.keys():
        raise ValueError("Selected GraphQL fields are absent from query-reachable full inventory")
    for coordinate in selected_fields:
        parent, name = coordinate.split(".")
        field = selected_schema.get_type(parent).fields[name]
        full = graphql_fields[coordinate]
        if (
            str(field.type) != full["return_type"]
            or {key: str(value.type) for key, value in field.args.items()} != full["arguments"]
        ):
            raise ValueError(f"Selected GraphQL signature differs from full inventory: {coordinate}")
    graphql = [
        deepcopy(row)
        | {
            "selected_sources": sorted(set(graphql_selected.get(row["coordinate"], []))),
            "in_selected_schema": row["coordinate"] in selected_fields,
            "implementation_scope": "excluded" if row["coordinate"] in excluded_graphql else "included",
            "exclusion_reason": excluded_graphql.get(row["coordinate"]),
        }
        for row in inventory["graphql"]["fields"]
    ]
    routes = []
    for name, function in sorted(functions.items()):
        for route in function.get("routes", [function]):
            stages = []
            for stage in route["traversal"]["stages"]:
                definition = contract["scopes"][stage["scope"]] if "scope" in stage else stage
                stages.append(
                    {
                        "name": stage["name"],
                        "sources": sorted(_source_names(definition)),
                        "bindings": deepcopy(definition),
                    }
                )
            routes.append(
                {
                    "entity": name,
                    "route": route["name"],
                    "parameters": [argument["name"] for argument in route["arguments"]],
                    "grain": function["grain"],
                    "selection": deepcopy(route.get("selection", [])),
                    **(
                        {"select_values": deepcopy(route["select_values"])}
                        if "select_values" in route
                        else {}
                    ),
                    **({"default": True} if route.get("default") else {}),
                    "population": route.get("population", function.get("description", "")),
                    "stages": stages,
                }
            )
    # A relationship is an analytical join declaration. Report each direction's
    # actual selectable inputs; the existence of an API field is not a binding.
    relationships = []
    for relation in contract["relationships"]:
        relationships.append(
            {
                "name": relation["name"],
                "from": relation["from"],
                "to": relation["to"],
                "analytical": relation.get("analytical", True),
                "retrieval_route_binding": "declared" if relation.get("retrievals") else "not_declared",
                "directions": [
                    {
                        "from": start,
                        "to": target,
                        "target_routes": [row["route"] for row in routes if row["entity"] == target],
                        "target_parameters": sorted(
                            {arg for row in routes if row["entity"] == target for arg in row["parameters"]}
                        ),
                        "retrievals": [
                            deepcopy(item)
                            for item in relation.get("retrievals", [])
                            if item["direction"] == direction
                        ],
                    }
                    for direction, start, target in (
                        ("forward", relation["from"], relation["to"]),
                        ("reverse", relation["to"], relation["from"]),
                    )
                ],
            }
        )
    categories = []
    for category in sorted({row["category"] for row in rest}):
        rows = [row for row in rest if row["category"] == category]
        selected = sum(any(row["selected_sources_by_product"].values()) for row in rows)
        categories.append(
            {
                "category": category,
                "operations": len(rows),
                "selected_operations": selected,
                "in_scope_operations": sum(row["implementation_scope"] == "included" for row in rows),
                "implementation_scope": "excluded"
                if all(row["implementation_scope"] == "excluded" for row in rows)
                else "partial"
                if any(row["implementation_scope"] == "excluded" for row in rows)
                else "included",
            }
        )
    navigation = [row for row in graphql if row["navigation"]]
    derived = [
        {
            "name": name,
            "from": definition["from"],
            "grain": definition["dataset"]["grain"],
            "operation": "expand" if "expand" in definition else "semantic_query",
        }
        for name, definition in sorted((derived_datasets or {}).items())
    ]
    in_scope = [row for row in rest if row["implementation_scope"] == "included"]
    selected_ids = {row["operation_id"] for row in rest if any(row["selected_sources_by_product"].values())}
    milestones = {}
    for name, milestone in policy.get("milestones", {}).items():
        ids = milestone["operation_ids"]
        if len(ids) != len(set(ids)) or set(ids) - known_operations:
            raise ValueError("Coverage milestones require distinct known operation IDs")
        milestones[name] = {
            "target_operations": len(ids),
            "selected_operations": len(set(ids) & selected_ids),
            "intentionally_unselected_operations": sorted(set(ids) & decisions.keys() - selected_ids),
            "remaining_operations": sorted(set(ids) - selected_ids - decisions.keys()),
            "operation_ids": sorted(ids),
        }
    return {
        "scope": "All pinned REST GET operations for both products and all query-reachable GraphQL fields",
        "validation": "schema inventory and declared-route comparison; no live endpoint execution",
        "semantic_coverage_complete": False,
        "coverage_policy": deepcopy(policy),
        "milestones": milestones,
        "contract_keys": audit_contract_keys(
            contract,
            inventory,
            excluded,
            excluded_operations,
            excluded_graphql_types=policy.get("excluded_graphql_types"),
            excluded_graphql_fields=policy.get("excluded_graphql_fields"),
        ),
        "summary": {
            "rest_operations": len(rest),
            "rest_categories": len(categories),
            "rest_selected_operations": sum(any(row["selected_sources_by_product"].values()) for row in rest),
            "rest_in_scope_operations": len(in_scope),
            "rest_excluded_operations": len(rest) - len(in_scope),
            "rest_in_scope_selected_operations": sum(
                any(row["selected_sources_by_product"].values()) for row in in_scope
            ),
            "graphql_query_roots": sum(
                row["coordinate"].startswith(inventory["graphql"]["query_root"] + ".") for row in graphql
            ),
            "graphql_read_types": len(inventory["graphql"]["types"]),
            "graphql_read_fields": len(graphql),
            "graphql_excluded_fields": len(excluded_graphql),
            "graphql_in_scope_read_fields": len(graphql) - len(excluded_graphql),
            "graphql_selected_schema_fields": len(selected_fields),
            "graphql_in_scope_selected_schema_fields": len(selected_fields - excluded_graphql.keys()),
            "graphql_excluded_selected_schema_fields": len(selected_fields & excluded_graphql.keys()),
            "graphql_navigation_fields": len(navigation),
            "graphql_in_scope_navigation_fields": sum(
                row["implementation_scope"] == "included" for row in navigation
            ),
            "graphql_navigation_fields_with_opposite_candidates": sum(
                bool(row["opposite_direction_candidates"]) for row in navigation
            ),
            "graphql_source_path_fields": len(graphql_selected),
            "graphql_in_scope_source_path_fields": len(graphql_selected.keys() - excluded_graphql.keys()),
            "entities": len(functions),
            "derived_datasets": len(derived),
            "routes": len(routes),
            "relationships": len(relationships),
            "analytical_relationships": sum(row["analytical"] for row in relationships),
        },
        "rest_categories": categories,
        "rest_operations": rest,
        "excluded_rest_methods": inventory["rest"]["method_counts"],
        "graphql_schema_diagnostics": inventory["graphql"]["schema_diagnostics"],
        "graphql_excluded_roots": inventory["graphql"]["excluded_roots"],
        "graphql_fields": graphql,
        "entity_routes": routes,
        "derived_datasets": derived,
        "relationship_directions": relationships,
    }
