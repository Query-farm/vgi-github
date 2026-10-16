"""Independently authored source contracts exercise the compiler's safety boundaries."""

from __future__ import annotations

import copy

import pytest
from graphql import build_schema, parse, validate

from vgi_github.generation.graph import compile_functions
from vgi_github.generation.schema import (
    SchemaError,
    compile_contract,
    compile_graphql_entity,
    compile_rest_entity,
)


def rest_spec():
    return {
        "paths": {
            "/repos/{owner}/{repo}/pulls/{pull_number}/reviews": {
                "get": {
                    "operationId": "pulls/list-reviews",
                    "parameters": [
                        {"name": name, "in": "path", "required": True, "schema": {"type": kind}}
                        for name, kind in (
                            ("owner", "string"),
                            ("repo", "string"),
                            ("pull_number", "integer"),
                        )
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/Review"},
                                    }
                                }
                            }
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Review": {
                    "type": "object",
                    "required": ["id", "state", "user", "tags"],
                    "properties": {
                        "id": {"type": "integer"},
                        "state": {"type": "string", "enum": ["APPROVED", "PENDING"]},
                        "submitted_at": {"type": "string", "format": "date-time", "nullable": True},
                        "user": {"$ref": "#/components/schemas/User"},
                        "tags": {"type": "array", "items": {"type": "string", "nullable": True}},
                    },
                },
                "User": {
                    "type": "object",
                    "nullable": True,
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "integer"},
                        "login": {"type": "string"},
                    },
                },
            }
        },
    }


def rest_entity():
    return {
        "name": "reviews",
        "description": "Review entities",
        "arguments": [
            {"name": "repository", "type": "VARCHAR", "nullable": False},
            {"name": "pull_request_number", "type": "BIGINT", "nullable": False},
        ],
        "columns": [
            {"name": "repository", "source_argument": "repository"},
            {"name": "id", "path": ["id"]},
            {"name": "state", "path": ["state"]},
            {"name": "submitted_at", "path": ["submitted_at"]},
            {"name": "user", "path": ["user"]},
            {"name": "tags", "path": ["tags"]},
        ],
        "grain": ["repository", "id"],
        "transport": {
            "kind": "rest",
            "operation_id": "pulls/list-reviews",
            "path_bindings": {
                "owner": {"argument": "repository", "transform": "repository_owner"},
                "repo": {"argument": "repository", "transform": "repository_name"},
                "pull_number": {"argument": "pull_request_number"},
            },
            "result_path": [],
            "pagination": {"kind": "link"},
        },
    }


SDL = """
scalar DateTime
scalar URI
type Query { repository(owner: String!, name: String!): Repository }
type Repository { labels(first: Int, after: String): LabelConnection }
type LabelConnection { nodes: [Label], pageInfo: PageInfo! }
type PageInfo { hasNextPage: Boolean!, endCursor: String }
type Label { id: ID!, name: String!, description: String, createdAt: DateTime!, url: URI! }
"""


def test_rest_input_scalar_variant_is_selected_by_declared_argument_type():
    document, entity = rest_spec(), rest_entity()
    parameter = document["paths"]["/repos/{owner}/{repo}/pulls/{pull_number}/reviews"]["get"]["parameters"][2]
    parameter["schema"] = {"oneOf": [{"type": "integer"}, {"type": "string"}]}
    assert compile_rest_entity(document, entity)["arguments"][1]["type"] == "BIGINT"
    entity["arguments"][1]["type"] = "BOOLEAN"
    with pytest.raises(SchemaError, match="exactly one scalar parameter variant"):
        compile_rest_entity(document, entity)


def test_source_ordinal_is_explicit_required_and_not_a_response_field():
    entity = rest_entity()
    entity["columns"].append({"name": "position", "source_ordinal": True})
    entity["grain"] = ["repository", "position"]
    column = compile_rest_entity(rest_spec(), entity)["columns"][-1]
    assert column["type"] == "BIGINT" and column["required"] and not column["nullable"]
    entity["columns"][-1]["path"] = ["id"]
    with pytest.raises(SchemaError, match="exactly one"):
        compile_rest_entity(rest_spec(), entity)


def test_argument_enum_rejects_invalid_definitions_and_examples():
    entity = rest_entity()
    entity["arguments"][0].update(enum=["example/alpha"], example="example/alpha")
    assert compile_rest_entity(rest_spec(), entity)["arguments"][0]["enum"] == ["example/alpha"]
    entity["arguments"][0]["example"] = "example/beta"
    with pytest.raises(SchemaError, match="example must satisfy enum"):
        compile_rest_entity(rest_spec(), entity)
    entity["arguments"][0]["enum"] = [1]
    with pytest.raises(SchemaError, match="enum requires distinct"):
        compile_rest_entity(rest_spec(), entity)


def graphql_entity():
    return {
        "name": "labels",
        "arguments": [{"name": "repository", "type": "VARCHAR"}],
        "columns": [
            {"name": "repository", "source_argument": "repository"},
            {"name": "id", "path": ["id"]},
            {"name": "name", "path": ["name"]},
            {"name": "description", "path": ["description"]},
            {"name": "created_at", "path": ["createdAt"]},
        ],
        "grain": ["repository", "id"],
        "transport": {
            "kind": "graphql",
            "field_path": ["repository", "labels"],
            "field_arguments": {
                "repository": {
                    "owner": {"argument": "repository", "transform": "repository_owner"},
                    "name": {"argument": "repository", "transform": "repository_name"},
                },
                "labels": {"first": {"literal": 100}, "after": {"cursor": True}},
            },
            "result_path": ["nodes"],
            "pagination": {"kind": "cursor", "page_info_path": ["pageInfo"]},
        },
    }


def test_rest_preserves_nested_types_enum_required_and_nullable():
    entity = compile_rest_entity(rest_spec(), rest_entity())
    cols = {column["name"]: column for column in entity["columns"]}
    assert cols["id"]["type"] == "BIGINT"
    assert cols["id"]["required"] and not cols["id"]["nullable"]
    assert cols["state"]["schema"]["enum"] == ["APPROVED", "PENDING"]
    assert cols["submitted_at"]["nullable"] and not cols["submitted_at"]["required"]
    assert cols["submitted_at"]["type"] == "TIMESTAMP WITH TIME ZONE"
    assert cols["user"]["nullable"] and cols["user"]["required"]
    assert cols["user"]["type"] == 'STRUCT("id" BIGINT, "login" VARCHAR)'
    assert cols["user"]["schema"]["fields"][1]["required"] is False
    assert cols["tags"]["type"] == "VARCHAR[]"
    assert cols["tags"]["schema"]["item"]["nullable"] is True
    assert entity["source"]["response_schema"]["references"]["#/components/schemas/User"]["nullable"]


@pytest.mark.parametrize("bad", ["recursive", "variant", "unresolved", "unknown", "wrong_type", "missing"])
def test_rest_rejects_unsupported_selected_contracts(bad):
    spec, entity = rest_spec(), rest_entity()
    user = spec["components"]["schemas"]["User"]
    if bad == "recursive":
        user["properties"]["manager"] = {"$ref": "#/components/schemas/User"}
    elif bad == "variant":
        user["properties"]["login"] = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
    elif bad == "unresolved":
        user["properties"]["login"] = {"$ref": "#/components/schemas/Missing"}
    elif bad == "unknown":
        entity["columns"][1]["path"] = ["does_not_exist"]
    elif bad == "wrong_type":
        entity["arguments"][1]["type"] = "VARCHAR"
    else:
        del entity["transport"]["path_bindings"]["repo"]
    with pytest.raises(SchemaError):
        compile_rest_entity(spec, entity)


def test_selection_bounds_recursive_graph_without_losing_source_graph():
    spec, entity = rest_spec(), rest_entity()
    spec["components"]["schemas"]["User"]["properties"]["manager"] = {"$ref": "#/components/schemas/User"}
    entity["columns"][4]["selection"] = {"id": True, "login": True}
    result = compile_rest_entity(spec, entity)
    assert len(result["columns"][4]["schema"]["fields"]) == 2
    assert (
        "manager"
        in result["source"]["response_schema"]["references"]["#/components/schemas/User"]["properties"]
    )


def test_graphql_query_is_generated_and_schema_validated():
    result = compile_graphql_entity(SDL, graphql_entity())
    transport = result["transport"]
    assert not validate(build_schema(SDL), parse(transport["document"]))
    assert transport["result_path"] == ["repository", "labels", "nodes"]
    assert transport["pagination"]["page_info_path"] == ["repository", "labels", "pageInfo"]
    assert transport["variables"]["cursor"] == {"cursor": True}
    assert transport["variables"]["repository_owner"]["transform"] == "repository_owner"
    assert "hasNextPage endCursor" in transport["document"]
    assert result["columns"][3]["nullable"]
    assert result["columns"][4]["type"] == "TIMESTAMP WITH TIME ZONE"


INPUT_OBJECT_SDL = """
type Query { user(login: String!): User }
type User { issues(first: Int, after: String, filterBy: IssueFilter): IssueConnection! }
type IssueConnection { nodes: [Issue], pageInfo: PageInfo! }
type Issue { id: ID!, title: String! }
type PageInfo { hasNextPage: Boolean!, endCursor: String }
enum IssueState { OPEN CLOSED }
enum FilterMode { INCLUDE EXCLUDE }
input IssueFilter {
    createdBy: String!
    state: IssueState = OPEN
    nested: NestedFilter
    defaulted: Int! = 1
    labels: [String!]
}
input NestedFilter { enabled: Boolean!, mode: FilterMode!, note: String, next: NestedFilter }
"""


def input_object_entity():
    return {
        "name": "issues",
        "arguments": [{"name": "user", "type": "VARCHAR", "nullable": False}],
        "columns": [{"name": "id", "path": ["id"]}, {"name": "title", "path": ["title"]}],
        "grain": ["id"],
        "transport": {
            "kind": "graphql",
            "field_path": ["user", "issues"],
            "field_arguments": {
                "user": {"login": {"argument": "user"}},
                "issues": {
                    "first": {"literal": 100},
                    "after": {"cursor": True},
                    "filterBy": {"object": {"createdBy": {"argument": "user"}}},
                },
            },
            "result_path": ["nodes"],
            "pagination": {"kind": "cursor", "page_info_path": ["pageInfo"]},
        },
    }


def test_graphql_input_object_preserves_reviewed_bindings_and_schema_defaults():
    entity = input_object_entity()
    fields = entity["transport"]["field_arguments"]["issues"]["filterBy"]["object"]
    fields["nested"] = {"object": {"enabled": {"literal": True}, "mode": {"literal": "INCLUDE"}}}
    original = copy.deepcopy(entity)
    result = compile_graphql_entity(INPUT_OBJECT_SDL, entity)
    transport = result["transport"]
    assert not validate(build_schema(INPUT_OBJECT_SDL), parse(transport["document"]))
    assert "$issues_filterBy: IssueFilter" in transport["document"]
    assert "filterBy: $issues_filterBy" in transport["document"]
    assert transport["variables"]["issues_filterBy"] == {"object": fields}
    # Omission leaves upstream defaults intact; optional keys are not filled with NULL.
    assert "defaulted" not in transport["variables"]["issues_filterBy"]["object"]
    assert "state" not in transport["variables"]["issues_filterBy"]["object"]
    assert entity == original


@pytest.mark.parametrize(
    "binding,error",
    [
        ({"object": {"createdBy": {"argument": "user"}, "typo": {"literal": 1}}}, "unknown input fields"),
        ({"object": {}}, "required input field createdBy is unmapped"),
        ({"object": {"createdBy": {"literal": 123}}}, "VARCHAR"),
        ({"object": {"createdBy": {"literal": None}}}, "literal does not match VARCHAR"),
        ({"object": []}, "at most 32 reviewed field bindings"),
        ({"argument": "user"}, "unknown keys"),
        ("user", "expected an object"),
        ({"object": {"createdBy": "user"}}, "expected an object"),
        ({"object": {f"field_{index}": {"literal": 1} for index in range(33)}}, "at most 32"),
        (
            {"object": {"createdBy": {"argument": "user"}, "labels": {"literal": ["bug"]}}},
            "scalar leaves",
        ),
    ],
)
def test_graphql_input_object_rejects_invalid_shapes_and_scalar_bindings(binding, error):
    entity = input_object_entity()
    entity["transport"]["field_arguments"]["issues"]["filterBy"] = binding
    with pytest.raises(SchemaError, match=error):
        compile_graphql_entity(INPUT_OBJECT_SDL, entity)


@pytest.mark.parametrize(
    "nested,error",
    [
        ({"enabled": {"literal": True}}, "required input field mode is unmapped"),
        (
            {"enabled": {"literal": True}, "mode": {"literal": "INVALID"}},
            "invalid GraphQL literal",
        ),
        (
            {"enabled": {"literal": True}, "mode": {"literal": "INCLUDE"}, "typo": {"literal": 1}},
            "unknown input fields",
        ),
        ({"enabled": {"literal": "true"}, "mode": {"literal": "INCLUDE"}}, "BOOLEAN"),
    ],
)
def test_graphql_input_object_checks_nested_fields_and_enums(nested, error):
    entity = input_object_entity()
    fields = entity["transport"]["field_arguments"]["issues"]["filterBy"]["object"]
    fields["nested"] = {"object": nested}
    with pytest.raises(SchemaError, match=error):
        compile_graphql_entity(INPUT_OBJECT_SDL, entity)


@pytest.mark.parametrize("kind,nullable,error", [("BIGINT", False, "VARCHAR"), ("VARCHAR", True, "NOT NULL")])
def test_graphql_input_object_checks_bound_argument_type_and_nullability(kind, nullable, error):
    entity = input_object_entity()
    entity["arguments"].append({"name": "creator", "type": kind, "nullable": nullable})
    entity["transport"]["field_arguments"]["issues"]["filterBy"]["object"]["createdBy"] = {
        "argument": "creator"
    }
    with pytest.raises(SchemaError, match=error):
        compile_graphql_entity(INPUT_OBJECT_SDL, entity)


@pytest.mark.parametrize("levels,accepted", [(7, True), (8, False)])
def test_graphql_input_object_bounds_nested_depth(levels, accepted):
    entity = input_object_entity()
    nested = None
    for _ in range(levels):
        fields = {"enabled": {"literal": True}, "mode": {"literal": "INCLUDE"}}
        if nested is not None:
            fields["next"] = nested
        nested = {"object": fields}
    entity["transport"]["field_arguments"]["issues"]["filterBy"]["object"]["nested"] = nested
    if accepted:
        compile_graphql_entity(INPUT_OBJECT_SDL, entity)
    else:
        with pytest.raises(SchemaError, match="exceeds eight object levels"):
            compile_graphql_entity(INPUT_OBJECT_SDL, entity)


@pytest.mark.parametrize(
    "bad", ["field", "argument", "missing_required", "mutation", "wrong_literal", "cursor"]
)
def test_graphql_rejects_invalid_selections(bad):
    entity = graphql_entity()
    transport = entity["transport"]
    if bad == "field":
        entity["columns"][1]["path"] = ["absent"]
    elif bad == "argument":
        transport["field_arguments"]["labels"]["unknown"] = {"literal": 1}
    elif bad == "missing_required":
        del transport["field_arguments"]["repository"]["owner"]
    elif bad == "mutation":
        transport["field_path"] = ["createLabel"]
    elif bad == "wrong_literal":
        transport["field_arguments"]["labels"]["first"] = {"literal": "one"}
    else:
        del transport["field_arguments"]["labels"]["after"]
    with pytest.raises(SchemaError):
        compile_graphql_entity(SDL, entity)


def test_contract_is_deterministic_does_not_mutate_overlay_and_rejects_typos():
    overlay = {"version": 1, "entities": [rest_entity(), graphql_entity()]}
    original = copy.deepcopy(overlay)
    first = compile_contract({"api.github.com": rest_spec()}, SDL, overlay)
    assert first == compile_contract({"api.github.com": rest_spec()}, SDL, overlay)
    assert overlay == original
    assert first["format"] == "vgi-github-entities"
    overlay["entities"][0]["colums"] = []
    with pytest.raises(SchemaError, match="unknown keys"):
        compile_contract({"api.github.com": rest_spec()}, SDL, overlay)


def test_singleton_common_variant_selection_requires_compatible_field_types():
    spec, entity = rest_spec(), rest_entity()
    operation = next(iter(spec["paths"].values()))["get"]
    operation["responses"]["200"]["content"]["application/json"]["schema"] = {
        "oneOf": [
            {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}},
            {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "integer"}, "extra": {"type": "string"}},
            },
        ]
    }
    entity["columns"] = [{"name": "id", "path": ["id"]}]
    entity["grain"] = ["id"]
    entity["transport"].update(result_shape="object", pagination={"kind": "none"})
    with pytest.raises(SchemaError, match="variant"):
        compile_rest_entity(spec, entity)
    entity["transport"]["response_variants"] = "common_fields"
    assert compile_rest_entity(spec, entity)["columns"][0]["type"] == "BIGINT"
    operation["responses"]["200"]["content"]["application/json"]["schema"]["oneOf"][1]["properties"]["id"][
        "type"
    ] = "string"
    with pytest.raises(SchemaError, match="identical selected concrete types"):
        compile_rest_entity(spec, entity)


def scoped_reviews():
    """Use three independent nullable resource inputs against one required source input."""
    contract = {"entities": [compile_rest_entity(rest_spec(), rest_entity())]}

    def leaf(name):
        return {
            "entity": "reviews",
            "arguments": {"repository": {"parameter": name}, "pull_request_number": {"literal": 7}},
        }

    overlay = {
        "functions": [
            {
                "name": "selected_reviews",
                "arguments": [
                    {"name": name, "type": "VARCHAR", "nullable": True, "default": None}
                    for name in ["first", "second", "third"]
                ],
                "columns": [{"name": "id", "source_stage": "selected", "source_column": "id"}],
                "grain": ["id"],
                "traversal": {
                    "stages": [{"name": "selected", "scope": "selection"}],
                    "output_stage": "selected",
                },
                "semantics": {},
            }
        ],
        "scopes": {
            "selection": {
                "exclusive_parameters": ["first", "second", "third"],
                "select": {
                    "parameter": "first",
                    "if_present": leaf("first"),
                    "if_absent": {
                        "parameter": "second",
                        "if_present": leaf("second"),
                        "if_absent": leaf("third"),
                    },
                },
            }
        },
    }
    return contract, overlay


def test_three_way_scope_infers_last_nonnull_parameter_without_mutating_overlay():
    contract, overlay = scoped_reviews()
    original = copy.deepcopy(overlay)
    compiled = compile_functions(contract, overlay)
    assert compiled["functions"][0]["columns"][0]["type"] == "BIGINT"
    assert compiled["scopes"] == overlay["scopes"]
    assert overlay == original


def test_generated_functions_do_not_declare_or_default_output_caps():
    contract, overlay = scoped_reviews()
    compiled = compile_functions(contract, overlay)
    assert "limits" not in compiled["functions"][0]
    overlay["functions"][0]["limits"] = {"max_output_rows": 1}
    with pytest.raises(SchemaError, match="unknown keys.*limits"):
        compile_functions(contract, overlay)


def test_singleton_scope_makes_shared_nullable_parameter_required():
    contract, overlay = scoped_reviews()
    scope = overlay["scopes"]["selection"]
    scope["exclusive_parameters"] = ["first"]
    scope["select"] = scope["select"]["if_present"]
    assert compile_functions(contract, overlay)["functions"][0]["arguments"][0]["nullable"] is True


@pytest.mark.parametrize("branch", ["if_present", "if_absent"])
def test_scope_does_not_infer_unselected_nullable_parameters(branch):
    contract, overlay = scoped_reviews()
    selection = overlay["scopes"]["selection"]["select"]
    if branch == "if_present":
        selection[branch]["arguments"]["repository"] = {"parameter": "third"}
    else:
        selection[branch] = {
            "entity": "reviews",
            "arguments": {"repository": {"parameter": "third"}, "pull_request_number": {"literal": 7}},
        }
    with pytest.raises(SchemaError, match="NOT NULL"):
        compile_functions(contract, overlay)


def test_scope_rejects_nullable_fallback_without_exactly_one_constraint():
    contract, overlay = scoped_reviews()
    del overlay["scopes"]["selection"]["exclusive_parameters"]
    with pytest.raises(SchemaError, match="NOT NULL"):
        compile_functions(contract, overlay)


def test_scope_rejects_contradictory_dependencies_and_repeated_decisions():
    contract, overlay = scoped_reviews()
    overlay["scopes"]["selection"]["requires_parameters"] = {"first": ["second"]}
    with pytest.raises(SchemaError, match="contradict"):
        compile_functions(contract, overlay)
    del overlay["scopes"]["selection"]["requires_parameters"]
    selection = overlay["scopes"]["selection"]["select"]
    selection["if_present"] = copy.deepcopy(selection)
    with pytest.raises(SchemaError, match="already fixed"):
        compile_functions(contract, overlay)


def test_scope_dependencies_prove_transitive_required_bindings():
    contract, overlay = scoped_reviews()
    scope = overlay["scopes"]["selection"]
    scope.pop("exclusive_parameters")
    scope["requires_parameters"] = {"first": ["second"], "second": ["third"]}
    scope["select"]["if_present"]["arguments"]["repository"] = {"parameter": "third"}
    scope["select"]["if_absent"] = {
        "entity": "reviews",
        "arguments": {"repository": {"literal": "public/repository"}, "pull_request_number": {"literal": 7}},
    }
    assert compile_functions(contract, overlay)["functions"][0]["name"] == "selected_reviews"


def test_resolver_branches_preserve_prior_parameter_presence():
    contract, overlay = scoped_reviews()
    resolver = copy.deepcopy(contract["entities"][0])
    resolver["name"] = "lookup"
    resolver["transport"]["result_shape"] = "object"
    contract["entities"].append(resolver)
    selection = overlay["scopes"]["selection"]["select"]
    leaf = selection["if_absent"]["if_absent"]
    selection["if_absent"]["if_absent"] = {
        "resolve": {**copy.deepcopy(leaf), "entity": "lookup"},
        "field": "state",
        "cases": {"APPROVED": leaf, "PENDING": copy.deepcopy(leaf)},
    }
    assert compile_functions(contract, overlay)["functions"][0]["grain"] == ["id"]


@pytest.mark.parametrize(
    "property_name,value,error",
    [
        ("exclusive_parameters", "first", "distinct public"),
        ("exclusive_parameters", ["first", "first"], "distinct public"),
        ("exclusive_parameters", [["first"]], "distinct public"),
        ("requires_parameters", [], "named parameter object"),
        ("requires_parameters", {"first": "second"}, "declared distinct"),
        ("requires_parameters", {"first": ["second", "second"]}, "declared distinct"),
    ],
)
def test_scope_constraints_are_validated_as_structured_contracts(property_name, value, error):
    contract, overlay = scoped_reviews()
    overlay["scopes"]["selection"][property_name] = value
    with pytest.raises(SchemaError, match=error):
        compile_functions(contract, overlay)


ACTOR_SDL = (
    SDL
    + """
interface Actor { login: String!, aliases: [String!]!, profile: Profile }
type Person implements Actor { login: String!, email: String, aliases: [String!]!, profile: Profile }
type Bot implements Actor { login: String!, aliases: [String!]!, profile: Profile }
type Profile { name: String! }
union Account = Person | Bot
extend type Label { author: Actor, account: Account }
"""
)


def actor_entity():
    entity = graphql_entity()
    entity["arguments"].append({"name": "user", "type": "VARCHAR"})
    entity["columns"].append({"name": "author_login", "path": ["author", "login"]})
    entity["policy"] = {
        "row_assertions": [{"column": "author_login", "argument": "user", "comparison": "github_login"}]
    }
    return entity


def test_graphql_common_interface_scalar_is_nullable_and_retains_population_assertion():
    entity = actor_entity()
    result = compile_graphql_entity(ACTOR_SDL, entity)
    author = next(column for column in result["columns"] if column["name"] == "author_login")
    assert author["type"] == "VARCHAR" and author["nullable"] and author["required"]
    assert "author { login }" in result["transport"]["document"]
    assert result["policy"] == entity["policy"]
    assert not validate(build_schema(ACTOR_SDL), parse(result["transport"]["document"]))


@pytest.mark.parametrize(
    "path,error",
    [
        (["author", "email"], "unknown GraphQL selected field"),
        (["author", "aliases"], "VARCHAR column"),
    ],
)
def test_graphql_interface_support_rejects_undeclared_fields_and_incompatible_actor_assertions(path, error):
    entity = actor_entity()
    entity["columns"][-1]["path"] = path
    with pytest.raises(SchemaError, match=error):
        compile_graphql_entity(ACTOR_SDL, entity)


@pytest.mark.parametrize(
    "path,expected",
    [
        (["author", "profile", "name"], "VARCHAR"),
        (["author", "aliases"], "VARCHAR[]"),
        (["account", "login"], "VARCHAR"),
    ],
)
def test_graphql_common_abstract_paths_keep_exact_types_and_parent_nullability(path, expected):
    entity = actor_entity()
    entity.pop("policy")
    entity["columns"][-1]["path"] = path
    compiled = compile_graphql_entity(ACTOR_SDL, entity)
    assert compiled["columns"][-1]["type"] == expected
    assert compiled["columns"][-1]["nullable"]
    assert validate(build_schema(ACTOR_SDL), parse(compiled["transport"]["document"])) == []


@pytest.mark.parametrize(
    "assertion,error",
    [
        ({"column": "unknown", "argument": "user", "comparison": "github_login"}, "VARCHAR column"),
        ({"column": "author_login", "argument": "unknown", "comparison": "github_login"}, "VARCHAR column"),
        ({"column": "created_at", "argument": "user", "comparison": "github_login"}, "VARCHAR column"),
        ({"column": "author_login", "argument": "user", "comparison": "sql"}, "unsupported row assertion"),
        (
            {"column": "author_login", "argument": "user", "comparison": "github_login", "sql": "TRUE"},
            "unknown keys",
        ),
    ],
)
def test_row_assertions_reject_unknown_fields_types_and_operators(assertion, error):
    entity = actor_entity()
    entity["policy"]["row_assertions"] = [assertion]
    with pytest.raises(SchemaError, match=error):
        compile_graphql_entity(ACTOR_SDL, entity)


def test_row_assertions_require_nonnull_arguments_and_reject_duplicate_rules():
    entity = actor_entity()
    entity["arguments"][-1]["nullable"] = True
    with pytest.raises(SchemaError, match="non-null VARCHAR argument"):
        compile_graphql_entity(ACTOR_SDL, entity)
    entity["arguments"][-1]["nullable"] = False
    entity["policy"]["row_assertions"] *= 2
    with pytest.raises(SchemaError, match="duplicate row assertion"):
        compile_graphql_entity(ACTOR_SDL, entity)


@pytest.mark.parametrize("policy", [{"unreviewed": True}, {"row_assertions": []}, {"row_assertions": {}}])
def test_row_assertion_policy_requires_exact_nonempty_contract(policy):
    entity = actor_entity()
    entity["policy"] = policy
    with pytest.raises(SchemaError, match="unknown keys|nonempty list"):
        compile_graphql_entity(ACTOR_SDL, entity)
