"""Independent code scanning populations, typed context, actor roles and failures."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def scan(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import code_scanning_fixture

    return code_scanning_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,arguments,key,expected",
    [
        ("code_scanning_alerts", {}, "alert_number", [1, 2, 3]),
        ("code_scanning_alerts", {"code_scanning_alert_number": 2}, "state", ["fixed"]),
        ("code_scanning_alerts", {"code_scanning_state": "open"}, "alert_number", [1]),
        ("code_scanning_alerts", {"code_scanning_state": "closed"}, "alert_number", [2, 3]),
        ("code_scanning_alerts", {"code_scanning_severity": "critical"}, "alert_number", [3]),
        ("code_scanning_alerts", {"code_scanning_assignees": "none"}, "alert_number", [2, 3]),
        ("code_scanning_alerts", {"code_scanning_ref": "refs/heads/feature"}, "alert_number", [1]),
        ("code_scanning_alerts", {"code_scanning_pr": 12}, "alert_number", [1]),
        (
            "code_scanning_alert_instances",
            {"code_scanning_alert_number": 1},
            "ref",
            ["refs/heads/main", "refs/heads/feature"],
        ),
        (
            "code_scanning_alert_instances",
            {"code_scanning_alert_number": 1, "code_scanning_ref": "refs/heads/feature"},
            "ref",
            ["refs/heads/feature"],
        ),
        ("code_scanning_alert_instances", {}, "alert_number", [1, 1, 2, 3]),
        ("code_scanning_analyses", {}, "analysis_id", [501, 502, 503]),
        ("code_scanning_analyses", {"code_scanning_analysis_id": 502}, "results_count", [3]),
        ("code_scanning_analyses", {"code_scanning_sarif_id": "upload-1"}, "analysis_id", [501, 502]),
        ("code_scanning_analyses", {"code_scanning_ref": "refs/heads/main"}, "analysis_id", [501, 503]),
        ("code_scanning_analyses", {"code_scanning_pr": 12}, "analysis_id", [502]),
        ("codeql_databases", {}, "database_id", [601, 602]),
        ("codeql_databases", {"codeql_database_language": "python"}, "size_bytes", [10]),
        ("code_scanning_autofixes", {"code_scanning_alert_number": 1}, "status", ["success"]),
        (
            "code_scanning_sarif_uploads",
            {"code_scanning_sarif_id": "upload-1"},
            "processing_status",
            ["complete"],
        ),
        ("code_scanning_sarif_uploads", {"code_scanning_analysis_id": 502}, "sarif_id", ["upload-1"]),
        ("code_scanning_repository_settings", {}, "pr_scan", ["enabled"]),
        ("codeql_variant_analyses", {"codeql_variant_analysis_id": 701}, "actor_login", ["alice"]),
        (
            "codeql_variant_repository_tasks",
            {"codeql_variant_analysis_id": 701},
            "target_repository_id",
            [911, 914],
        ),
        (
            "codeql_variant_repository_tasks",
            {"codeql_variant_analysis_id": 701, "codeql_target_repository": "scan-fixture/target"},
            "analysis_status",
            ["failed"],
        ),
        ("code_scanning_dismissal_requests", {}, "dismissal_request_id", [901, 902]),
        (
            "code_scanning_dismissal_requests",
            {"code_scanning_alert_number": 3},
            "dismissal_request_id",
            [901],
        ),
        (
            "code_scanning_dismissal_requests",
            {"code_scanning_dismissal_status": "open"},
            "dismissal_request_id",
            [902],
        ),
        (
            "code_scanning_dismissal_requests",
            {"code_scanning_dismissal_reviewer": "bob"},
            "dismissal_request_id",
            [901],
        ),
    ],
)
def test_code_scanning_route_populations(pilot, scan, monkeypatch, name, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, scan.respond)
    rows = rows_for(contract, name, repository="scan-fixture/alpha", **arguments)
    assert [row[key] for row in rows] == expected
    assert all(row["repository_id"] == 911 for row in rows)


def test_org_and_repository_alerts_preserve_qualified_identity_and_canonical_detail(pilot, scan, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, scan.respond)
    organization = rows_for(contract, "code_scanning_alerts", organization="scan-fixture")
    repository = rows_for(contract, "code_scanning_alerts", repository="scan-fixture/alpha")
    exact = rows_for(
        contract, "code_scanning_alerts", repository="scan-fixture/alpha", code_scanning_alert_number=1
    )
    assert organization[:3] == repository
    assert repository[:1] == exact
    assert [(r["repository_id"], r["alert_number"]) for r in organization] == [
        (911, 1),
        (911, 2),
        (911, 3),
        (912, 1),
    ]
    assert organization[0]["rule"]["help"] == "Validate input"
    assert organization[0]["linked_pull_requests"][0]["user"]["login"] == "bob"
    assert sum(r.url.path == "/orgs/scan-fixture/code-scanning/alerts" for r in requests) == 4


def test_alert_actors_severity_and_typed_instance_are_distinct(pilot, scan, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, scan.respond)
    rows = rows_for(contract, "code_scanning_alerts", repository="scan-fixture/alpha")
    assert rows[2]["dismissed_by_login"] == "bob"
    assert rows[2]["dismissal_approved_by_login"] == "alice"
    assert rows[0]["assignees"][0]["login"] == "alice"
    assert rows[0]["security_severity"] == "high" and rows[0]["rule_severity"] == "warning"
    assert rows[0]["most_recent_instance"]["location"]["start_line"] == 10
    assert rows[0]["most_recent_instance"]["message"]["markdown"] == "**Untrusted input**"
    instances = rows_for(
        contract,
        "code_scanning_alert_instances",
        repository="scan-fixture/alpha",
        code_scanning_alert_number=3,
    )
    assert rows[2]["state"] == "dismissed" and instances[0]["state"] == "open"


def test_analysis_results_repeat_alerts_and_legacy_rule_zero_remains_visible(pilot, scan, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, scan.respond)
    rows = rows_for(contract, "code_scanning_analyses", repository="scan-fixture/alpha")
    assert sum(r["results_count"] for r in rows) == 8
    assert rows[0]["sarif_id"] == rows[1]["sarif_id"]
    assert rows[2]["rules_count"] == 0
    fn = next(f for f in contract["functions"] if f["name"] == "code_scanning_analyses")
    assert "unavailable" in fn["description"]


def test_variant_target_roles_null_counts_and_nonexhaustive_skipped_metadata(pilot, scan, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, scan.respond)
    tasks = rows_for(
        contract,
        "codeql_variant_repository_tasks",
        repository="scan-fixture/alpha",
        codeql_variant_analysis_id=701,
    )
    assert [(r["repository_id"], r["target_repository_id"]) for r in tasks] == [(911, 911), (911, 914)]
    assert tasks[1]["result_count"] is None and tasks[1]["artifact_size_in_bytes"] is None
    assert sum(r["result_count"] or 0 for r in tasks) == 7
    variant = rows_for(
        contract, "codeql_variant_analyses", repository="scan-fixture/alpha", codeql_variant_analysis_id=701
    )[0]
    skipped = variant["skipped_repositories"]["access_mismatch_repos"]
    assert skipped["repository_count"] == 5 and len(skipped["repositories"]) == 1
    assert variant["controller_repository_id"] == 911


def test_dismissal_routes_keep_request_id_alert_text_and_requester_reviewer_roles(pilot, scan, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, scan.respond)
    rows = rows_for(contract, "code_scanning_dismissal_requests", organization="scan-fixture")
    assert [r["dismissal_request_id"] for r in rows] == [901, 902, 903]
    assert rows[0]["dismissal_request_number"] == 103
    assert rows[0]["data"][0]["alert_number"] == "3"
    assert rows[0]["requester_login"] == "alice"
    assert rows[0]["responses"][0]["reviewer"]["actor_name"] == "bob"


def test_organization_settings_are_not_repository_execution_counts(pilot, scan, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, scan.respond)
    rows = rows_for(contract, "code_scanning_organization_settings", organization="scan-fixture")
    assert rows == [{"organization_id": 910, "organization_login": "scan-fixture", "pr_scan": "enabled"}]


@pytest.mark.parametrize("field", ["ref", "analysis_key", "environment"])
def test_missing_instance_identity_fails_instead_of_dropping_record(pilot, scan, monkeypatch, field):
    _, contract, _ = pilot
    changed = deepcopy(scan.INSTANCES)
    changed[1][0].pop(field)
    monkeypatch.setattr(scan, "INSTANCES", changed)
    install(monkeypatch, scan.respond)
    with pytest.raises(GeneratedContractError, match="required|non.null|identity"):
        rows_for(
            contract,
            "code_scanning_alert_instances",
            repository="scan-fixture/alpha",
            code_scanning_alert_number=1,
        )


@pytest.mark.parametrize(
    "operation,field,value,function,arguments",
    [
        ("/alerts/1", "number", 2, "code_scanning_alerts", {"code_scanning_alert_number": 1}),
        ("/analyses/501", "id", 502, "code_scanning_analyses", {"code_scanning_analysis_id": 501}),
        (
            "/databases/python",
            "language",
            "javascript",
            "codeql_databases",
            {"codeql_database_language": "python"},
        ),
    ],
)
def test_exact_identity_mismatch_fails(
    pilot, scan, monkeypatch, operation, field, value, function, arguments
):
    _, contract, _ = pilot

    def respond(request):
        response = scan.respond(request)
        if request.url.path.endswith(operation):
            data = response.json()
            data[field] = value
            return httpx.Response(200, json=data, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(contract, function, repository="scan-fixture/alpha", **arguments)


def test_unknown_optional_field_is_null_but_present_wrong_type_fails(pilot, scan, monkeypatch):
    _, contract, _ = pilot
    changed = deepcopy(scan.TASKS)
    changed["scan-fixture/target"]["result_count"] = "unknown"
    monkeypatch.setattr(scan, "TASKS", changed)
    install(monkeypatch, scan.respond)
    with pytest.raises(GeneratedContractError, match="BIGINT|integer|type"):
        rows_for(
            contract,
            "codeql_variant_repository_tasks",
            repository="scan-fixture/alpha",
            codeql_variant_analysis_id=701,
            codeql_target_repository="scan-fixture/target",
        )


def test_permission_error_on_later_alert_page_is_not_partial_success(pilot, scan, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/code-scanning/alerts") and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Resource not accessible"}, request=request)
        return scan.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="403|accessible"):
        rows_for(contract, "code_scanning_alerts", repository="scan-fixture/alpha")


def test_repeated_next_link_is_rejected(pilot, scan, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        response = scan.respond(request)
        if request.url.path.endswith("/code-scanning/analyses"):
            return httpx.Response(
                200, json=response.json(), headers={"Link": f'<{request.url}>; rel="next"'}, request=request
            )
        return response

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="repeat|cycle|pagination|cursor|duplicate row identity"):
        rows_for(contract, "code_scanning_analyses", repository="scan-fixture/alpha")


def test_incompatible_exact_selectors_reject_before_http(pilot, scan, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, scan.respond)
    with pytest.raises(GeneratedContractError, match="argument|route|consume"):
        rows_for(
            contract,
            "code_scanning_alerts",
            repository="scan-fixture/alpha",
            code_scanning_alert_number=1,
            code_scanning_state="open",
        )
    assert requests == []


def test_empty_repository_is_empty_not_one_null_record(pilot, scan, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, scan.respond)
    for name in [
        "code_scanning_alerts",
        "code_scanning_alert_instances",
        "code_scanning_analyses",
        "codeql_databases",
        "code_scanning_dismissal_requests",
    ]:
        assert rows_for(contract, name, repository="scan-fixture/empty") == []
