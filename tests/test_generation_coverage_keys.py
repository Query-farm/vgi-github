"""Independent finite API-key denominators and public-exposure measurements."""

import pytest

from vgi_github.generation.coverage import graphql_inventory
from vgi_github.generation.coverage_keys import audit_contract_keys, rest_contract_keys


def schema_ref(name):
    return {"$ref": "#/components/schemas/" + name}


def small_api():
    return {
        "paths": {
            "/nodes/{node_id}": {
                "parameters": [{"$ref": "#/components/parameters/node_id"}],
                "get": {
                    "operationId": "nodes/list",
                    "parameters": [
                        {"in": "query", "name": name, "schema": {"type": "integer"}}
                        for name in ["per_page", "page", "unused_filter"]
                    ],
                    "responses": {
                        "200": {"content": {"application/json": {"schema": schema_ref("Envelope")}}},
                        "206": {
                            "content": {
                                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                            }
                        },
                        "302": {"description": "Download redirect"},
                        "304": {"description": "Not modified"},
                        "404": {"content": {"application/json": {"schema": schema_ref("Error")}}},
                    },
                },
            },
            "/billing": {
                "get": {
                    "operationId": "billing/get",
                    "responses": {
                        "200": {"content": {"application/json": {"schema": schema_ref("Invoice")}}}
                    },
                }
            },
        },
        "components": {
            "parameters": {
                "node_id": {"in": "path", "name": "node_id", "required": True, "schema": {"type": "integer"}}
            },
            "schemas": {
                "Envelope": {
                    "type": "object",
                    "properties": {
                        "nodes": {"type": "array", "items": schema_ref("Node")},
                        "total_count": {"type": "integer"},
                    },
                },
                "Node": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "integer"},
                        "label": {"type": "string"},
                        "next": schema_ref("Node"),
                        "owner": schema_ref("Owner"),
                        "attributes": {"type": "object", "additionalProperties": schema_ref("Attribute")},
                        "variant": {"anyOf": [schema_ref("VariantA"), schema_ref("VariantB")]},
                    },
                },
                "Owner": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                    "additionalProperties": False,
                },
                "Attribute": {"type": "object", "properties": {"rank": {"type": "integer"}}},
                "VariantA": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "VariantB": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "Invoice": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "total": {"type": "integer"}},
                },
                "Error": {"type": "object", "properties": {"message": {"type": "string"}}},
            },
        },
    }


def scalar(kind="BIGINT"):
    return {"kind": "scalar", "type": kind, "nullable": False}


def source_column(name, path, descriptor=None):
    return {"name": name, "path": path, "schema": descriptor or scalar()}


def rest_source():
    return {
        "name": "nodes_source",
        "transport": {
            "kind": "rest",
            "product": "api.github.com",
            "operation_id": "nodes/list",
            "result_path": ["nodes"],
            "pagination": {"kind": "link"},
            "path_bindings": {"node_id": {"argument": "node_id"}},
            "query_bindings": {},
        },
        "columns": [
            source_column("id", ["id"]),
            source_column("owner_id", ["owner", "id"]),
            source_column("private_label", ["label"], scalar("VARCHAR")),
            source_column("variant_id", ["variant", "id"]),
        ],
    }


def public_function(source, names):
    return {
        "name": "public_nodes",
        "traversal": {"stages": [{"name": "rows", "entity": source}], "output_stage": "rows"},
        "columns": [{"name": name, "source_stage": "rows", "source_column": name} for name in names],
    }


def test_reviewed_response_media_and_variant_cover_only_the_selected_declarations():
    def rows(kind):
        return {
            "type": "array",
            "items": {"type": "object", "properties": {"id": {"type": kind}}},
        }

    spec = {
        "paths": {
            "/records": {
                "get": {
                    "operationId": "records/list",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": rows("string")},
                                "application/vnd.fixture+json": {
                                    "schema": {"anyOf": [rows("string"), rows("integer")]}
                                },
                            }
                        }
                    },
                }
            }
        }
    }
    source = {
        "name": "records",
        "transport": {
            "kind": "rest",
            "product": "api.github.com",
            "operation_id": "records/list",
        },
        "source": {
            "response_projection": {
                "media_type": "application/vnd.fixture+json",
                "variant": {"kind": "anyOf", "index": 1, "comment": "Reviewed integer form."},
            },
        },
        "columns": [source_column("id", ["id"])],
    }
    measured = audit_contract_keys(
        {"entities": [source], "functions": [public_function("records", ["id"])]},
        {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(spec)}}},
    )["rest"]["products"]["api.github.com"]
    assert measured["summary"]["response_properties"] == 3
    assert measured["summary"]["in_scope_public_response_properties"] == 1
    assert measured["operations"]["records/list"]["public_properties"] == [
        "#/paths/~1records/get/responses/200/content/application~1vnd.fixture+json/schema/anyOf/1/items/properties/id"
    ]


def test_finite_property_denominator_and_excluded_scope():
    graph = rest_contract_keys(small_api())
    contract = {
        "entities": [rest_source()],
        "functions": [public_function("nodes_source", ["id", "owner_id"])],
    }
    measured = audit_contract_keys(
        contract,
        {"rest": {"contract_keys_by_product": {"api.github.com": graph}}},
        excluded_categories=["billing"],
    )
    product = measured["rest"]["products"]["api.github.com"]
    assert product["summary"]["response_properties"] == 15
    assert product["summary"]["in_scope_response_properties"] == 13
    assert product["summary"]["in_scope_mapped_response_properties"] == 5
    assert product["summary"]["in_scope_public_response_properties"] == 2
    assert product["summary"]["in_scope_bound_parameters"] == 3
    assert product["summary"]["in_scope_parameters"] == 4
    assert product["summary"]["in_scope_dynamic_maps"] == 1
    public = product["operations"]["nodes/list"]["public_properties"]
    assert public == ["#/components/schemas/Node/properties/id", "#/components/schemas/Owner/properties/id"]
    assert (
        "#/components/schemas/Owner/properties/name"
        not in product["operations"]["nodes/list"]["mapped_properties"]
    )


def test_redirects_binary_and_error_bodies_are_distinguished():
    graph = rest_contract_keys(small_api())
    responses = graph["operations"]["nodes/list"]["responses"]
    assert [(row["status"], row["body"]) for row in responses] == [
        ("200", "schema"),
        ("206", "schema"),
        ("302", "none"),
        ("304", "none"),
    ]
    binary = next(row for row in responses if row["status"] == "206")
    assert graph["nodes"][binary["schema_pointer"]] == {"type": "string", "format": "binary"}
    assert "#/components/schemas/Error" not in graph["nodes"]
    assert graph["nodes"]["#/components/schemas/Node"]["required"] == ["id"]
    assert graph["nodes"]["#/components/schemas/Node"]["properties"]["next"] == "#/components/schemas/Node"


def test_nested_struct_projection_counts_only_selected_children():
    source = rest_source()
    source["columns"] = [
        source_column("owner", ["owner"], {"kind": "struct", "fields": [{"name": "id", "schema": scalar()}]})
    ]
    contract = {"entities": [source], "functions": [public_function("nodes_source", ["owner"])]}
    result = audit_contract_keys(
        contract, {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(small_api())}}}
    )
    row = result["rest"]["products"]["api.github.com"]["columns"][0]
    assert row["mapped_properties"] == [
        "#/components/schemas/Node/properties/owner",
        "#/components/schemas/Owner/properties/id",
    ]
    assert row["navigation_properties"] == ["#/components/schemas/Envelope/properties/nodes"]


def test_shared_types_do_not_double_count_across_operations():
    spec = small_api()
    spec["paths"]["/another"] = {
        "get": {
            "operationId": "nodes/another",
            "responses": {"200": {"content": {"application/json": {"schema": schema_ref("Node")}}}},
        }
    }
    result = audit_contract_keys(
        {"entities": [], "functions": []},
        {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(spec)}}},
    )
    assert result["rest"]["products"]["api.github.com"]["summary"]["response_properties"] == 15


def test_response_refs_and_property_pointer_escaping():
    spec = {
        "paths": {
            "/a/b": {
                "get": {
                    "operationId": "nodes/get",
                    "responses": {"200": {"$ref": "#/components/responses/Success"}},
                }
            }
        },
        "components": {
            "responses": {
                "Success": {
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"a/b~c": {"type": "string"}}}
                        }
                    }
                }
            }
        },
    }
    graph = rest_contract_keys(spec)
    pointer = graph["operations"]["nodes/get"]["responses"][0]["schema_pointer"]
    assert pointer == "#/components/responses/Success/content/application~1json/schema"
    assert graph["nodes"][pointer]["properties"]["a/b~c"].endswith("/properties/a~1b~0c")


def test_graphql_actual_fetching_and_public_projection_are_separate():
    sdl = """
        type Query { node(id: ID!): Node unused: String }
        interface Node { id: ID! }
        type User implements Node { id: ID! login: String! privateNote: String }
        type Team implements Node { id: ID! name: String }
    """
    source = {
        "name": "node_source",
        "transport": {
            "kind": "graphql",
            "result_path": ["record"],
            "document": (
                "query Example($id: ID!) { record: node(id: $id) { id "
                "... on User { label: login privateNote } ...TeamFields } } "
                "fragment TeamFields on Team { name }"
            ),
        },
        "columns": [
            source_column("id", ["id"]),
            source_column("label", ["label"], scalar("VARCHAR")),
            source_column("private_note", ["privateNote"], scalar("VARCHAR")),
        ],
    }
    contract = {"entities": [source], "functions": [public_function("node_source", ["id", "label"])]}
    measured = audit_contract_keys(contract, {"graphql": graphql_inventory(sdl)})["graphql"]
    assert measured["fetched_coordinates"] == [
        "Node.id",
        "Query.node",
        "Team.name",
        "User.login",
        "User.privateNote",
    ]
    assert measured["public_coordinates"] == ["Node.id", "User.login"]
    assert measured["bound_arguments"] == ["Query.node(id)"]
    assert measured["summary"]["read_fields"] == 8
    assert measured["summary"]["fetched_fields"] == 5
    assert measured["summary"]["public_fields"] == 2


def test_graphql_scoped_denominators_preserve_raw_fetches_and_shared_return_types():
    sdl = """
        interface Node { id: ID! }
        type Query { enterprise(slug: String): Enterprise user(login: String!): User node: Node }
        type Enterprise implements Node { id: ID! owner: User members(first: Int): [User!]! }
        type User implements Node { id: ID! login: String! enterprise: Enterprise secret: String }
    """
    source = {
        "name": "enterprise_source",
        "transport": {
            "kind": "graphql",
            "result_path": ["enterprise"],
            "document": (
                '{ enterprise(slug: "example") { id owner { id login secret } members(first: 1) { id } } }'
            ),
        },
        "columns": [
            source_column("enterprise_id", ["id"]),
            source_column("owner_login", ["owner", "login"], scalar("VARCHAR")),
            source_column("owner_secret", ["owner", "secret"], scalar("VARCHAR")),
        ],
    }
    measured = audit_contract_keys(
        {
            "entities": [source],
            "functions": [
                public_function("enterprise_source", ["enterprise_id", "owner_login", "owner_secret"])
            ],
        },
        {"graphql": graphql_inventory(sdl)},
        excluded_graphql_types={"Enterprise": "Enterprise management is outside this model."},
        excluded_graphql_fields={
            "Query.enterprise": "Enterprise retrieval is outside this model.",
            "User.secret": "This specific shared-type field is outside this model.",
        },
    )["graphql"]
    assert measured["summary"] == {
        "read_fields": 11,
        "excluded_fields": 5,
        "in_scope_read_fields": 6,
        "fetched_fields": 7,
        "in_scope_fetched_fields": 2,
        "excluded_fetched_fields": 5,
        "public_fields": 3,
        "in_scope_public_fields": 1,
        "excluded_public_fields": 2,
        "declared_arguments": 3,
        "in_scope_declared_arguments": 1,
        "excluded_declared_arguments": 2,
        "bound_arguments": 2,
        "in_scope_bound_arguments": 0,
        "excluded_bound_arguments": 2,
    }
    assert measured["excluded_coordinates"] == [
        "Enterprise.id",
        "Enterprise.members",
        "Enterprise.owner",
        "Query.enterprise",
        "User.secret",
    ]
    assert measured["fetched_coordinates"] == [
        "Enterprise.id",
        "Enterprise.members",
        "Enterprise.owner",
        "Query.enterprise",
        "User.id",
        "User.login",
        "User.secret",
    ]
    assert measured["in_scope_fetched_coordinates"] == ["User.id", "User.login"]
    assert measured["public_coordinates"] == ["Enterprise.id", "User.login", "User.secret"]
    assert measured["in_scope_public_coordinates"] == ["User.login"]
    assert measured["excluded_public_coordinates"] == ["Enterprise.id", "User.secret"]
    assert measured["in_scope_bound_arguments"] == []
    assert measured["excluded_bound_arguments"] == ["Enterprise.members(first)", "Query.enterprise(slug)"]
    assert measured["scope_policy"]["excluded_types"] == {
        "Enterprise": "Enterprise management is outside this model."
    }
    assert {"Node.id", "User.enterprise", "Query.user"}.isdisjoint(measured["excluded_coordinates"])
    assert measured["sources"][0]["public_coordinates"] == measured["public_coordinates"]


@pytest.mark.parametrize(
    "policy",
    [
        {"excluded_graphql_types": {"Unknown": "Unknown type"}},
        {"excluded_graphql_types": {"User*": "No wildcards"}},
        {"excluded_graphql_fields": {"User.absent": "Unknown field"}},
        {"excluded_graphql_fields": {"User.*": "No wildcards"}},
        {"excluded_graphql_types": {"User": " "}},
        {"excluded_graphql_fields": {"User.id": None}},
        {"excluded_graphql_types": ["User"]},
        {"excluded_graphql_fields": []},
    ],
)
def test_graphql_scope_requires_known_exact_names_and_explicit_reasons(policy):
    with pytest.raises(ValueError, match="GraphQL (type|field) exclusions.*known exact names.*reasons"):
        audit_contract_keys(
            {"entities": [], "functions": []},
            {"graphql": graphql_inventory("type Query { user: User } type User { id: ID! }")},
            **policy,
        )


def test_graphql_aliases_and_restricted_subtypes_do_not_inflate_public_keys():
    sdl = """
        type Query { actor: Actor }
        union Actor = User | Organization
        type User { email: String }
        type Organization { email: String }
    """
    source = {
        "name": "actor_source",
        "transport": {
            "kind": "graphql",
            "result_path": ["actor"],
            "response_aliases": {"u_email": "email", "o_email": "email"},
            "document": "{ actor { ... on User { u_email: email } ... on Organization { o_email: email } } }",
        },
        "columns": [{**source_column("user_email", ["email"], scalar("VARCHAR")), "on_types": ["User"]}],
    }
    measured = audit_contract_keys(
        {"entities": [source], "functions": [public_function("actor_source", ["user_email"])]},
        {"graphql": graphql_inventory(sdl)},
    )["graphql"]
    assert measured["fetched_coordinates"] == ["Organization.email", "Query.actor", "User.email"]
    assert measured["public_coordinates"] == ["User.email"]


def test_graphql_typename_is_verified_metadata_without_inflating_field_coverage():
    sdl = "type Query { actor: User } type User { id: ID! }"
    source = {
        "name": "actor_source",
        "transport": {"kind": "graphql", "result_path": ["actor"], "document": "{ actor { __typename id } }"},
        "columns": [source_column("actor_type", ["__typename"], scalar("VARCHAR"))],
    }
    measured = audit_contract_keys(
        {"entities": [source], "functions": [public_function("actor_source", ["actor_type"])]},
        {"graphql": graphql_inventory(sdl)},
    )["graphql"]
    assert measured["fetched_coordinates"] == ["Query.actor", "User.id"]
    assert measured["public_coordinates"] == []
    assert measured["sources"][0]["columns"] == [
        {
            "column": "actor_type",
            "coordinates": [],
            "public_fields": ["public_nodes.actor_type"],
            "response_metadata": "__typename",
        }
    ]


def test_public_scopes_trace_only_declared_physical_projections():
    contract = {
        "entities": [rest_source()],
        "scopes": {"choice": {"select": {"entity": "nodes_source"}}},
        "functions": [
            {
                "name": "public_nodes",
                "routes": [
                    {
                        "traversal": {"stages": [{"name": "rows", "scope": "choice"}]},
                        "columns": [{"name": "id", "source_stage": "rows", "source_column": "id"}],
                    }
                ],
            }
        ],
    }
    result = audit_contract_keys(
        contract, {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(small_api())}}}
    )
    assert result["rest"]["products"]["api.github.com"]["summary"]["in_scope_public_response_properties"] == 1


def test_unreferenced_scope_sources_do_not_select_operations_or_map_keys():
    dormant = {
        "name": "billing_source",
        "transport": {"kind": "rest", "product": "api.github.com", "operation_id": "billing/get"},
        "columns": [source_column("id", ["id"]), source_column("total", ["total"])],
    }
    function = public_function("nodes_source", ["id"])
    function["traversal"]["stages"] = [{"name": "rows", "scope": "active"}]
    contract = {
        "entities": [rest_source(), dormant],
        "functions": [function],
        "scopes": {
            "active": {"select": {"entity": "nodes_source"}},
            "unused": {"select": {"entity": "billing_source"}},
        },
    }
    measured = audit_contract_keys(
        contract,
        {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(small_api())}}},
    )
    product = measured["rest"]["products"]["api.github.com"]
    assert product["summary"]["operations"] == 2
    assert product["summary"]["selected_operations"] == 1
    assert product["summary"]["response_properties"] == 15
    assert product["summary"]["mapped_response_properties"] == 5
    assert product["summary"]["in_scope_bound_parameters"] == 3
    assert product["operations"]["billing/get"]["selected_sources"] == []
    assert product["operations"]["billing/get"]["mapped_properties"] == []
    assert measured["source_reachability"]["compiled_sources"] == 2
    assert measured["source_reachability"]["reachable_sources"] == 1
    assert measured["source_reachability"]["unreachable_sources"] == ["billing_source"]
    assert len(contract["entities"]) == 2

    # A source used only to resolve a filter is reachable, but its values are not public fields.
    function["filters"] = [
        {"root": {"traversal": {"stages": [{"name": "filter_ids", "entity": "billing_source"}]}}}
    ]
    filtered = audit_contract_keys(
        contract,
        {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(small_api())}}},
    )
    billing = filtered["rest"]["products"]["api.github.com"]["operations"]["billing/get"]
    assert billing["selected_sources"] == ["billing_source"]
    assert billing["public_properties"] == []
    assert filtered["source_reachability"]["unreachable_sources"] == []


def test_unreachable_graphql_documents_do_not_count_as_fetching_or_bound_arguments():
    active = {
        "name": "active_source",
        "transport": {"kind": "graphql", "result_path": ["active"], "document": "{ active { id } }"},
        "columns": [source_column("id", ["id"])],
    }
    dormant = {
        "name": "dormant_source",
        "transport": {
            "kind": "graphql",
            "result_path": ["inactive"],
            "document": "{ inactive(limit: 2) { secret } }",
        },
        "columns": [source_column("secret", ["secret"], scalar("VARCHAR"))],
    }
    contract = {
        "entities": [active, dormant],
        "functions": [public_function("active_source", ["id"])],
    }
    measured = audit_contract_keys(
        contract,
        {
            "graphql": graphql_inventory(
                "type Query { active: User inactive(limit: Int): Admin } "
                "type User { id: ID! } type Admin { secret: String }"
            )
        },
    )
    graph = measured["graphql"]
    assert graph["summary"]["read_fields"] == 4
    assert graph["summary"]["declared_arguments"] == 1
    assert graph["fetched_coordinates"] == ["Query.active", "User.id"]
    assert graph["public_coordinates"] == ["User.id"]
    assert graph["bound_arguments"] == []
    assert measured["source_reachability"]["unreachable_sources"] == ["dormant_source"]
    assert len(contract["entities"]) == 2


def test_source_only_runtime_exports_differ_from_an_explicitly_empty_function_catalog():
    contract = {"entities": [rest_source()]}
    inventory = {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(small_api())}}}
    direct = audit_contract_keys(contract, inventory)
    empty = audit_contract_keys({**contract, "functions": []}, inventory)
    assert direct["rest"]["products"]["api.github.com"]["summary"]["selected_operations"] == 1
    assert direct["source_reachability"]["unreachable_sources"] == []
    assert empty["rest"]["products"]["api.github.com"]["summary"]["selected_operations"] == 0
    assert empty["source_reachability"]["unreachable_sources"] == ["nodes_source"]


def test_operation_tags_override_namespace_for_category_exclusions():
    spec = small_api()
    spec["paths"]["/nodes/{node_id}"]["get"]["tags"] = ["enterprise-apps", "nodes"]
    graph = rest_contract_keys(spec)
    assert graph["operations"]["nodes/list"]["category"] == "enterprise-apps"
    assert graph["operations"]["billing/get"]["category"] == "billing"
    measured = audit_contract_keys(
        {"entities": [], "functions": []},
        {"rest": {"contract_keys_by_product": {"ghec": graph}}},
        excluded_categories=["enterprise-apps"],
    )["rest"]["products"]["ghec"]
    assert measured["summary"]["in_scope_operations"] == 1
    assert measured["summary"]["in_scope_response_properties"] == 2
    assert measured["operations"]["nodes/list"]["included"] is False


def test_operation_exclusions_also_remove_their_properties_and_parameters():
    measured = audit_contract_keys(
        {"entities": [], "functions": []},
        {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(small_api())}}},
        excluded_operations=["nodes/list"],
    )["rest"]["products"]["api.github.com"]
    assert measured["summary"]["in_scope_operations"] == 1
    assert measured["summary"]["in_scope_response_properties"] == 2
    assert measured["operations"]["nodes/list"]["included"] is False
    assert measured["operations"]["billing/get"]["included"] is True


def test_content_metadata_is_measured_without_claiming_json_property_coverage():
    source = rest_source()
    source["transport"]["content"] = {"accept": "application/octet-stream", "response_statuses": ["302"]}
    source["columns"] = [
        {"name": "bytes", "source_response": "body", "schema": {"kind": "scalar", "type": "BLOB"}}
    ]
    graph = rest_contract_keys(small_api())
    graph["operations"]["nodes/list"]["responses"] = [{"status": "302", "body": "none"}]
    measured = audit_contract_keys(
        {"entities": [source], "functions": [public_function("nodes_source", ["bytes"])]},
        {"rest": {"contract_keys_by_product": {"api.github.com": graph}}},
    )["rest"]["products"]["api.github.com"]
    operation = measured["operations"]["nodes/list"]
    assert operation["mapped_properties"] == operation["public_properties"] == []
    assert operation["content_contracts"] == [
        {"source": "nodes_source", "accept": "application/octet-stream", "response_statuses": ["302"]}
    ]
    assert measured["columns"][0]["response_metadata"] == "body"
    assert measured["columns"][0]["public_fields"] == ["public_nodes.bytes"]


def test_typed_dictionary_values_count_separately_from_fixed_properties():
    source = rest_source()
    source["columns"] = [
        source_column(
            "attributes",
            ["attributes"],
            {
                "kind": "map",
                "key": scalar("VARCHAR"),
                "value": {"kind": "struct", "fields": [{"name": "rank", "schema": scalar()}]},
            },
        )
    ]
    measured = audit_contract_keys(
        {"entities": [source], "functions": [public_function("nodes_source", ["attributes"])]},
        {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(small_api())}}},
    )["rest"]["products"]["api.github.com"]
    operation = measured["operations"]["nodes/list"]
    assert operation["public_properties"] == [
        "#/components/schemas/Attribute/properties/rank",
        "#/components/schemas/Node/properties/attributes",
    ]
    assert operation["public_dynamic_maps"] == ["#/components/schemas/Node/properties/attributes"]
    assert measured["summary"]["in_scope_public_dynamic_maps"] == 1


def test_nested_public_projection_does_not_claim_unexposed_siblings():
    source = rest_source()
    source["columns"] = [
        source_column(
            "owner",
            ["owner"],
            {
                "kind": "struct",
                "fields": [{"name": "id", "schema": scalar()}, {"name": "name", "schema": scalar("VARCHAR")}],
            },
        )
    ]
    public = public_function("nodes_source", ["owner"])
    public["columns"][0].update(name="owner_id", source_path=["id"])
    measured = audit_contract_keys(
        {"entities": [source], "functions": [public]},
        {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(small_api())}}},
    )["rest"]["products"]["api.github.com"]["operations"]["nodes/list"]
    assert "#/components/schemas/Owner/properties/name" in measured["mapped_properties"]
    assert measured["public_properties"] == [
        "#/components/schemas/Node/properties/owner",
        "#/components/schemas/Owner/properties/id",
    ]


def test_entry_keys_do_not_claim_dictionary_value_coverage():
    spec = small_api()
    spec["paths"]["/nodes/{node_id}"]["get"]["responses"] = {
        "200": {
            "content": {
                "application/json": {
                    "schema": {"type": "object", "additionalProperties": {"type": "integer"}}
                }
            }
        }
    }
    source = rest_source()
    source["transport"].update(result_path=[], result_shape="object_entries")
    source["columns"] = [
        {"name": "name", "source_entry": "key", "schema": scalar("VARCHAR")},
        {"name": "amount", "source_entry": "value", "schema": scalar()},
    ]
    inventory = {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(spec)}}}
    contract = {"entities": [source], "functions": [public_function("nodes_source", ["name"])]}
    measured = audit_contract_keys(contract, inventory)["rest"]["products"]["api.github.com"]
    assert measured["summary"]["mapped_dynamic_maps"] == 1
    assert measured["summary"]["in_scope_public_dynamic_maps"] == 0
    assert measured["columns"][0]["response_metadata"] == "dictionary_key"
    contract["functions"] = [public_function("nodes_source", ["name", "amount"])]
    measured = audit_contract_keys(contract, inventory)["rest"]["products"]["api.github.com"]
    assert measured["summary"]["in_scope_public_dynamic_maps"] == 1
    assert measured["operations"]["nodes/list"]["public_properties"] == []


def test_pagination_total_count_is_control_coverage_not_public_data():
    source = rest_source()
    source["transport"]["pagination"]["total_count_path"] = ["total_count"]
    contract = {"entities": [source], "functions": [public_function("nodes_source", ["id"])]}
    measured = audit_contract_keys(
        contract,
        {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(small_api())}}},
    )["rest"]["products"]["api.github.com"]
    key = "#/components/schemas/Envelope/properties/total_count"
    assert measured["summary"]["validated_control_response_properties"] == 1
    assert measured["summary"]["in_scope_validated_control_response_properties"] == 1
    assert measured["summary"]["in_scope_mapped_response_properties"] == 5
    assert measured["summary"]["in_scope_public_response_properties"] == 1
    assert measured["operations"]["nodes/list"]["control_properties"] == [key]
    assert key not in measured["operations"]["nodes/list"]["mapped_properties"]
    assert key not in measured["operations"]["nodes/list"]["public_properties"]
    assert measured["controls"] == [
        {
            "source": "nodes_source",
            "operation_id": "nodes/list",
            "purpose": "pagination_total_count_validation",
            "path": ["total_count"],
            "properties": [key],
            "navigation_properties": [],
        }
    ]
