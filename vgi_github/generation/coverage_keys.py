"""Measure declared read-contract keys without equating fetching with exposure.

REST identities are product plus a canonical JSON pointer to a named property
*declaration*. Recursive paths therefore do not create an infinite denominator.
Properties reached through shared response types are counted once per product.
Dynamic additional-property names cannot be enumerated and are reported separately.
"""

from __future__ import annotations

from collections import defaultdict

from graphql import parse

DENOMINATOR = (
    "Unique canonical named JSON-schema property declarations reachable from GET "
    "2xx/3xx response schemas, per product. Shared declarations count once; "
    "recursive paths do not multiply keys. Dynamic map keys are unenumerated. "
    "Mapped properties require typed physical columns; path navigation alone is "
    "reported separately. Pagination total-count validation is control coverage, "
    "not a typed entity mapping. Public properties require a public route projection."
    " Selected mappings and bindings require a source reachable from an exported function."
)


def _escape(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def _lookup(document, pointer):
    if not pointer.startswith("#/"):
        raise ValueError(f"Contract key inventory requires local references: {pointer}")
    value = document
    for part in pointer[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def rest_contract_keys(spec):
    """Build a compact, cycle-safe graph from the complete pinned OpenAPI file."""
    nodes, operations = {}, {}

    def canonical(pointer):
        seen = set()
        while pointer not in seen:
            seen.add(pointer)
            value = _lookup(spec, pointer)
            if not isinstance(value, dict) or "$ref" not in value:
                return pointer
            pointer = value["$ref"]
        # Alias-only cycles are unusual but finite and retain a deterministic key.
        return min(seen)

    def schema(pointer):
        pointer = canonical(pointer)
        if pointer in nodes:
            return pointer
        value = _lookup(spec, pointer)
        result = {}
        nodes[pointer] = result
        if not isinstance(value, dict):
            result["boolean_schema"] = bool(value)
            return pointer
        result.update({key: value[key] for key in ("type", "format", "nullable") if key in value})
        if "$ref" in value:
            result["alias"] = canonical(value["$ref"])
        if "properties" in value:
            result["properties"] = {
                name: schema(pointer + "/properties/" + _escape(name)) for name in sorted(value["properties"])
            }
            result["required"] = sorted(value.get("required", []))
        if "items" in value:
            result["items"] = schema(pointer + "/items")
        for keyword in ("oneOf", "anyOf", "allOf"):
            if keyword in value:
                result[keyword] = [
                    schema(pointer + f"/{keyword}/{index}") for index in range(len(value[keyword]))
                ]
        if "additionalProperties" in value:
            additional = value["additionalProperties"]
            result["additional_properties"] = (
                additional if isinstance(additional, bool) else schema(pointer + "/additionalProperties")
            )
        return pointer

    for path, item in sorted(spec.get("paths", {}).items()):
        if "get" not in item:
            continue
        operation = item["get"]
        prefix = "#/paths/" + _escape(path)
        parameters = {}
        for parent, location in ((item, prefix), (operation, prefix + "/get")):
            for index, _raw in enumerate(parent.get("parameters", [])):
                pointer = canonical(location + f"/parameters/{index}")
                value = _lookup(spec, pointer)
                parameters[(value["in"], value["name"])] = {
                    "in": value["in"],
                    "name": value["name"],
                    "required": bool(value.get("required", False)),
                    **({"schema_pointer": schema(pointer + "/schema")} if "schema" in value else {}),
                }
        responses = []
        for status in sorted(operation.get("responses", {})):
            if str(status)[:1] not in {"2", "3"}:
                continue
            pointer = canonical(prefix + "/get/responses/" + _escape(status))
            response = _lookup(spec, pointer)
            if not response.get("content"):
                responses.append({"status": str(status), "body": "none"})
            for media, content in sorted(response.get("content", {}).items()):
                row = {"status": str(status), "media_type": media, "body": "unspecified"}
                if "schema" in content:
                    row.update(
                        body="schema",
                        schema_pointer=schema(pointer + "/content/" + _escape(media) + "/schema"),
                    )
                responses.append(row)
        identity = operation["operationId"]
        operations[identity] = {
            "category": operation.get("tags", [identity.split("/")[0]])[0],
            "path": path,
            "parameters": [parameters[key] for key in sorted(parameters)],
            "responses": responses,
        }
    return {
        "version": 1,
        "denominator": DENOMINATOR,
        "nodes": dict(sorted(nodes.items())),
        "operations": operations,
    }


def _reachable(nodes, roots):
    visited, properties, maps = set(), set(), set()
    pending = list(roots)
    while pending:
        pointer = pending.pop()
        if pointer in visited:
            continue
        visited.add(pointer)
        node = nodes[pointer]
        for name, target in node.get("properties", {}).items():
            properties.add(pointer + "/properties/" + _escape(name))
            pending.append(target)
        for keyword in ("oneOf", "anyOf", "allOf"):
            pending.extend(node.get(keyword, []))
        if "items" in node:
            pending.append(node["items"])
        additional = node.get("additional_properties")
        if additional:
            maps.add(pointer)
            if isinstance(additional, str):
                pending.append(additional)
    return properties, maps


def _property(nodes, roots, name):
    """Find one declared property through arrays and exact variant branches."""
    found, seen = [], set()
    pending = list(roots)
    while pending:
        pointer = pending.pop()
        if pointer in seen:
            continue
        seen.add(pointer)
        node = nodes[pointer]
        if name in node.get("properties", {}):
            found.append((pointer + "/properties/" + _escape(name), node["properties"][name]))
        if "items" in node:
            pending.append(node["items"])
        for keyword in ("oneOf", "anyOf", "allOf"):
            pending.extend(node.get(keyword, []))
    return found


def _typed_descendants(descriptor, path=(), conditions=()):
    if "variant" in descriptor:
        for field in descriptor["fields"]:
            if field["name"] in descriptor["variant"]["names"]:
                branch = (*conditions, (path, field["name"]))
                yield from _typed_descendants(field["schema"], path, branch)
    elif descriptor.get("kind") == "list":
        yield from _typed_descendants(descriptor["item"], path, conditions)
    elif descriptor.get("kind") == "struct":
        for field in descriptor["fields"]:
            child = (*path, field["name"])
            yield child, field["schema"], conditions
            yield from _typed_descendants(field["schema"], child, conditions)


def _dictionary_values(nodes, roots):
    found, pending, seen = [], list(roots), set()
    while pending:
        pointer = pending.pop()
        if pointer in seen:
            continue
        seen.add(pointer)
        node = nodes[pointer]
        additional = node.get("additional_properties")
        if isinstance(additional, str):
            found.append((pointer, additional))
        if "items" in node:
            pending.append(node["items"])
        for keyword in ("oneOf", "anyOf", "allOf"):
            pending.extend(node.get(keyword, []))
    return found


def _projection_schema(schema, path):
    if not path:
        return schema
    field = next((field for field in schema.get("fields", []) if field["name"] == path[0]), None)
    if schema["kind"] != "struct" or field is None:
        raise ValueError("Public projection must select a declared STRUCT member")
    return {**schema, "fields": [{**field, "schema": _projection_schema(field["schema"], path[1:])}]}


def _map_rest_column(nodes, roots, result_path, column, projection_path=()):
    if "path" not in column and "source_entry" not in column and "source_document_path" not in column:
        return set(), set(), set()
    navigation, mapped, maps = set(), set(), set()
    if "source_document_path" in column:
        path = column["source_document_path"]
    elif "source_entry" in column:
        for name in result_path:
            pairs = _property(nodes, roots, name)
            if not pairs:
                raise ValueError(f"Selected REST dictionary is absent from inventory: {result_path}")
            navigation.update(pair[0] for pair in pairs)
            roots = {pair[1] for pair in pairs}
        dictionaries = _dictionary_values(nodes, roots)
        if not dictionaries:
            raise ValueError("Selected REST dictionary value is absent from inventory")
        if column["source_entry"] == "key":
            return mapped, navigation, maps
        maps.update(pair[0] for pair in dictionaries)
        roots = {pair[1] for pair in dictionaries}
        path = column.get("path", [])
    else:
        path = [*result_path, *column["path"]]
    for index, name in enumerate(path):
        pairs = _property(nodes, roots, name)
        if not pairs:
            raise ValueError(f"Selected REST property is absent from inventory: {column['name']} {path}")
        keys, roots = {pair[0] for pair in pairs}, {pair[1] for pair in pairs}
        (mapped if index == len(path) - 1 else navigation).update(keys)

    def variant_roots(targets, index):
        selected, pending, seen = set(), list(targets), set()
        while pending:
            pointer = pending.pop()
            if pointer in seen:
                continue
            seen.add(pointer)
            node = nodes[pointer]
            alternatives = node.get("oneOf", node.get("anyOf"))
            if alternatives is not None:
                if index >= len(alternatives):
                    raise ValueError("Typed variant is absent from the response schema inventory")
                selected.add(alternatives[index])
            elif "items" in node:
                pending.append(node["items"])
        return selected

    def descendants(targets, descriptor):
        if "variant" in descriptor:
            fields = {field["name"]: field["schema"] for field in descriptor["fields"]}
            for index, name in enumerate(descriptor["variant"]["names"]):
                if name not in fields:
                    continue
                selected = variant_roots(targets, index)
                if not selected:
                    raise ValueError("Typed variant is absent from the response schema inventory")
                descendants(selected, fields[name])
        elif descriptor.get("kind") == "list":
            descendants(targets, descriptor["item"])
        elif descriptor.get("kind") == "map":
            dictionaries = _dictionary_values(nodes, targets)
            if not dictionaries:
                raise ValueError("Typed REST map is absent from the response schema inventory")
            maps.update(pair[0] for pair in dictionaries)
            descendants({pair[1] for pair in dictionaries}, descriptor["value"])
        elif descriptor.get("kind") == "struct":
            for field in descriptor["fields"]:
                pairs = _property(nodes, targets, field["name"])
                if not pairs:
                    raise ValueError(
                        f"Selected nested REST property is absent from inventory: {field['name']}"
                    )
                mapped.update(pair[0] for pair in pairs)
                descendants({pair[1] for pair in pairs}, field["schema"])

    descendants(roots, _projection_schema(column["schema"], projection_path))
    return mapped, navigation, maps


def _entities(value):
    found = set()
    if isinstance(value, dict):
        if "entity" in value:
            found.add(value["entity"])
        for child in value.values():
            found.update(_entities(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_entities(child))
    return found


def reachable_source_names(contract):
    """Follow exported function plans and only the reusable scopes they reference."""
    if "functions" not in contract:
        # The runtime directly exports physical entities for a source-only contract.
        return {source["name"] for source in contract.get("entities", [])}
    reached, scopes = set(), set()

    def visit(value):
        if isinstance(value, dict):
            if "entity" in value:
                reached.add(value["entity"])
            if "scope" in value and value["scope"] not in scopes:
                scopes.add(value["scope"])
                visit(contract.get("scopes", {})[value["scope"]])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for function in contract["functions"]:
        visit(function.get("filters", []))
        for route in function.get("routes", [function]):
            visit(route.get("traversal", {}))
            visit(route.get("cohort", {}))
    return reached


def _exposures(contract):
    exposed = defaultdict(set)
    for function in contract.get("functions", []):
        for route in function.get("routes", [function]):
            stages = {}
            for stage in route.get("traversal", {}).get("stages", []):
                sources = _entities(stage)
                if "scope" in stage:
                    sources.update(_entities(contract.get("scopes", {})[stage["scope"]]))
                stages[stage["name"]] = sources
            for column in route.get("columns", []):
                for source in stages.get(column.get("source_stage"), []):
                    exposed[(source, column["source_column"])].add(
                        (function["name"] + "." + column["name"], tuple(column.get("source_path", [])))
                    )
    return exposed


def _graphql_query_fields(source, inventory):
    fields = {row["coordinate"]: row for row in inventory["fields"]}
    document = parse(source["transport"]["document"])
    fragments = {node.name.value: node for node in document.definitions if node.kind == "fragment_definition"}
    by_path, fetched, arguments = defaultdict(set), set(), set()

    def visit(selection, parent, path, active=(), conditions=()):
        for node in selection.selections:
            if node.kind == "inline_fragment":
                visit(
                    node.selection_set,
                    node.type_condition.name.value if node.type_condition else parent,
                    path,
                    active,
                    (*conditions, (path, node.type_condition.name.value))
                    if node.type_condition
                    else conditions,
                )
            elif node.kind == "fragment_spread":
                if node.name.value in active:
                    raise ValueError("A fetched GraphQL document contains a fragment cycle")
                fragment = fragments[node.name.value]
                visit(
                    fragment.selection_set,
                    fragment.type_condition.name.value,
                    path,
                    (*active, node.name.value),
                    (*conditions, (path, fragment.type_condition.name.value)),
                )
            else:
                coordinate = parent + "." + node.name.value
                wire_name = node.alias.value if node.alias else node.name.value
                name = source["transport"].get("response_aliases", {}).get(wire_name, wire_name)
                key = (*path, name)
                if node.name.value == "__typename":
                    by_path[key].add((None, conditions))
                    continue
                if coordinate not in fields:
                    raise ValueError(f"Fetched GraphQL field is absent from inventory: {coordinate}")
                fetched.add(coordinate)
                by_path[key].add((coordinate, conditions))
                arguments.update(coordinate + "(" + arg.name.value + ")" for arg in node.arguments)
                if node.selection_set:
                    visit(node.selection_set, fields[coordinate]["named_type"], key, active, conditions)

    for node in document.definitions:
        if node.kind == "operation_definition":
            visit(node.selection_set, inventory["query_root"], ())
    return by_path, fetched, arguments


def _graphql_coordinates(by_path, path, constraints):
    return {
        coordinate
        for coordinate, conditions in by_path[path]
        if all(dict(conditions).get(parent) in types for parent, types in constraints.items())
    }


def graphql_exclusions(inventory, excluded_types=None, excluded_fields=None):
    """Resolve exact owner-type and field exclusions without traversing return types."""
    fields = {row["coordinate"] for row in inventory.get("fields", [])}
    types = {row["name"] for row in inventory.get("types", [])}
    excluded_types = {} if excluded_types is None else excluded_types
    excluded_fields = {} if excluded_fields is None else excluded_fields
    for kind, exclusions, known in (
        ("type", excluded_types, types),
        ("field", excluded_fields, fields),
    ):
        if (
            not isinstance(exclusions, dict)
            or set(exclusions) - known
            or any(not isinstance(reason, str) or not reason.strip() for reason in exclusions.values())
        ):
            raise ValueError(f"GraphQL {kind} exclusions require known exact names and explicit reasons")
    return {
        coordinate: excluded_fields.get(coordinate, excluded_types.get(coordinate.split(".")[0]))
        for coordinate in sorted(fields)
        if coordinate in excluded_fields or coordinate.split(".")[0] in excluded_types
    }


def audit_contract_keys(
    contract,
    inventory,
    excluded_categories=(),
    excluded_operations=(),
    *,
    excluded_graphql_types=None,
    excluded_graphql_fields=None,
):
    """Measure physical selections and public projections against full key graphs."""
    exposed = _exposures(contract)
    compiled = contract.get("entities", [])
    reachable = reachable_source_names(contract)
    sources = [source for source in compiled if source["name"] in reachable]
    result = {
        "rest": {"denominator": DENOMINATOR, "products": {}},
        "graphql": {},
        "source_reachability": {
            "compiled_sources": len(compiled),
            "reachable_sources": len(sources),
            "unreachable_sources": sorted(
                source["name"] for source in compiled if source["name"] not in reachable
            ),
            "basis": (
                "Only sources reachable from exported function plans and their referenced scopes "
                "contribute to selected, mapped, fetched or bound coverage. The compiled source "
                "inventory is retained, including unreachable sources."
            ),
        },
    }
    for product, graph in sorted(inventory.get("rest", {}).get("contract_keys_by_product", {}).items()):
        nodes, operations = graph["nodes"], graph["operations"]
        operation_rows, columns, controls = {}, [], []
        all_roots, scoped_roots = [], []
        all_parameters, scoped_parameters, bound_parameters = set(), set(), set()
        all_mapped, scoped_mapped, public, navigation = set(), set(), set(), set()
        all_controls, scoped_controls = set(), set()
        all_mapped_maps, scoped_mapped_maps, public_maps = set(), set(), set()
        for identity, operation in operations.items():
            included = (
                operation["category"] not in excluded_categories and identity not in excluded_operations
            )
            roots = [row["schema_pointer"] for row in operation["responses"] if "schema_pointer" in row]
            all_roots.extend(roots)
            if included:
                scoped_roots.extend(roots)
            property_keys, dynamic_maps = _reachable(nodes, roots)
            parameter_keys = {
                identity + ":" + item["in"] + ":" + item["name"] for item in operation["parameters"]
            }
            all_parameters.update(parameter_keys)
            if included:
                scoped_parameters.update(parameter_keys)
            selected = [
                source
                for source in sources
                if source["transport"].get("kind") == "rest"
                and source["transport"].get("product") == product
                and source["transport"]["operation_id"] == identity
            ]
            mapped, op_public, op_navigation, bindings = set(), set(), set(), {}
            op_controls = set()
            op_mapped_maps, op_public_maps = set(), set()
            for source in selected:
                transport = source["transport"]
                projection = source.get("source", {}).get("response_projection", {})
                selected_roots = [
                    row["schema_pointer"]
                    for row in operation["responses"]
                    if row["status"] == str(transport.get("response_status", "200"))
                    and row.get("media_type") == projection.get("media_type", "application/json")
                    and "schema_pointer" in row
                ]
                if not selected_roots and "content" not in transport:
                    raise ValueError(f"Selected REST response is absent from inventory: {identity}")
                if "variant" in projection:
                    variant = projection["variant"]
                    narrowed = []
                    for pointer in selected_roots:
                        alternatives = nodes[pointer].get(variant["kind"], [])
                        if not 0 <= variant["index"] < len(alternatives):
                            raise ValueError(
                                f"Selected REST response variant is absent from inventory: {identity}"
                            )
                        narrowed.append(alternatives[variant["index"]])
                    selected_roots = narrowed
                count_path = transport.get("pagination", {}).get("total_count_path")
                control_paths = [("pagination_total_count_validation", count_path)] if count_path else []
                control_paths.extend(
                    ("response_assertion_" + assertion["comparison"], assertion["path"])
                    for assertion in transport.get("response_assertions", [])
                )
                for purpose, control_path in control_paths:
                    control_keys, control_navigation, _ = _map_rest_column(
                        nodes,
                        selected_roots,
                        [],
                        {
                            "name": purpose,
                            "path": control_path,
                            "schema": {"kind": "scalar", "type": "BIGINT"},
                        },
                    )
                    op_controls.update(control_keys)
                    controls.append(
                        {
                            "source": source["name"],
                            "operation_id": identity,
                            "purpose": purpose,
                            "path": control_path,
                            "properties": sorted(control_keys),
                            "navigation_properties": sorted(control_navigation),
                        }
                    )
                for column in source["columns"]:
                    keys, visited, mapped_maps = _map_rest_column(
                        nodes, selected_roots, transport.get("result_path", []), column
                    )
                    exposures = exposed[(source["name"], column["name"])]
                    projections = {name for name, _ in exposures}
                    mapped.update(keys)
                    op_mapped_maps.update(mapped_maps)
                    op_navigation.update(visited)
                    if projections:
                        for _, projection in exposures:
                            projected_keys, _, projected_maps = _map_rest_column(
                                nodes, selected_roots, transport.get("result_path", []), column, projection
                            )
                            op_public.update(projected_keys)
                            op_public_maps.update(projected_maps)
                    columns.append(
                        {
                            "source": source["name"],
                            "column": column["name"],
                            "operation_id": identity,
                            "mapped_properties": sorted(keys),
                            "navigation_properties": sorted(visited),
                            "public_fields": sorted(projections),
                            "mapped_dynamic_maps": sorted(mapped_maps),
                            **(
                                {"response_metadata": column["source_response"]}
                                if "source_response" in column
                                else {}
                            ),
                            **(
                                {"response_metadata": "dictionary_key"}
                                if column.get("source_entry") == "key"
                                else {}
                            ),
                        }
                    )
                for parameter in operation["parameters"]:
                    place, name = parameter["in"], parameter["name"]
                    binding = transport.get(place + "_bindings", {}).get(name)
                    mechanism = "explicit" if binding is not None else None
                    if place == "query" and name == "per_page":
                        mechanism = mechanism or "runtime_page_size"
                    if place == "query" and name == "page" and transport["pagination"]["kind"] == "link":
                        mechanism = mechanism or "server_link_pagination"
                    if mechanism:
                        key = identity + ":" + place + ":" + name
                        bindings.setdefault(key, []).append(
                            {
                                "source": source["name"],
                                "mechanism": mechanism,
                                **({"binding": binding} if binding is not None else {}),
                            }
                        )
            all_mapped.update(mapped)
            all_controls.update(op_controls)
            all_mapped_maps.update(op_mapped_maps)
            if included:
                scoped_mapped.update(mapped)
                scoped_controls.update(op_controls)
                public.update(op_public)
                navigation.update(op_navigation)
                bound_parameters.update(bindings)
                scoped_mapped_maps.update(op_mapped_maps)
                public_maps.update(op_public_maps)
            operation_rows[identity] = {
                "included": included,
                "response_property_count": len(property_keys),
                "dynamic_map_count": len(dynamic_maps),
                "parameter_count": len(parameter_keys),
                "mapped_properties": sorted(mapped),
                "public_properties": sorted(op_public),
                "navigation_properties": sorted(op_navigation),
                "control_properties": sorted(op_controls),
                "mapped_dynamic_maps": sorted(op_mapped_maps),
                "public_dynamic_maps": sorted(op_public_maps),
                "parameter_bindings": bindings,
                "selected_sources": sorted(source["name"] for source in selected),
                "content_contracts": [
                    {"source": source["name"], **source["transport"]["content"]}
                    for source in selected
                    if "content" in source["transport"]
                ],
            }
        properties, dynamic_maps = _reachable(nodes, all_roots)
        scoped_properties, scoped_maps = _reachable(nodes, scoped_roots)
        result["rest"]["products"][product] = {
            "summary": {
                "operations": len(operations),
                "in_scope_operations": sum(row["included"] for row in operation_rows.values()),
                "selected_operations": sum(bool(row["selected_sources"]) for row in operation_rows.values()),
                "response_properties": len(properties),
                "in_scope_response_properties": len(scoped_properties),
                "mapped_response_properties": len(all_mapped),
                "in_scope_mapped_response_properties": len(scoped_mapped),
                "in_scope_public_response_properties": len(public),
                "in_scope_navigation_properties": len(navigation),
                "validated_control_response_properties": len(all_controls),
                "in_scope_validated_control_response_properties": len(scoped_controls),
                "dynamic_maps": len(dynamic_maps),
                "in_scope_dynamic_maps": len(scoped_maps),
                "mapped_dynamic_maps": len(all_mapped_maps),
                "in_scope_mapped_dynamic_maps": len(scoped_mapped_maps),
                "in_scope_public_dynamic_maps": len(public_maps),
                "parameters": len(all_parameters),
                "in_scope_parameters": len(scoped_parameters),
                "in_scope_bound_parameters": len(bound_parameters),
            },
            "operations": operation_rows,
            "columns": columns,
            "controls": controls,
        }
    graphql = inventory.get("graphql", {})
    exclusions = graphql_exclusions(graphql, excluded_graphql_types, excluded_graphql_fields)
    declared_fields = {row["coordinate"] for row in graphql.get("fields", [])}
    included_fields = declared_fields - exclusions.keys()
    declared_arguments = {
        row["coordinate"] + "(" + name + ")"
        for row in graphql.get("fields", [])
        for name in row.get("arguments", {})
    }
    included_arguments = {
        row["coordinate"] + "(" + name + ")"
        for row in graphql.get("fields", [])
        if row["coordinate"] in included_fields
        for name in row.get("arguments", {})
    }
    fetched_all, public_all, arguments_all, graphql_sources = set(), set(), set(), []
    for source in sources:
        if source["transport"]["kind"] != "graphql":
            continue
        by_path, fetched, arguments = _graphql_query_fields(source, graphql)
        public, mapped, columns = set(), set(), []
        for column in source["columns"]:
            if "path" not in column:
                continue
            path = (*source["transport"]["result_path"], *column["path"])
            constraints = {path[:-1]: set(column["on_types"])} if "on_types" in column else {}
            coordinates = _graphql_coordinates(by_path, path, constraints)
            for child, _, conditions in _typed_descendants(column["schema"]):
                restrictions = {**constraints, **{(*path, *parent): {kind} for parent, kind in conditions}}
                coordinates.update(_graphql_coordinates(by_path, (*path, *child), restrictions))
            if not coordinates:
                raise ValueError(
                    f"Mapped GraphQL column absent from fetched query: {source['name']}.{column['name']}"
                )
            metadata = None in coordinates
            coordinates.discard(None)
            exposures = exposed[(source["name"], column["name"])]
            projections = {name for name, _ in exposures}
            if projections:
                for _, projection in exposures:
                    if not projection:
                        public.update(coordinates)
                        continue
                    projected = _projection_schema(column["schema"], projection)
                    selected = _graphql_coordinates(by_path, path, constraints)
                    for child, _, conditions in _typed_descendants(projected):
                        restrictions = {
                            **constraints,
                            **{(*path, *parent): {kind} for parent, kind in conditions},
                        }
                        selected.update(_graphql_coordinates(by_path, (*path, *child), restrictions))
                    selected.discard(None)
                    public.update(selected)
            mapped.update(coordinates)
            columns.append(
                {
                    "column": column["name"],
                    "coordinates": sorted(coordinates),
                    "public_fields": sorted(projections),
                    **({"response_metadata": "__typename"} if metadata else {}),
                }
            )
        fetched_all.update(fetched)
        public_all.update(public)
        arguments_all.update(arguments)
        graphql_sources.append(
            {
                "source": source["name"],
                "fetched_coordinates": sorted(fetched),
                "mapped_coordinates": sorted(mapped),
                "public_coordinates": sorted(public),
                "bound_arguments": sorted(arguments),
                "columns": columns,
            }
        )
    result["graphql"] = {
        "denominator": (
            "Unique query-reachable Type.field declarations, including interface and concrete-type "
            "declarations separately. Raw totals retain the full pinned read schema. Scoped totals "
            "exclude only explicit owner-type or field names; shared and returned types are not "
            "transitively excluded. Argument identities are Type.field(argument) and inherit their "
            "owning field's scope. Fetched coordinates require actual query AST selections in "
            "sources reachable from exported functions; public "
            "coordinates additionally require a public typed projection. REST equivalents and "
            "selected-schema inclusion do not count as GraphQL fetching or public exposure."
        ),
        "summary": {
            "read_fields": len(declared_fields),
            "excluded_fields": len(exclusions),
            "in_scope_read_fields": len(included_fields),
            "fetched_fields": len(fetched_all),
            "in_scope_fetched_fields": len(fetched_all & included_fields),
            "excluded_fetched_fields": len(fetched_all & exclusions.keys()),
            "public_fields": len(public_all),
            "in_scope_public_fields": len(public_all & included_fields),
            "excluded_public_fields": len(public_all & exclusions.keys()),
            "declared_arguments": len(declared_arguments),
            "in_scope_declared_arguments": len(included_arguments),
            "excluded_declared_arguments": len(declared_arguments - included_arguments),
            "bound_arguments": len(arguments_all),
            "in_scope_bound_arguments": len(arguments_all & included_arguments),
            "excluded_bound_arguments": len(arguments_all & (declared_arguments - included_arguments)),
        },
        "fetched_coordinates": sorted(fetched_all),
        "in_scope_fetched_coordinates": sorted(fetched_all & included_fields),
        "excluded_fetched_coordinates": sorted(fetched_all & exclusions.keys()),
        "public_coordinates": sorted(public_all),
        "in_scope_public_coordinates": sorted(public_all & included_fields),
        "excluded_public_coordinates": sorted(public_all & exclusions.keys()),
        "bound_arguments": sorted(arguments_all),
        "in_scope_bound_arguments": sorted(arguments_all & included_arguments),
        "excluded_bound_arguments": sorted(arguments_all & (declared_arguments - included_arguments)),
        "excluded_coordinates": sorted(exclusions),
        "scope_policy": {
            "excluded_types": dict(excluded_graphql_types or {}),
            "excluded_fields": dict(excluded_graphql_fields or {}),
        },
        "sources": graphql_sources,
        "exclusion_status": (
            "Explicit type and field exclusions apply only to scoped totals; "
            "raw totals retain the full read schema."
            if exclusions
            else "No GraphQL type or field exclusions are declared; scoped totals equal the full read schema."
        ),
    }
    return result
