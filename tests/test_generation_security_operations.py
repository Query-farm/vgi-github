"""Independent security operation populations, typed roles and failure boundaries."""

import json

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def security(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import security_operations_fixture

    return security_operations_fixture


def rows_for(contract, name, **arguments):
    entity = next(f for f in contract["functions"] if f["name"] == name)
    result = run(entity, {k: [v] for k, v in arguments.items()}, contract=contract)
    return [row for batch in result.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,arguments,key,expected",
    [
        ("security_campaigns", {"organization": "security-fixture"}, "campaign_number", [1, 2, 3]),
        (
            "security_campaigns",
            {"organization": "security-fixture", "security_campaign_number": 2},
            "state",
            ["closed"],
        ),
        (
            "security_campaigns",
            {"organization": "security-fixture", "security_campaign_state": "open"},
            "campaign_number",
            [1, 3],
        ),
        (
            "security_campaigns",
            {"organization": "security-fixture", "security_campaign_state": "closed"},
            "campaign_number",
            [2],
        ),
        ("code_quality_findings", {"repository": "security-fixture/alpha"}, "finding_number", [1, 2, 3]),
        (
            "code_quality_findings",
            {"repository": "security-fixture/alpha", "code_quality_finding_number": 2},
            "severity",
            ["warning"],
        ),
        (
            "code_quality_findings",
            {"repository": "security-fixture/alpha", "code_quality_finding_state": "open"},
            "finding_number",
            [1, 3],
        ),
        (
            "code_quality_findings",
            {"repository": "security-fixture/alpha", "code_quality_finding_state": "dismissed"},
            "finding_number",
            [2],
        ),
        ("code_quality_findings", {"repository": "security-fixture/empty"}, "finding_number", []),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha"},
            "dismissal_request_id",
            [2801, 2802],
        ),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha", "dependabot_alert_number": 7},
            "dismissal_request_number",
            [51],
        ),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha", "dependabot_alert_number": 9},
            "status",
            ["expired"],
        ),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha", "dependabot_dismissal_period": "day"},
            "dismissal_request_id",
            [2802],
        ),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha", "dependabot_dismissal_status": "open"},
            "status",
            ["pending"],
        ),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha", "dependabot_dismissal_reviewer": "security-bob"},
            "dismissal_request_id",
            [2801],
        ),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha", "dependabot_dismissal_requester": "security-bob"},
            "dismissal_request_id",
            [],
        ),
        (
            "dependabot_dismissal_requests",
            {"organization": "security-fixture"},
            "dismissal_request_id",
            [2802],
        ),
        (
            "dependabot_dismissal_requests",
            {"organization": "security-fixture", "dependabot_dismissal_period": "month"},
            "dismissal_request_id",
            [2801, 2802, 2804],
        ),
        (
            "dependabot_dismissal_requests",
            {
                "organization": "security-fixture",
                "dependabot_dismissal_period": "month",
                "dependabot_dismissal_repository_name": "beta",
            },
            "dismissal_request_id",
            [2804],
        ),
        (
            "dependabot_dismissal_requests",
            {
                "organization": "security-fixture",
                "dependabot_dismissal_period": "month",
                "dependabot_dismissal_requester": "security-bob",
            },
            "dismissal_request_id",
            [2804],
        ),
        (
            "dependabot_dismissal_requests",
            {
                "organization": "security-fixture",
                "dependabot_dismissal_period": "month",
                "dependabot_dismissal_org_status": "denied",
            },
            "dismissal_request_id",
            [2804],
        ),
        (
            "dependabot_dismissal_requests",
            {"organization": "security-fixture", "dependabot_dismissal_org_status": "completed"},
            "dismissal_request_id",
            [],
        ),
        (
            "dependabot_dismissal_requests",
            {"organization": "security-fixture", "dependabot_dismissal_org_status": "cancelled"},
            "dismissal_request_id",
            [],
        ),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/empty"},
            "dismissal_request_id",
            [],
        ),
    ],
)
def test_security_operation_route_populations(pilot, security, monkeypatch, name, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, security.respond)
    assert [r[key] for r in rows_for(contract, name, **arguments)] == expected


def test_campaign_managers_and_unknown_statistics_are_typed(pilot, security, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, security.respond)
    rows = rows_for(contract, "security_campaigns", organization="security-fixture")
    assert [r["organization_id"] for r in rows] == [2500, 2500, 2500]
    assert rows[0]["managers"][0]["id"] == 2601
    assert rows[0]["managers"][1]["login"] == "security-bob"
    assert rows[0]["team_managers"][0]["id"] == 2701
    assert rows[0]["team_managers"][0]["permissions"]["pull"] is True
    assert rows[0]["team_managers"][0]["parent"] is None
    assert rows[0]["alert_stats"] == {"open_count": 4, "closed_count": 3, "in_progress_count": 1}
    assert rows[1]["open_alert_count"] == 0
    assert rows[2]["alert_stats"] is None and rows[2]["open_alert_count"] is None
    assert sum(r["closed_alert_count"] or 0 for r in rows) == 8
    assert len([r for r in requests if r.url.path.endswith("/campaigns")]) == 3


def test_campaign_lookup_preserves_canonical_fields(pilot, security, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, security.respond)
    collection = rows_for(contract, "security_campaigns", organization="security-fixture")
    exact = rows_for(
        contract, "security_campaigns", organization="security-fixture", security_campaign_number=1
    )
    assert exact == collection[:1]


def test_findings_paginate_cursors_with_qualified_identity_and_complete_nested_values(
    pilot, security, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, security.respond)
    rows = rows_for(contract, "code_quality_findings", organization="security-fixture")
    assert [(r["repository_id"], r["finding_number"]) for r in rows] == [
        (2501, 1),
        (2501, 2),
        (2501, 3),
        (2502, 1),
    ]
    assert rows[0]["rule"]["help"] == "Extract a function"
    assert rows[0]["location"]["end_column"] == 8
    assert rows[0]["message"] == {"text": "Repeated logic", "markdown": "**Repeated logic**"}
    alpha = [r for r in requests if r.url.path == "/repos/security-fixture/alpha/code-quality/findings"]
    assert [r.url.params.get("after") for r in alpha] == [None, "2", "3"]
    assert (
        rows_for(
            contract,
            "code_quality_findings",
            repository="security-fixture/alpha",
            code_quality_finding_number=1,
        )
        == rows[:1]
    )


def test_dismissal_roles_numbers_and_explicit_lookback_populations(pilot, security, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, security.respond)
    repo = rows_for(contract, "dependabot_dismissal_requests", repository="security-fixture/alpha")
    org = rows_for(
        contract,
        "dependabot_dismissal_requests",
        organization="security-fixture",
        dependabot_dismissal_period="month",
        dependabot_dismissal_repository_name="alpha",
    )
    assert repo == org
    assert repo[0]["requester_id"] == 2601
    assert [r["reviewer"]["actor_id"] for r in repo[0]["responses"]] == [2602, 2603]
    assert [r["status"] for r in repo[0]["responses"]] == ["denied", "approved"]
    assert repo[0]["status"] == "approved"
    assert repo[0]["data"][0] == {
        "reason": "tolerable_risk",
        "alert_number": "7",
        "alert_title": "Vulnerable package",
    }
    assert all(r["selected_alert_number"] is None for r in repo)
    exact = rows_for(
        contract,
        "dependabot_dismissal_requests",
        repository="security-fixture/alpha",
        dependabot_alert_number=7,
    )[0]
    assert (
        exact["dismissal_request_id"],
        exact["dismissal_request_number"],
        exact["selected_alert_number"],
    ) == (2801, 51, 7)
    assert {k: v for k, v in exact.items() if k != "selected_alert_number"} == {
        k: v for k, v in repo[0].items() if k != "selected_alert_number"
    }


@pytest.mark.parametrize(
    "name,args,path",
    [
        (
            "security_campaigns",
            {"organization": "security-fixture", "security_campaign_number": 1},
            "/campaigns/1",
        ),
        (
            "code_quality_findings",
            {"repository": "security-fixture/alpha", "code_quality_finding_number": 1},
            "/findings/1",
        ),
    ],
)
def test_exact_object_identity_mismatch_fails(pilot, security, monkeypatch, name, args, path):
    _, contract, _ = pilot

    def respond(request):
        result = security.respond(request)
        if request.url.path.endswith(path):
            body = result.json()
            body["number"] = 99
            return httpx.Response(200, json=body, headers=result.headers, request=request)
        return result

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(contract, name, **args)


@pytest.mark.parametrize(
    "name,args",
    [
        ("security_campaigns", {"organization": "security-fixture", "security_campaign_number": 999}),
        (
            "code_quality_findings",
            {"repository": "security-fixture/alpha", "code_quality_finding_number": 999},
        ),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha", "dependabot_alert_number": 999},
        ),
    ],
)
def test_missing_selected_objects_fail_as_404(pilot, security, monkeypatch, name, args):
    _, contract, _ = pilot
    install(monkeypatch, security.respond)
    with pytest.raises(Exception, match="404"):
        rows_for(contract, name, **args)


@pytest.mark.parametrize(
    "failure", ["missing_id", "missing_repository_id", "wrong_repository", "invalid_response_reviewer"]
)
def test_dismissal_identity_and_typed_reviewers_fail_closed(pilot, security, monkeypatch, failure):
    _, contract, _ = pilot

    def respond(request):
        result = security.respond(request)
        if request.url.path.endswith("/dismissal-requests/dependabot"):
            body = result.json()
            if failure == "missing_id":
                body[0].pop("id")
            elif failure == "missing_repository_id":
                body[0]["repository"].pop("id")
            elif failure == "wrong_repository":
                body[0]["repository"]["full_name"] = "security-fixture/beta"
            else:
                body[0]["responses"][0]["reviewer"]["actor_id"] = "not-an-id"
            return httpx.Response(200, json=body, headers=result.headers, request=request)
        return result

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="required|row assertion|BIGINT|integer"):
        rows_for(contract, "dependabot_dismissal_requests", repository="security-fixture/alpha")


@pytest.mark.parametrize(
    "name,args,path,key",
    [
        ("security_campaigns", {"organization": "security-fixture"}, "/campaigns", "page"),
        ("code_quality_findings", {"repository": "security-fixture/alpha"}, "/findings", "after"),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha"},
            "/dismissal-requests/dependabot",
            "page",
        ),
    ],
)
def test_later_page_failure_is_not_a_complete_population(pilot, security, monkeypatch, name, args, path, key):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith(path) and request.url.params.get(key) == "2":
            return httpx.Response(403, json={"message": "Security page denied"}, request=request)
        return security.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="403|denied"):
        rows_for(contract, name, **args)


def test_repeated_finding_cursor_does_not_silently_duplicate_results(pilot, security, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        result = security.respond(request)
        if request.url.path.endswith("/code-quality/findings"):
            return httpx.Response(
                200, json=result.json(), headers={"Link": f'<{request.url}>; rel="next"'}, request=request
            )
        return result

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="repeat|cycle|pagination|cursor|duplicate row identity"):
        rows_for(contract, "code_quality_findings", repository="security-fixture/alpha")


@pytest.mark.parametrize(
    "name,args",
    [
        (
            "security_campaigns",
            {
                "organization": "security-fixture",
                "security_campaign_number": 1,
                "security_campaign_state": "open",
            },
        ),
        (
            "code_quality_findings",
            {
                "repository": "security-fixture/alpha",
                "code_quality_finding_number": 1,
                "code_quality_finding_state": "open",
            },
        ),
        (
            "dependabot_dismissal_requests",
            {
                "repository": "security-fixture/alpha",
                "dependabot_alert_number": 7,
                "dependabot_dismissal_reviewer": "security-bob",
            },
        ),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha", "dependabot_dismissal_org_status": "completed"},
        ),
        (
            "dependabot_dismissal_requests",
            {"organization": "security-fixture", "dependabot_dismissal_status": "open"},
        ),
        (
            "dependabot_dismissal_requests",
            {"repository": "security-fixture/alpha", "dependabot_dismissal_period": "year"},
        ),
    ],
)
def test_incompatible_or_invalid_selectors_reject_before_http(pilot, security, monkeypatch, name, args):
    _, contract, _ = pilot
    requests = install(monkeypatch, security.respond)
    with pytest.raises(GeneratedContractError, match="argument|route|consume|enum|value"):
        rows_for(contract, name, **args)
    assert requests == []


def test_seven_operations_use_three_canonical_entities_and_explicit_reverse_roles():
    domain = json.loads((ROOT / "generation/domains/security_operations.json").read_text())
    assert [f["name"] for f in domain["functions"]] == [
        "security_campaigns",
        "code_quality_findings",
        "dependabot_dismissal_requests",
    ]
    assert {e["transport"]["operation_id"] for e in domain["entities"]} == {
        "campaigns/list-org-campaigns",
        "campaigns/get-campaign-summary",
        "code-quality/list-findings-for-repo",
        "code-quality/get-finding",
        "dependabot/list-dismissal-requests-for-repo",
        "dependabot/list-dismissal-requests-for-org",
        "dependabot/get-dismissal-request-for-repo",
    }
    relations = {r["name"]: r for r in domain["relationships"]}
    for name in [
        "security_campaigns_to_organizations",
        "code_quality_findings_to_repositories",
        "dependabot_dismissal_requests_to_repositories",
        "dependabot_dismissal_requests_to_organizations",
        "dependabot_dismissal_requests_to_alerts",
    ]:
        assert any(r["direction"] == "reverse" for r in relations[name]["retrievals"])
    assert relations["dependabot_dismissal_requests_to_requesters"]["from_columns"] == ["requester_id"]
    alert = relations["dependabot_dismissal_requests_to_alerts"]
    assert alert["analytical"] is False and alert["optional"] is True
    assert alert["from_columns"] == ["repository_id", "selected_alert_number"]
