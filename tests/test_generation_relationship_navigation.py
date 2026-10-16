"""Navigation uses exact canonical routes and explicit unavailable-value guards."""

import json
from copy import deepcopy

import pytest

from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generation.artifacts import build_model, validate_semantics


def test_parent_forward_routes_preserve_identity_and_null_availability(pilot):
    overlay, contract, _ = pilot
    validate_semantics(contract, overlay)
    relations = {r["name"]: r for r in contract["relationships"]}
    for name in [
        "pull_requests_to_authors",
        "issues_to_authors",
        "discussions_to_authors",
        "issue_comments_to_authors",
        "discussion_comments_to_authors",
        "commit_comments_to_authors",
    ]:
        forward = next(r for r in relations[name]["retrievals"] if r["direction"] == "forward")
        assert forward == {
            "direction": "forward",
            "route": "numeric_identity",
            "bindings": {"user_account_id": "author_id"},
            "when_not_null": ["author_id"],
        }
    expected = {
        "release_assets_to_releases": (
            "lookup",
            {"repository": "repository", "release_id": "release_id"},
            ["release_id"],
        ),
        "dependabot_dismissal_requests_to_alerts": (
            "lookup",
            {"repository": "repository", "dependabot_alert_number": "selected_alert_number"},
            ["repository", "selected_alert_number"],
        ),
        "reactions_to_commit_comments": (
            "lookup",
            {"repository": "repository", "commit_comment_id": "subject_commit_comment_id"},
            ["subject_commit_comment_id"],
        ),
        "reactions_to_issues": (
            "nodes",
            {"issue_node_id": "subject_issue_node_id"},
            ["subject_issue_node_id"],
        ),
        "reactions_to_pull_requests": (
            "lookup",
            {"repository": "repository", "pull_request_number": "subject_number"},
            ["subject_pull_request", "subject_number"],
        ),
    }
    for name, (route, bindings, guards) in expected.items():
        forward = next(r for r in relations[name]["retrievals"] if r["direction"] == "forward")
        assert forward["route"] == route
        assert forward["bindings"] == bindings
        assert forward["when_not_null"] == guards
    assert next(r for r in relations["reactions_to_issues"]["retrievals"] if r["direction"] == "forward")[
        "when_null"
    ] == ["subject_pull_request"]


@pytest.mark.parametrize("mutation", ["missing_field", "duplicate_field", "empty", "contradiction"])
def test_navigation_rejects_invalid_null_guards(pilot, mutation):
    overlay, original, _ = pilot
    contract = deepcopy(original)
    relation = next(r for r in contract["relationships"] if r["name"] == "reactions_to_pull_requests")
    forward = next(r for r in relation["retrievals"] if r["direction"] == "forward")
    if mutation == "missing_field":
        forward["when_not_null"] = ["undeclared_parent"]
    elif mutation == "duplicate_field":
        forward["when_not_null"] = ["subject_pull_request", "subject_pull_request"]
    elif mutation == "empty":
        forward["when_not_null"] = []
    else:
        forward["when_null"] = ["subject_pull_request"]
    with pytest.raises(ValueError, match="guard|field|distinct|nonempty|contradict|both NULL and non-NULL"):
        validate_semantics(contract, overlay)


def test_workflow_run_suite_reverse_binding_preserves_nullable_identity_guard(pilot):
    overlay, contract, _ = pilot
    validate_semantics(contract, overlay)
    relation = next(
        row for row in contract["relationships"] if row["name"] == "check_suites_to_workflow_runs"
    )
    reverse = next(row for row in relation["retrievals"] if row["direction"] == "reverse")
    expected = {
        "direction": "reverse",
        "route": "lookup",
        "bindings": {"repository": "repository", "check_suite_id": "check_suite_id"},
        "when_not_null": ["check_suite_id"],
    }
    assert reverse == expected
    model, _ = build_model(contract, overlay)
    published = json.loads(model["policy"]["tags"]["github.relationship_retrievals"])
    assert expected in published["check_suites_to_workflow_runs"]
    assert "check_suites_to_workflow_runs" not in model["policy"]["relationships"]
