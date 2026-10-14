"""Limited independent checks for reviewed policies and reproducible pilot artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
from graphql import build_schema, parse, validate

from scripts import generate_semantic_catalog as generator
from vgi_github.generation.artifacts import emit_artifacts, validate_semantics
from vgi_github.generation.overlay import load_overlay, overlay_bytes
from vgi_github.generation.schema import compile_contract, compile_graphql_entity

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pilot():
    overlay = load_overlay(ROOT / "generation/pilot.json")
    overlay_data = overlay_bytes(overlay)
    specs, sdl, lock = generator.locked_inputs(ROOT, overlay)
    contract = compile_contract(specs, sdl, overlay)
    provenance = {
        "overlay_sha256": hashlib.sha256(overlay_data).hexdigest(),
        "source_lock_sha256": hashlib.sha256(
            (ROOT / "generation/sources.lock.json").read_bytes()
        ).hexdigest(),
        "rest_revision": lock["rest_revision"],
        "graphql_revision": lock["graphql_revision"],
    }
    return overlay, contract, provenance


def test_artifacts_are_deterministic_current_and_package_contents_are_linked(pilot):
    overlay, contract, provenance = pilot
    output = emit_artifacts(contract, overlay, provenance)
    assert output == emit_artifacts(deepcopy(contract), deepcopy(overlay), deepcopy(provenance))
    generator.write_outputs(ROOT, output, check=True)
    package = json.loads(output["models/generated-pilot/github-generated.package.json"])
    document = package["documents"][0]
    assert document["content"] == output["models/generated-pilot/github-generated.crossfield.json"]
    assert document["sha256"] == hashlib.sha256(document["content"].encode()).hexdigest()
    assert package["reports"] == []
    assert len(package["documents"]) == 1
    model = json.loads(document["content"])
    assert set(model["metrics"]) == set(overlay.get("crossfield", {}).get("metrics", {})) | {
        "repository_count",
        "pull_request_count",
        "merged_prs",
        "median_merge_hours",
        "submitted_review_count",
        "approved_review_count",
        "label_count",
        "organization_count",
        "user_count",
        "organization_member_count",
        "team_count",
        "team_membership_count",
        "authored_pr_count",
        "authored_merged_pr_count",
        "authored_median_merge_hours",
        "authored_pr_active_days",
        "authored_pr_repository_count",
        "authored_issue_count",
        "authored_issue_active_days",
        "authored_issue_repository_count",
        "authored_discussion_count",
        "authored_discussion_active_days",
        "authored_discussion_repository_count",
        "authored_issue_comment_count",
        "authored_issue_comment_active_days",
        "authored_issue_comment_repository_count",
        "authored_discussion_comment_count",
        "authored_discussion_comment_active_days",
        "authored_discussion_comment_repository_count",
        "authored_discussion_comment_unknown_repository_count",
        "authored_commit_comment_count",
        "authored_commit_comment_active_days",
        "authored_commit_comment_repository_count",
    }
    assert model["invocations"]["sources"]["pull_request_reviews"]["function"]["schema"] == "generated"
    coverage = json.loads(output["models/generated-pilot/coverage.json"])
    assert coverage["complete_worker_replacement"] is False
    assert set(coverage["sources"]) == {
        "account_lookup",
        "repository_lookup",
        "organization_repositories",
        "user_repositories",
        "pull_request_list",
        "pull_request_lookup",
        "reviews_source",
        "labels_source",
        "organization_lookup",
        "user_profile_lookup",
        "organization_members_source",
        "teams_source",
        "team_members_source",
        "authored_pull_requests_source",
        "authored_issues_source",
        "authored_discussions_source",
        "authored_issue_comments_source",
        "authored_discussion_comments_source",
        "authored_commit_comments_source",
    }
    assert {entity["name"] for entity in coverage["entities"]} == {
        "repositories",
        "pull_requests",
        "pull_request_reviews",
        "repository_labels",
        "organizations",
        "users",
        "organization_memberships",
        "teams",
        "team_memberships",
        "authored_pull_requests",
        "authored_issues",
        "authored_discussions",
        "authored_issue_comments",
        "authored_discussion_comments",
        "authored_commit_comments",
    }
    assert all(source["profile"] == "producer_sync_v1" for source in model["invocations"]["sources"].values())
    assert model["invocations"]["input_contracts"] == {}
    assert model["semantic_query"]["parameters"]["owner"]["default"] is None
    assert model["semantic_query"]["parameters"]["repository"]["default"] is None
    assert model["policy"]["field_semantics"]["repositories.repository"]["sql_name"] == "repository_name"
    assert "pull_request_reviews.author_login" not in model["policy"]["dimensions"]
    assert model["policy"]["metric_semantics"]["median_merge_hours"]["additivity"] == "non_additive"
    assert {relationship["name"] for relationship in model["relationships"]} == {
        "pull_requests_to_repositories",
        "reviews_to_pull_requests",
        "labels_to_repositories",
        "repositories_to_organizations",
        "memberships_to_organizations",
        "teams_to_organizations",
        "team_memberships_to_teams",
        "authored_pull_requests_to_users",
        "authored_issues_to_users",
        "authored_discussions_to_users",
        "authored_issue_comments_to_users",
        "authored_discussion_comments_to_users",
        "authored_commit_comments_to_users",
    }
    assert "imports" not in model
    assert {metadata["key_evidence"] for metadata in model["policy"]["dataset_semantics"].values()} == {
        "declared"
    }
    assert {metadata["key_evidence"] for metadata in model["policy"]["relationship_semantics"].values()} == {
        "declared"
    }


def test_reports_are_optional_conveniences(pilot):
    overlay, contract, provenance = pilot
    entity = contract["functions"][0]
    entity["semantics"]["detail_report"] = {"name": "inventory", "comment": "Optional repository inventory."}
    package = json.loads(
        emit_artifacts(contract, overlay, provenance)["models/generated-pilot/github-generated.package.json"]
    )
    assert [report["name"] for report in package["reports"]] == ["inventory"]


def test_semantic_parameters_publish_typed_examples_without_turning_them_into_defaults(pilot):
    overlay, contract, provenance = pilot
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    parameters = model["semantic_query"]["parameters"]
    examples = {
        "organization": "Query-farm",
        "owner": "Query-farm",
        "repository": "Query-farm/crossfield",
        "user": "octocat",
        "pull_request_number": 1,
        "users": [{"login": "octocat"}, {"login": "hubot"}],
        "repositories": [{"repository": "Query-farm/crossfield"}, {"repository": "Query-farm/vgi"}],
    }
    assert {name: value["example"] for name, value in parameters.items()} == examples
    for name in ("organization", "owner", "repository", "user"):
        assert parameters[name]["type"] == "VARCHAR"
        assert parameters[name]["non_empty"] is True
    assert parameters["pull_request_number"]["minimum"] == 1
    assert "non_empty" not in parameters["pull_request_number"]
    assert parameters["users"]["type"] == 'STRUCT("login" VARCHAR)[]'
    assert parameters["repositories"]["type"] == 'STRUCT("repository" VARCHAR)[]'
    for name in parameters:
        assert parameters[name]["nullable"] is True and parameters[name]["default"] is None
    package = json.loads(output["models/generated-pilot/github-generated.package.json"])
    assert package["revision"] == 8
    assert model["name"] == "github" and model["id"] == "queryfarm.github.generated_pilot"
    assert package["package_id"] == "9952d457-873c-5e13-965e-07fbdc1cfe2b"
    for name, source in model["invocations"]["sources"].items():
        assert source["dataset"]["id"] == f"queryfarm.github.generated_pilot/datasets/{name}"


def test_scope_constraints_are_coalesced_deterministically_and_apply_only_to_relevant_datasets(pilot):
    overlay, contract, provenance = pilot

    def constraints(value):
        return json.loads(
            emit_artifacts(value, overlay, provenance)[
                "models/generated-pilot/github-generated.crossfield.json"
            ]
        )["semantic_query"]["constraints"]

    expected = [
        {
            "kind": "exactly_one",
            "parameters": ["organization"],
            "datasets": ["organization_memberships", "organizations", "team_memberships", "teams"],
        },
        {
            "kind": "exactly_one",
            "parameters": ["organization", "owner", "repositories", "repository"],
            "datasets": ["pull_request_reviews", "pull_requests", "repositories", "repository_labels"],
        },
        {
            "kind": "exactly_one",
            "parameters": ["user", "users"],
            "datasets": ["authored_commit_comments", "authored_discussion_comments", "authored_discussions",
                         "authored_issue_comments", "authored_issues", "authored_pull_requests", "users"],
        },
        {
            "kind": "requires",
            "when": "pull_request_number",
            "parameters": ["repository"],
            "datasets": ["pull_request_reviews", "pull_requests"],
        },
    ]
    assert constraints(contract) == expected
    contract["functions"].reverse()
    contract["scopes"]["repositories"]["exclusive_parameters"].reverse()
    assert constraints(contract) == expected
    # User-only queries cannot acquire unrelated repository or organization requirements.
    assert all(not {"users", "authored_pull_requests"}.intersection(rule["datasets"])
               for rule in expected if rule["parameters"] != ["user", "users"])


def test_generator_rejects_unrepresentable_minimum_string_length_instead_of_weakening_it(pilot):
    overlay, contract, provenance = pilot
    contract["functions"][0]["arguments"][0]["min_length"] = 2
    with pytest.raises(ValueError, match="cannot preserve owner min_length 2"):
        emit_artifacts(contract, overlay, provenance)


@pytest.mark.parametrize(
    "name,example,error",
    [
        ("owner", None, "non-NULL scalar matching VARCHAR"),
        ("owner", 123, "non-NULL scalar matching VARCHAR"),
        ("owner", ["Query-farm"], "non-NULL scalar matching VARCHAR"),
        ("owner", {"value": "Query-farm"}, "non-NULL scalar matching VARCHAR"),
        ("owner", " ", "satisfy min_length"),
        ("pull_request_number", "1", "non-NULL scalar matching BIGINT"),
        ("pull_request_number", True, "non-NULL scalar matching BIGINT"),
        ("pull_request_number", 2**63, "non-NULL scalar matching BIGINT"),
        ("pull_request_number", 0, "satisfy minimum"),
    ],
)
def test_parameter_examples_must_satisfy_types_and_declared_bounds(pilot, name, example, error):
    overlay, _, _ = pilot
    function = next(
        entity for entity in overlay["functions"] if any(arg["name"] == name for arg in entity["arguments"])
    )
    next(arg for arg in function["arguments"] if arg["name"] == name)["example"] = example
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match=error):
        compile_contract(specs, sdl, overlay)


def test_shared_semantic_parameter_examples_must_agree(pilot):
    overlay, contract, provenance = pilot
    next(arg for arg in contract["functions"][0]["arguments"] if arg["name"] == "owner")["example"] = "other"
    with pytest.raises(ValueError, match="Inconsistent shared semantic parameter owner"):
        emit_artifacts(contract, overlay, provenance)


def test_discovery_example_uses_the_qualified_invocation_name(pilot):
    overlay, contract, provenance = pilot
    readme = emit_artifacts(contract, overlay, provenance)["models/generated-pilot/README.md"]
    assert "AND invocation_name='engineering.semantic.github' ORDER BY ordinal;" in readme
    assert "invocation_name='github'" not in readme
    assert "[research.sql](research.sql)" in readme
    assert "weekly periods start on ISO Monday" in readme


def test_missing_count_populations_are_zero_but_median_stays_null(pilot):
    overlay, contract, provenance = pilot
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    metrics = model["policy"]["metric_semantics"]
    for entity in contract["functions"]:
        for recipe in entity["semantics"]["metrics"]:
            assert metrics[recipe["name"]]["missing"] == (
                "zero" if recipe["kind"] in {"count", "count_distinct"} else "null"
            )
    assert metrics["approved_review_count"]["population"].endswith("state = 'APPROVED'")
    assert metrics["median_merge_hours"]["missing"] == "null"


@pytest.mark.parametrize("field", ["repository_node_id", "authored_pr_created_day", "authored_pr_merged_day"])
def test_distinct_count_recipes_preserve_scalar_grain_and_zero_empty_populations(pilot, field):
    overlay, contract, provenance = pilot
    entity = next(entity for entity in contract["functions"] if entity["name"] == "authored_pull_requests")
    entity["semantics"]["metrics"].append(
        {
            "name": "unique_values",
            "kind": "count_distinct",
            "field": field,
            "where": {"field": "merged_at", "op": "is_not_null"},
            "comment": (
                "Distinct non-NULL values in the merged PR cohort; overlapping groups cannot be summed."
            ),
        }
    )
    model = json.loads(
        emit_artifacts(contract, overlay, provenance)[
            "models/generated-pilot/github-generated.crossfield.json"
        ]
    )
    assert model["metrics"]["unique_values"]["expression"] == (
        f"COUNT(DISTINCT authored_pull_requests.{field})"
    )
    metric = model["policy"]["metric_semantics"]["unique_values"]
    assert metric["additivity"] == "non_additive"
    assert metric["missing"] == "zero"
    assert metric["population"] == "authored_pull_requests.merged_at IS NOT NULL"
    assert "unit" not in metric


@pytest.mark.parametrize("field", [None, "unknown_field", "user"])
def test_distinct_count_rejects_missing_unknown_or_nested_fields(pilot, field):
    overlay, contract, provenance = pilot
    entity = next(entity for entity in contract["functions"] if entity["name"] == "pull_request_reviews")
    entity["semantics"]["metrics"].append(
        {
            "name": "invalid_distinct",
            "kind": "count_distinct",
            **({"field": field} if field is not None else {}),
            "comment": "An invalid measure must not be emitted.",
        }
    )
    with pytest.raises(ValueError, match="Distinct count requires a declared scalar field"):
        emit_artifacts(contract, overlay, provenance)


def _category_field(contract):
    entity = next(entity for entity in contract["functions"] if entity["name"] == "authored_pull_requests")
    field = {
        "name": "test_category",
        "kind": "text_category",
        "source": "title",
        "rules": [
            {"id": "exact_doc", "match": "exact", "value": "DOCS: readme", "category": "readme"},
            {"id": "documentation", "match": "prefix", "value": "docs:", "category": "documentation"},
            {"id": "quoted", "match": "contains", "value": "user's", "category": "user's change"},
        ],
        "otherwise": "unclassified",
        "comment": "Title convention only; inspect the original title as evidence. First matching rule wins.",
    }
    entity["semantics"].setdefault("derived_fields", []).append(field)
    entity["semantics"]["detail_fields"].append("test_category")
    entity["semantics"]["dimensions"].append("test_category")
    return entity, field


def test_text_categories_preserve_order_literal_escaping_unmatched_values_and_source_evidence(pilot):
    overlay, contract, provenance = pilot
    entity, _ = _category_field(contract)
    # A nullable source still yields the explicit unmatched category, never a made-up classification.
    next(column for column in entity["columns"] if column["name"] == "title")["nullable"] = True
    outputs = emit_artifacts(contract, overlay, provenance)
    model = json.loads(outputs["models/generated-pilot/github-generated.crossfield.json"])
    source = model["invocations"]["sources"]["authored_pull_requests"]
    field = source["dataset"]["fields"]["test_category"]
    assert field == {
        "dimension": True,
        "type": "VARCHAR",
        "expression": "CASE WHEN LOWER(authored_pull_requests.title) = LOWER('DOCS: readme') THEN 'readme' "
        "WHEN STARTSWITH(LOWER(authored_pull_requests.title), LOWER('docs:')) THEN 'documentation' "
        "WHEN CONTAINS(LOWER(authored_pull_requests.title), LOWER('user''s')) THEN 'user''s change' "
        "ELSE 'unclassified' END",
    }
    assert "authored_pull_requests.title" in model["policy"]["detail_fields"]
    assert "authored_pull_requests.test_category" in model["policy"]["filter_dimensions"]
    assert "test_category" not in {column["name"] for column in source["result_columns"]}
    assert "| `test_category` | `VARCHAR` | no |" in outputs["models/generated-pilot/README.md"]


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("unknown_source", "VARCHAR source"),
        ("numeric_source", "VARCHAR source"),
        ("hidden_evidence", "exposed as a detail field"),
        ("raw_sql", "reviewed source"),
        ("no_fallback", "explicit otherwise"),
        ("blank_fallback", "otherwise category"),
        ("empty_rules", "between 1 and 32"),
        ("too_many_rules", "between 1 and 32"),
        ("duplicate_rule_id", "IDs must be unique"),
        ("regex", "only support exact, prefix and contains"),
        ("empty_match", "match values must be nonempty"),
        ("empty_category", "labels must be nonempty"),
    ],
)
def test_text_category_recipes_reject_unbounded_or_unreviewed_classification(pilot, mutation, error):
    overlay, contract, provenance = pilot
    entity, field = _category_field(contract)
    if mutation == "unknown_source":
        field["source"] = "invented"
    elif mutation == "numeric_source":
        field["source"] = "pull_request_number"
    elif mutation == "hidden_evidence":
        entity["semantics"]["detail_fields"].remove("title")
    elif mutation == "raw_sql":
        field["expression"] = "CURRENT_USER"
    elif mutation == "no_fallback":
        field.pop("otherwise")
    elif mutation == "blank_fallback":
        field["otherwise"] = " "
    elif mutation == "empty_rules":
        field["rules"] = []
    elif mutation == "too_many_rules":
        field["rules"] *= 11
    elif mutation == "duplicate_rule_id":
        field["rules"][1]["id"] = field["rules"][0]["id"]
    elif mutation == "regex":
        field["rules"][0]["match"] = "regex"
    elif mutation == "empty_match":
        field["rules"][0]["value"] = ""
    else:
        field["rules"][0]["category"] = ""
    with pytest.raises(ValueError, match=error):
        emit_artifacts(contract, overlay, provenance)


@pytest.mark.parametrize("granularity", ["day", "week", "month"])
def test_utc_period_recipes_emit_calendar_start_dates_and_preserve_nullability(pilot, granularity):
    overlay, contract, provenance = pilot
    entity = next(entity for entity in contract["functions"] if entity["name"] == "pull_requests")
    field = next(
        field for field in entity["semantics"]["derived_fields"] if field["name"] == "pull_request_merged_day"
    )
    field["granularity"] = granularity
    outputs = emit_artifacts(contract, overlay, provenance)
    model = json.loads(outputs["models/generated-pilot/github-generated.crossfield.json"])
    emitted = model["invocations"]["sources"]["pull_requests"]["dataset"]["fields"]["pull_request_merged_day"]
    day = "CAST(pull_requests.merged_at AS DATE)"
    assert emitted["expression"] == (
        day if granularity == "day" else f"CAST(DATE_TRUNC('{granularity}', {day}) AS DATE)"
    )
    assert emitted["timezone"] == "UTC" and emitted["calendar"] == "gregorian"
    assert emitted["type"] == "DATE" and emitted["granularity"] == granularity
    assert "| `pull_request_merged_day` | `DATE` | yes |" in outputs["models/generated-pilot/README.md"]
    field["granularity"] = "year"
    with pytest.raises(ValueError, match="only support day, week and month"):
        emit_artifacts(contract, overlay, provenance)


@pytest.mark.parametrize(
    "entity_name,source_name,day_name",
    [
        ("pull_requests", "created_at", "pull_request_created_day"),
        ("pull_requests", "merged_at", "pull_request_merged_day"),
        ("pull_request_reviews", "submitted_at", "review_submitted_day"),
    ],
)
def test_date_dimensions_are_model_owned_utc_casts(pilot, entity_name, source_name, day_name):
    overlay, contract, provenance = pilot
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    source = model["invocations"]["sources"][entity_name]
    assert source["dataset"]["fields"][day_name] == {
        "dimension": True,
        "expression": f"CAST({entity_name}.{source_name} AS DATE)",
        "type": "DATE",
        "is_time": True,
        "timezone": "UTC",
        "calendar": "gregorian",
        "granularity": "day",
    }
    full_name = entity_name + "." + day_name
    for approval in ("dimensions", "filter_dimensions", "detail_fields"):
        assert full_name in model["policy"][approval]
    assert model["policy"]["field_semantics"][full_name]["sql_name"] == day_name
    # Deriving a DATE must not pretend the worker returned one or change its schema.
    assert day_name not in {column["name"] for column in source["result_columns"]}
    worker = json.loads(output["vgi_github/generated_entities.json"])
    entity = next(entity for entity in worker["functions"] if entity["name"] == entity_name)
    assert day_name not in {column["name"] for column in entity["columns"]}
    assert next(column for column in entity["columns"] if column["name"] == source_name)["type"] == (
        "TIMESTAMP WITH TIME ZONE"
    )


@pytest.mark.parametrize("nullable,required", [(False, True), (True, True), (False, False)])
def test_date_nullability_preserves_nullable_and_optional_source_contracts(pilot, nullable, required):
    overlay, contract, provenance = pilot
    entity = next(entity for entity in contract["functions"] if entity["name"] == "pull_requests")
    source = next(column for column in entity["columns"] if column["name"] == "created_at")
    source["nullable"], source["required"] = nullable, required
    output = emit_artifacts(contract, overlay, provenance)
    expected = "yes" if nullable or not required else "no"
    assert (
        f"| `pull_request_created_day` | `DATE` | {expected} |" in output["models/generated-pilot/README.md"]
    )
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    field = model["invocations"]["sources"]["pull_requests"]["dataset"]["fields"]["pull_request_created_day"]
    # CAST preserves NULL; there is no fabricated epoch, current date or string fallback.
    assert field["expression"] == "CAST(pull_requests.created_at AS DATE)"


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("missing_timezone", "explicit UTC timezone"),
        ("different_timezone", "explicit UTC timezone"),
        ("sql_expression", "reviewed date recipe"),
        ("unknown_source", "timestamp-with-time-zone"),
        ("text_source", "timestamp-with-time-zone"),
        ("naive_timestamp", "timestamp-with-time-zone"),
        ("duplicate", "distinct and documented"),
        ("undocumented", "distinct and documented"),
    ],
)
def test_date_recipes_reject_unapproved_type_timezone_or_expression(pilot, mutation, error):
    overlay, contract, _ = pilot
    entity = next(entity for entity in contract["functions"] if entity["name"] == "pull_requests")
    field = next(
        field
        for field in entity["semantics"]["derived_fields"]
        if field["name"] == "pull_request_created_day"
    )
    if mutation == "missing_timezone":
        field.pop("timezone")
    elif mutation == "different_timezone":
        field["timezone"] = "America/New_York"
    elif mutation == "sql_expression":
        field["expression"] = "CURRENT_DATE"
    elif mutation == "unknown_source":
        field["source"] = "invented"
    elif mutation == "text_source":
        field["source"] = "author_login"
    elif mutation == "naive_timestamp":
        next(column for column in entity["columns"] if column["name"] == "created_at")["type"] = "TIMESTAMP"
    elif mutation == "duplicate":
        field["name"] = "created_at"
    else:
        field["comment"] = " "
    with pytest.raises(ValueError, match=error):
        validate_semantics(contract, overlay)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("missing_mapping", "exactly its declared"),
        ("unknown_stage", "earlier stage"),
        ("unknown_parameter", "undeclared parameter"),
        ("incompatible_scope", "same named entity columns"),
        ("nullable_mapping", "NOT NULL"),
        ("bad_default", "NULL default"),
    ],
)
def test_connected_scope_contracts_reject_incompatible_changes(pilot, mutation, error):
    overlay, _, _ = pilot
    if mutation == "missing_mapping":
        overlay["scopes"]["repositories"]["select"]["if_present"]["arguments"] = {}
    elif mutation == "unknown_stage":
        overlay["functions"][2]["traversal"]["stages"][-1]["arguments"]["pull_request_number"]["stage"] = (
            "future"
        )
    elif mutation == "unknown_parameter":
        overlay["scopes"]["repositories"]["select"]["parameter"] = "unknown"
    elif mutation == "incompatible_scope":
        overlay["entities"][2]["columns"].pop()
    elif mutation == "nullable_mapping":
        overlay["scopes"]["repositories"].pop("exclusive_parameters")
    elif mutation == "bad_default":
        overlay["functions"][0]["arguments"][0]["default"] = "someone"
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match=error):
        compile_contract(specs, sdl, overlay)


def test_review_role_and_repository_identity_are_explicit(pilot):
    _, contract, _ = pilot
    shared = contract["shared_dimensions"]
    assert "pull_requests.author_id" in shared["github.pr_author.account_id.v1"]
    assert "pull_request_reviews.reviewer_id" in shared["github.reviewer.account_id.v1"]
    assert set(shared["github.pr_author.account_id.v1"]).isdisjoint(shared["github.reviewer.account_id.v1"])
    reviews = next(entity for entity in contract["functions"] if entity["name"] == "pull_request_reviews")
    columns = {column["name"]: column for column in reviews["columns"]}
    assert columns["repository"]["source_stage"] == "repositories"
    assert columns["author_login"]["source_stage"] == "pull_requests"
    assert columns["reviewer_login"]["source_stage"] == "reviews"


def test_disconnected_traversal_cannot_multiply_child_populations(pilot):
    overlay, _, _ = pilot
    overlay["functions"][2]["traversal"]["stages"][-1]["arguments"]["pull_request_number"] = {"literal": 1}
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match="immediate parent"):
        compile_contract(specs, sdl, overlay)


def test_cyclic_relationships_reject_before_model_emission(pilot):
    overlay, contract, _ = pilot
    contract["relationships"].append(
        {
            "name": "self_loop",
            "from": "repositories",
            "to": "repositories",
            "from_columns": ["repository_id"],
            "to_columns": ["repository_id"],
        }
    )
    with pytest.raises(ValueError, match="cycle"):
        validate_semantics(contract, overlay)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("unknown_approval", "approvals"),
        ("unknown_column", "Unknown column"),
        ("nested_dimension", "Nested values"),
        ("arbitrary_expression", "reviewed count"),
        ("incomplete_relationship", "complete entity grain"),
    ],
)
def test_invalid_policy_cannot_silently_broaden_approvals(pilot, mutation, error):
    overlay, contract, _ = pilot
    entity = contract["functions"][2]
    if mutation == "unknown_approval":
        entity["semantics"]["all_fields"] = True
    elif mutation == "unknown_column":
        entity["semantics"]["detail_fields"].append("not_a_source_field")
    elif mutation == "nested_dimension":
        entity["semantics"]["dimensions"].append("user")
    elif mutation == "arbitrary_expression":
        entity["semantics"]["metrics"][0]["expression"] = "SUM(id)"
    elif mutation == "incomplete_relationship":
        contract["relationships"][1]["to_columns"] = ["repository_id"]
    with pytest.raises(ValueError, match=error):
        validate_semantics(contract, overlay)


def test_unknown_selected_source_field_rejects_generation(pilot):
    overlay, _, _ = pilot
    overlay["entities"][0]["columns"].append({"name": "invented", "path": ["invented"]})
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match="unknown selected property"):
        compile_contract(specs, sdl, overlay)


def test_source_snapshot_tampering_fails_before_generation(pilot, tmp_path):
    overlay, _, _ = pilot
    shutil.copytree(ROOT / "generation", tmp_path / "generation")
    lock = json.loads((tmp_path / "generation/sources.lock.json").read_text())
    selected = tmp_path / lock["snapshots"][0]["path"]
    selected.write_bytes(selected.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="schema hash mismatch"):
        generator.locked_inputs(tmp_path, overlay)


def test_check_detects_stale_artifacts_without_rewriting_them(tmp_path):
    expected = {"models/pilot.json": '{"version":1}\n'}
    generator.write_outputs(tmp_path, expected, check=False)
    target = tmp_path / "models/pilot.json"
    target.write_text("stale artifact\n")
    with pytest.raises(ValueError, match="artifacts are stale"):
        generator.write_outputs(tmp_path, expected, check=True)
    assert target.read_text() == "stale artifact\n"


def test_nested_graphql_selection_keeps_only_reviewed_shape():
    sdl = """
    type Query { repository(owner:String!,name:String!): Repository }
    type Repository { labels(first:Int,after:String): LabelConnection }
    type LabelConnection { nodes:[Label],pageInfo:PageInfo! }
    type PageInfo { hasNextPage:Boolean!,endCursor:String }
    type Label { id:ID!,creator:User }
    type User { id:ID!,login:String!,organization:Organization,unused:String }
    type Organization { name:String!,backToUser:User }
    """
    entity = {
        "name": "nested_labels",
        "arguments": [{"name": "repository", "type": "VARCHAR"}],
        "grain": ["id"],
        "columns": [
            {"name": "id", "path": ["id"]},
            {
                "name": "creator",
                "path": ["creator"],
                "selection": {"login": True, "organization": {"name": True}},
            },
        ],
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
    selected = generator.select_graphql(sdl, [entity])
    assert "unused" not in selected and "backToUser" not in selected
    compiled = compile_graphql_entity(selected, entity)
    creator = compiled["columns"][1]
    assert creator["type"] == 'STRUCT("login" VARCHAR, "organization" STRUCT("name" VARCHAR))'
    assert creator["nullable"] is True
    assert validate(build_schema(sdl), parse(compiled["transport"]["document"])) == []


def test_optional_relationship_is_policy_metadata_not_an_ossie_property(pilot):
    overlay, contract, provenance = pilot
    relation = next(
        relation
        for relation in contract["relationships"]
        if relation["name"] == "repositories_to_organizations"
    )
    assert relation["optional"] is True
    model = json.loads(
        emit_artifacts(contract, overlay, provenance)[
            "models/generated-pilot/github-generated.crossfield.json"
        ]
    )
    emitted = next(value for value in model["relationships"] if value["name"] == relation["name"])
    assert "optional" not in emitted
    assert model["policy"]["relationship_semantics"][relation["name"]]["optional"] is True
    relation["optional"] = "true"
    with pytest.raises(ValueError, match="optional must be a boolean"):
        validate_semantics(contract, overlay)


def test_membership_does_not_grant_an_activity_attribution_join(pilot):
    _, contract, _ = pilot
    relationships = contract["relationships"]
    assert not any(
        relation["from"] in {"pull_requests", "authored_pull_requests", "pull_request_reviews"}
        and relation["to"] in {"team_memberships", "organization_memberships", "teams"}
        for relation in relationships
    )
    assert not any(
        relation["from"] == "organization_memberships" and relation["to"] == "users"
        for relation in relationships
    )


def test_graphql_common_interface_fields_preserve_types_and_validate_against_source():
    sdl = """
    type Query { user(login:String!): User }
    type User { pullRequests(first:Int,after:String): PullRequestConnection! }
    type PullRequestConnection { nodes:[PullRequest],pageInfo:PageInfo! }
    type PageInfo { hasNextPage:Boolean!,endCursor:String }
    type PullRequest { id:ID!,author:Actor }
    interface Actor { login:String!,unused:String }
    type Bot implements Actor { login:String!,unused:String }
    """
    entity = {
        "name": "user_activity",
        "arguments": [{"name": "user", "type": "VARCHAR"}],
        "grain": ["id"],
        "columns": [
            {"name": "id", "path": ["id"]},
            {"name": "author_login", "path": ["author", "login"]},
        ],
        "transport": {
            "kind": "graphql",
            "field_path": ["user", "pullRequests"],
            "field_arguments": {
                "user": {"login": {"argument": "user"}},
                "pullRequests": {"first": {"literal": 100}, "after": {"cursor": True}},
            },
            "result_path": ["nodes"],
            "pagination": {"kind": "cursor", "page_info_path": ["pageInfo"]},
        },
    }
    selected = generator.select_graphql(sdl, [entity])
    assert "unused" not in selected
    compiled = compile_graphql_entity(selected, entity)
    assert validate(build_schema(sdl), parse(compiled["transport"]["document"])) == []
    author = compiled["columns"][1]
    assert author["type"] == "VARCHAR" and author["nullable"] is True


def _native_proof(contract):
    proof = json.loads((ROOT / "tests/crossfield/generator_semantics.overlay.json").read_text())
    entity = next(item for item in contract["functions"] if item["name"] == proof["entity"])
    entity["semantics"]["crossfield"] = deepcopy(proof["crossfield"])
    for key in ("dimensions", "detail_fields"):
        entity["semantics"][key] += proof[key]
    return entity


def test_native_crossfield_definitions_preserve_expressions_and_policy_without_recipe_branches(pilot):
    overlay, contract, provenance = pilot
    entity = _native_proof(contract)
    native = entity["semantics"]["crossfield"]
    before = deepcopy(native)
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    assert model["metrics"]["proof_p90_merge_hours"] == native["metrics"]["proof_p90_merge_hours"]
    assert (
        model["invocations"]["sources"][entity["name"]]["dataset"]["fields"]["proof_title_lower"]
        == (native["fields"]["proof_title_lower"])
    )
    assert model["policy"]["metric_semantics"]["proof_p90_merge_hours"] == {
        "dataset": entity["name"],
        **native["metric_semantics"]["proof_p90_merge_hours"],
    }
    assert (
        model["policy"]["field_semantics"]["authored_pull_requests.proof_title_lower"]
        == (native["field_semantics"]["proof_title_lower"])
    )
    assert "proof_p90_merge_hours" in output["models/generated-pilot/README.md"]
    coverage = json.loads(output["models/generated-pilot/coverage.json"])
    assert "proof_p90_merge_hours" in next(
        item["metrics"] for item in coverage["entities"] if item["name"] == entity["name"]
    )
    assert native == before
    # Native-only calculations must not alter the worker's actual API result schema.
    generated = json.loads(output["models/generated-pilot/source_schemas.json"])
    assert all(
        "proof_title_lower" not in {column["name"] for column in item["columns"]}
        for item in generated["entities"]
    )


@pytest.mark.parametrize(
    "expression",
    ["SUM(", "my_future_scalar(authored_pull_requests.title)", "SUM(authored_pull_requests.no_such_field)"],
)
def test_generator_leaves_native_expression_acceptance_to_crossfield(pilot, expression):
    overlay, contract, provenance = pilot
    entity = _native_proof(contract)
    entity["semantics"]["crossfield"]["metrics"]["proof_p90_merge_hours"]["expression"] = expression
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    assert model["metrics"]["proof_p90_merge_hours"]["expression"] == expression
    # Native generator_semantics.test rejects malformed/unknown definitions. Generation
    # itself neither approves SQL nor executes API requests or arbitrary code.


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("source_field_collision", "collides with a generated"),
        ("recipe_field_collision", "collides with a generated"),
        ("metric_collision", "Duplicate metric"),
        ("foreign_dataset", "declaring entity"),
        ("foreign_field", "declaring entity"),
        ("missing_policy", "metric_semantics entry"),
        ("dimension_conflict", "dimension approval"),
        ("sql_name_conflict", "generated sql_name"),
    ],
)
def test_native_definitions_cannot_replace_generated_ownership(pilot, mutation, error):
    overlay, contract, provenance = pilot
    entity = _native_proof(contract)
    native = entity["semantics"]["crossfield"]
    if mutation in {"source_field_collision", "recipe_field_collision"}:
        name = "title" if mutation == "source_field_collision" else "merge_hours"
        native["fields"][name] = native["fields"].pop("proof_title_lower")
    elif mutation == "metric_collision":
        native["metrics"]["authored_pr_count"] = native["metrics"].pop("proof_p90_merge_hours")
        native["metric_semantics"]["authored_pr_count"] = native["metric_semantics"].pop(
            "proof_p90_merge_hours"
        )
    elif mutation == "foreign_dataset":
        native["metric_semantics"]["proof_p90_merge_hours"]["dataset"] = "pull_requests"
    elif mutation == "foreign_field":
        native["field_semantics"]["foreign_field"] = {"comment": "Outside owner."}
    elif mutation == "missing_policy":
        native["metric_semantics"] = {}
    elif mutation == "dimension_conflict":
        native["fields"]["proof_title_lower"]["dimension"] = False
    elif mutation == "sql_name_conflict":
        native["field_semantics"]["repository_name"] = {"sql_name": "conflicting_name"}
    with pytest.raises(ValueError, match=error):
        emit_artifacts(contract, overlay, provenance)


def test_native_timestamp_metadata_is_not_replaced_by_api_defaults(pilot):
    overlay, contract, provenance = pilot
    entity = _native_proof(contract)
    definition = entity["semantics"]["crossfield"]["fields"]["proof_title_lower"]
    definition.update(
        expression="authored_pull_requests.created_at",
        type="TIMESTAMP WITH TIME ZONE",
        timezone="America/New_York",
    )
    model = json.loads(
        emit_artifacts(contract, overlay, provenance)[
            "models/generated-pilot/github-generated.crossfield.json"
        ]
    )
    assert (
        model["invocations"]["sources"][entity["name"]]["dataset"]["fields"]["proof_title_lower"]
        == definition
    )
