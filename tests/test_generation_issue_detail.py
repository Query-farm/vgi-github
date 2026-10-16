"""Independent issue identities, role directions and heterogeneous timeline contracts."""

import json
from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def issues(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import issue_detail_fixture

    return issue_detail_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,arguments,key,expected",
    [
        ("issues", {}, "issue_node_id", ["I2101", "I2102"]),
        ("issues", {"issue_number": 2}, "issue_node_id", ["I2102"]),
        ("issues", {"issue_state": "all"}, "issue_node_id", ["I2101", "I2102"]),
        ("issues", {"issue_state": "closed"}, "issue_node_id", ["I2102"]),
        ("issues", {"issue_creator": "issue-author"}, "issue_node_id", ["I2101"]),
        ("issues", {"issue_assignee": "issue-author"}, "issue_node_id", ["I2101"]),
        ("issues", {"issue_parent_of": 2}, "issue_node_id", ["I2103"]),
        ("issues", {"issue_blocked_by": 2}, "issue_node_id", ["I2103"]),
        ("issues", {"issue_related_to": 1}, "issue_node_id", ["I2103"]),
        ("issue_comments", {}, "comment_node_id", ["C501", "C502"]),
        ("issue_comments", {"issue_number": 1}, "comment_node_id", ["C501"]),
        ("issue_comments", {"issue_comment_id": 501}, "comment_node_id", ["C501"]),
        ("issue_events", {}, "event_id", [301, 302]),
        ("issue_events", {"issue_number": 1}, "event_id", [301]),
        ("issue_events", {"issue_event_id": 302}, "event_id", [302]),
        ("issue_timeline_entries", {"issue_number": 1}, "entry_ordinal", [1, 2, 3, 4]),
        ("issue_field_values", {"issue_number": 1}, "issue_field_id", [1, 2]),
        ("issue_suggestions", {"issue_number": 1}, "suggestion_id", [701, 702, 703]),
        (
            "issue_suggestions",
            {"issue_number": 1, "issue_suggestion_state": "applied"},
            "suggestion_id",
            [702],
        ),
        (
            "issue_suggestions",
            {"issue_number": 1, "issue_suggestion_action": "add_field"},
            "suggestion_id",
            [702, 703],
        ),
        ("milestones", {}, "milestone_id", [401, 402]),
        ("milestones", {"milestone_number": 2}, "milestone_id", [402]),
        ("milestones", {"milestone_state": "closed"}, "milestone_id", [402]),
        ("repository_assignees", {}, "assignee_id", [1201, 1202]),
        ("issue_assignments", {"issue_number": 1}, "assignee_id", [1201, 1202]),
        ("repository_labels", {"label": "bug"}, "label_id", ["L11"]),
        ("repository_labels", {"label_collection": True}, "label_id", ["L11", "L12"]),
        ("repository_labels", {"label_issue_number": 1}, "label_id", ["L11", "L12"]),
        ("repository_labels", {"milestone_number": 1}, "label_id", ["L11"]),
    ],
)
def test_issue_routes(pilot, issues, monkeypatch, name, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, issues.respond)
    rows = rows_for(contract, name, repository="issue-fixture/alpha", **arguments)
    assert [r[key] for r in rows] == expected


def test_canonical_issue_fields_match_across_authored_node_rest_and_graphql_routes(
    pilot, issues, monkeypatch
):
    _, contract, _ = pilot
    install(monkeypatch, issues.respond)
    repo = rows_for(contract, "issues", repository="issue-fixture/alpha")
    rest = rows_for(contract, "issues", repository="issue-fixture/alpha", issue_state="all")
    exact = rows_for(contract, "issues", repository="issue-fixture/alpha", issue_number=1)
    node = rows_for(contract, "issues", issue_node_id="I2101")
    authored = rows_for(contract, "issues", user="issue-author")
    rest_only = {
        "reported_state_reason",
        "assignee",
        "assignees",
        "closed_by",
        "issue_type",
        "reaction_summary",
        "dependency_summary",
        "performed_via_app",
        "parent_issue_url",
    }

    def common(rows):
        return [{k: v for k, v in row.items() if k not in rest_only} for row in rows]

    assert common(repo) == common(rest)
    assert common(repo[:1]) == common(exact) == common(node) == common(authored[:1])
    assert all(repo[0][field] is None for field in rest_only)
    assert rest[0]["assignees"][0]["login"] == "issue-author"
    assert [r["state"] for r in repo] == ["OPEN", "CLOSED"]
    # The PR discovery has a present pull_request object with a NULL URL, and must still be excluded.
    assert len(repo) == 2 and len(authored) == 2


def test_authenticated_scopes_are_distinct_from_authorship_and_from_each_other(pilot, issues, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, issues.respond)
    visible = rows_for(contract, "issues", viewer_issues=True, issue_state="all")
    member = rows_for(contract, "issues", viewer_member_issues=True, issue_state="all")
    org = rows_for(
        contract, "issues", viewer_organization_issues=True, organization="issue-fixture", issue_state="all"
    )
    assert [r["issue_node_id"] for r in visible] == ["I2101", "I2102", "I2103"]
    assert [r["issue_node_id"] for r in member] == ["I2101"]
    assert [r["issue_node_id"] for r in org] == ["I2102"]
    assert visible[-1]["repository_name"] == "issue-fixture/beta"


@pytest.mark.parametrize(
    "name,forward,reverse,keys",
    [
        (
            "issue_subissue_memberships",
            "issue_parent_of",
            "issue_children_of",
            ("parent_node_id", "child_node_id"),
        ),
        ("issue_dependencies", "issue_blocked_by", "issue_blocking", ("blocking_node_id", "blocked_node_id")),
    ],
)
def test_reverse_edges_have_same_identity_and_keep_cross_repository_roles(
    pilot, issues, monkeypatch, name, forward, reverse, keys
):
    _, contract, _ = pilot
    install(monkeypatch, issues.respond)
    a = rows_for(contract, name, repository="issue-fixture/alpha", **{forward: 2})
    b = rows_for(contract, name, repository="issue-fixture/beta", **{reverse: 1})
    assert a == b and len(a) == 1
    assert tuple(a[0][k] for k in keys) == ("I2103", "I2102")
    target = rows_for(contract, "issues", repository="issue-fixture/alpha", **{forward: 2})
    assert target[0]["repository_name"] == "issue-fixture/beta"
    assert target[0]["number"] == 1


def test_related_membership_observations_preserve_requested_direction(pilot, issues, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, issues.respond)
    a = rows_for(contract, "issue_related_memberships", repository="issue-fixture/alpha", issue_related_to=1)[
        0
    ]
    b = rows_for(contract, "issue_related_memberships", repository="issue-fixture/beta", issue_related_to=1)[
        0
    ]
    assert (a["source_node_id"], a["related_node_id"]) == ("I2101", "I2103")
    assert (b["source_node_id"], b["related_node_id"]) == ("I2103", "I2101")


def test_event_identity_and_assignment_actor_roles_match_across_routes(pilot, issues, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, issues.respond)
    repo = rows_for(contract, "issue_events", repository="issue-fixture/alpha")
    exact = rows_for(contract, "issue_events", repository="issue-fixture/alpha", issue_event_id=302)
    thread = rows_for(contract, "issue_events", repository="issue-fixture/alpha", issue_number=2)
    assert repo[1:] == exact == thread
    assert exact[0]["actor_login"] == exact[0]["assigner_login"] == "issue-author"
    assert exact[0]["assignee_login"] == "issue-bob"
    assert exact[0]["issue"]["node_id"] == "I2102"


def test_timeline_preserves_typed_variants_and_non_event_grain(pilot, issues, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, issues.respond)
    rows = rows_for(contract, "issue_timeline_entries", repository="issue-fixture/alpha", issue_number=1)
    assert [r["entry_ordinal"] for r in rows] == [1, 2, 3, 4]
    assert [r["event_types"] for r in rows] == [
        ["variant_1"],
        ["variant_14"],
        ["variant_16"],
        ["variant_22"],
    ]
    assert rows[0]["labeled_payload"]["label"]["name"] == "bug"
    assert rows[0]["commented_payload"] is None
    assert rows[1]["commented_payload"]["body"] == "First comment"
    assert rows[2]["event_id"] is None
    commit = rows[2]["committed_payload"]
    assert commit["author"]["name"] == "Original author"
    assert commit["committer"]["name"] == "Integrator"
    assert sum(r.url.path.endswith("/timeline") for r in requests) == 4


def test_field_and_suggestion_values_preserve_types_and_nullable_observations(pilot, issues, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, issues.respond)
    fields = rows_for(contract, "issue_field_values", repository="issue-fixture/alpha", issue_number=1)
    assert fields[0]["value"]["matched_types"] == ["variant_2"]
    assert fields[0]["value"]["variant_2"] == 3.5
    assert fields[1]["value"] is None
    assert [o["name"] for o in fields[1]["multi_select_options"]] == ["Parser", "API"]
    suggestions = rows_for(contract, "issue_suggestions", repository="issue-fixture/alpha", issue_number=1)
    assert [r["target_value"]["matched_types"] for r in suggestions] == [
        ["variant_1"],
        ["variant_3"],
        ["variant_4"],
    ]
    assert suggestions[1]["target_value"]["variant_3"] is True
    assert suggestions[2]["target_value"]["variant_4"] == ["Parser", "API"]
    assert suggestions[1]["actor_id"] == 1301 and suggestions[1]["resolved_by"] == 1202
    assert all(r.url.params["state"] == "all" for r in requests if r.url.path.endswith("/suggestions"))


@pytest.mark.parametrize(
    "number,login,status,scope",
    [
        (None, "issue-author", 204, "repository"),
        (1, "issue-author", 204, "issue"),
        (None, "unavailable", 404, "repository"),
        (1, "unavailable", 404, "issue"),
    ],
)
def test_capability_status_does_not_confuse_unavailable_with_empty_collection(
    pilot, issues, monkeypatch, number, login, status, scope
):
    _, contract, _ = pilot
    install(monkeypatch, issues.respond)
    args = {"issue_number": number} if number else {}
    rows = rows_for(
        contract,
        "issue_assignment_capabilities",
        repository="issue-fixture/alpha",
        assignee_login=login,
        **args,
    )
    assert len(rows) == 1
    assert (rows[0]["scope_kind"], rows[0]["context_issue_number"], rows[0]["status_code"]) == (
        scope,
        number or 0,
        status,
    )


def test_missing_discovery_node_identity_cannot_silently_skip_issue(pilot, issues, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        result = issues.respond(request)
        if request.url.path.endswith("/alpha/issues"):
            payload = result.json()
            payload[0].pop("node_id")
            return httpx.Response(200, json=payload, headers=result.headers, request=request)
        return result

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="required|NULL|non.null"):
        rows_for(contract, "issues", repository="issue-fixture/alpha", issue_state="all")


@pytest.mark.parametrize("change", ["unknown", "missing_label"])
def test_timeline_discriminator_rejects_unknown_or_malformed_selected_event(
    pilot, issues, monkeypatch, change
):
    _, contract, _ = pilot
    timeline = deepcopy(issues.TIMELINE)
    if change == "unknown":
        timeline[0]["event"] = "unmodeled-event"
    else:
        timeline[0].pop("label")
    monkeypatch.setattr(issues, "TIMELINE", timeline)
    install(monkeypatch, issues.respond)
    with pytest.raises(GeneratedContractError, match="discriminator|variant|required|label"):
        rows_for(contract, "issue_timeline_entries", repository="issue-fixture/alpha", issue_number=1)


def test_exact_event_identity_mismatch_fails(pilot, issues, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        result = issues.respond(request)
        if request.url.path.endswith("/issues/events/301"):
            payload = result.json()
            payload["id"] = 302
            return httpx.Response(200, json=payload, headers=result.headers, request=request)
        return result

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(contract, "issue_events", repository="issue-fixture/alpha", issue_event_id=301)


def test_node_hydration_must_match_discovered_canonical_issue_identity(pilot, issues, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        result = issues.respond(request)
        if request.url.path == "/graphql":
            payload = result.json()
            if "node" in payload.get("data", {}):
                payload["data"]["node"]["id"] = "I2102"
                return httpx.Response(200, json=payload, headers=result.headers, request=request)
        return result

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(contract, "issues", repository="issue-fixture/alpha", issue_number=1)


def test_later_page_failure_never_reports_partial_timeline(pilot, issues, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/timeline") and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Not accessible"}, request=request)
        return issues.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="403|accessible"):
        rows_for(contract, "issue_timeline_entries", repository="issue-fixture/alpha", issue_number=1)


def test_issue_since_serializes_timestamp_without_dropping_filter_on_pages(pilot, issues, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, issues.respond)
    rows_for(
        contract,
        "issues",
        repository="issue-fixture/alpha",
        issue_state="all",
        issue_since=datetime(2026, 9, 1, tzinfo=UTC),
    )
    collections = [r for r in requests if r.url.path.endswith("/alpha/issues")]
    assert len(collections) == 3
    assert all(r.url.params["since"].startswith("2026-09-01T00:00:00") for r in collections)


def test_milestone_all_state_population_and_empty_collections(pilot, issues, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, issues.respond)
    rows = rows_for(contract, "milestones", repository="issue-fixture/alpha")
    assert len(rows) == 2 and sum(r["open_issues"] for r in rows) == 2
    assert sum(r["closed_issues"] for r in rows) == 7
    assert all(r.url.params["state"] == "all" for r in requests if r.url.path.endswith("/milestones"))
    for name in ["issues", "issue_comments", "issue_events", "milestones", "repository_assignees"]:
        assert rows_for(contract, name, repository="issue-fixture/empty") == []


def test_incompatible_selectors_reject_before_http(pilot, issues, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, issues.respond)
    with pytest.raises(GeneratedContractError, match="argument|route|consume"):
        rows_for(contract, "issues", repository="issue-fixture/alpha", issue_number=1, issue_state="closed")
    assert requests == []


def test_all_issue_get_operations_have_typed_sources_and_role_edges_remain_explicit():
    detail = json.loads((ROOT / "generation/domains/issue_detail.json").read_text())
    sources = detail["entities"]
    operations = {s["transport"].get("operation_id") for s in sources}
    contributions = json.loads((ROOT / "generation/domains/contributions.json").read_text())
    operations.update(s["transport"].get("operation_id") for s in contributions["entities"])
    assert len({op for op in operations if op and op.startswith("issues/")}) == 28
    pairs = {"issue_subissue_memberships", "issue_dependencies", "issue_related_memberships"}
    for relation in detail["relationships"]:
        if relation.get("from") in pairs or relation.get("source") in pairs:
            assert relation.get("analytical") is False


def test_issue_enrichment_preserves_typed_business_fields_without_extra_http(pilot, issues, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, issues.respond)
    node = rows_for(contract, "issues", issue_node_id="I2101")[0]
    assert len(requests) == 1 and requests[0].method == "POST"
    assert node["issue_id"] == 2101 and node["body_text"] == "Independent issue evidence"
    assert node["body_html"] == "<p>Independent issue evidence</p>"
    assert node["closed"] is False and node["locked"] is False and node["is_pinned"] is True
    assert node["milestone_node_id"] == "M401" and node["milestone_state"] == "OPEN"
    assert node["milestone"]["number"] == 1 and node["milestone"]["progressPercentage"] == 60.0
    assert node["milestone_due_on"] == datetime(2026, 10, 1, tzinfo=UTC)
    assert node["assignees"] is None and node["reaction_summary"] is None
    requests.clear()
    exact = rows_for(contract, "issues", repository="issue-fixture/alpha", issue_number=1)[0]
    assert len(requests) == 3 and [r.method for r in requests] == ["GET", "GET", "POST"]
    assert [a["id"] for a in exact["assignees"]] == [1201, 1202]
    assert exact["issue_type"]["name"] == "Bug" and exact["issue_type"]["is_enabled"] is True
    assert exact["reaction_summary"]["+1"] == 3 and exact["reaction_summary"]["heart"] == 2
    assert exact["performed_via_app"]["id"] == 8201
    requests.clear()
    rows_for(contract, "issues", repository="issue-fixture/alpha")
    assert len(requests) == 3  # Repository identity plus the two existing connection pages.
    assert all("/milestones" not in r.url.path and "/assignees" not in r.url.path for r in requests)


def test_issue_closing_actor_and_rest_duplicate_reason_are_distinct(pilot, issues, monkeypatch):
    _, contract, _ = pilot
    monkeypatch.setitem(issues.I2, "state_reason", "duplicate")
    install(monkeypatch, issues.respond)
    row = rows_for(contract, "issues", repository="issue-fixture/alpha", issue_number=2)[0]
    assert row["author_id"] == 1202 and row["closed_by"]["id"] == 1201
    assert row["state_reason"] == "NOT_PLANNED" and row["reported_state_reason"] == "duplicate"
    assert row["locked"] is True and row["active_lock_reason"] == "RESOLVED"
    assert row["dependency_summary"]["blocked_by"] == 1 and row["dependency_summary"]["blocking"] == 0
    assert row["parent_issue_url"].endswith("/beta/issues/1")
    assert row["milestone"] is None and row["last_edited_at"] is None


def test_rest_optional_issue_evidence_does_not_accept_illegal_null(pilot, issues, monkeypatch):
    _, contract, _ = pilot

    def changed(request, explicit_null=False):
        response = issues.respond(request)
        if request.url.path == "/repos/issue-fixture/alpha/issues/1":
            body = response.json()
            body.pop("assignees")
            if explicit_null:
                body["assignees"] = None
            return httpx.Response(200, json=body, request=request)
        return response

    install(monkeypatch, changed)
    row = rows_for(contract, "issues", repository="issue-fixture/alpha", issue_number=1)[0]
    assert row["assignees"] is None
    install(monkeypatch, lambda request: changed(request, True))
    with pytest.raises(GeneratedContractError, match="assignees: NULL is not allowed"):
        rows_for(contract, "issues", repository="issue-fixture/alpha", issue_number=1)
