"""Secret alert identity, full location variants and bounded request observations."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import secret_scanning_fixture

    return secret_scanning_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,arguments,key,expected",
    [
        ("secret_scanning_alerts", {}, "alert_number", [1, 2, 3]),
        ("secret_scanning_alerts", {"secret_scanning_alert_number": 2}, "state", ["resolved"]),
        ("secret_scanning_alerts", {"secret_scanning_state": "open"}, "alert_number", [1]),
        ("secret_scanning_alerts", {"secret_scanning_validity": "active"}, "alert_number", [1, 3]),
        ("secret_scanning_alerts", {"secret_scanning_bypassed": False}, "alert_number", [2, 3]),
        ("secret_scanning_alerts", {"secret_scanning_publicly_leaked": True}, "alert_number", [1]),
        ("secret_scanning_alerts", {"secret_scanning_multi_repo": True}, "alert_number", [1]),
        ("secret_scanning_alerts", {"secret_scanning_providers": "github"}, "alert_number", [1, 2]),
        ("secret_scanning_alerts", {"secret_scanning_exclude_providers": "github"}, "alert_number", [3]),
        ("secret_scanning_alerts", {"secret_scanning_assignee": "alice"}, "alert_number", [1]),
        ("secret_scanning_alerts", {"secret_scanning_resolution": "revoked"}, "alert_number", [2]),
        (
            "secret_scanning_alerts",
            {"secret_scanning_included_metadata": "owner-email,secret-id"},
            "alert_number",
            [1, 2, 3],
        ),
        ("secret_scanning_locations", {"secret_scanning_alert_number": 2}, "location_ordinal", [1]),
        ("secret_scanning_scan_snapshots", {}, "repository_id", [1011]),
        ("secret_scanning_bypass_requests", {}, "request_number", [41, 42]),
        ("secret_scanning_bypass_requests", {"secret_scanning_bypass_number": 41}, "status", ["approved"]),
        (
            "secret_scanning_bypass_requests",
            {"secret_scanning_bypass_status": "completed"},
            "request_number",
            [42],
        ),
        (
            "secret_scanning_bypass_requests",
            {"secret_scanning_request_reviewer": "bob"},
            "request_number",
            [41, 42],
        ),
        ("secret_scanning_dismissal_requests", {}, "request_number", [91]),
        ("secret_scanning_dismissal_requests", {"secret_scanning_alert_number": 2}, "request_id", [901]),
        ("secret_scanning_custom_patterns", {}, "pattern_id", [701, 702]),
        (
            "secret_scanning_custom_patterns",
            {"secret_scanning_pattern_state": "published"},
            "pattern_id",
            [701],
        ),
        (
            "secret_scanning_custom_patterns",
            {"secret_scanning_pattern_push_protection": "disabled"},
            "pattern_id",
            [702],
        ),
    ],
)
def test_secret_scanning_route_populations(pilot, secret, monkeypatch, name, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, secret.respond)
    rows = rows_for(contract, name, repository="secret-fixture/alpha", **arguments)
    assert [row[key] for row in rows] == expected


def test_alert_routes_share_canonical_fields_without_unqualifying_numbers(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, secret.respond)
    org = rows_for(contract, "secret_scanning_alerts", organization="secret-fixture")
    repo = rows_for(contract, "secret_scanning_alerts", repository="secret-fixture/alpha")
    lookup = rows_for(
        contract, "secret_scanning_alerts", repository="secret-fixture/alpha", secret_scanning_alert_number=1
    )
    assert org[:3] == repo and repo[:1] == lookup
    assert [(r["repository_id"], r["alert_number"]) for r in org] == [
        (1011, 1),
        (1011, 2),
        (1011, 3),
        (1012, 1),
    ]
    assert repo[2]["state"] == "resolved" and repo[2]["validity"] == "active"
    assert repo[1]["resolved_by_login"] == "bob"
    assert repo[0]["push_protection_bypassed_by_login"] == "alice"
    assert repo[0]["push_protection_bypass_request_reviewer_login"] == "carol"
    assert repo[0]["metadata"][0] == {"key": "owner-email", "value": "synthetic@example.com"}


def test_hide_secret_option_survives_discovery_hydration_and_pages(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, secret.respond)
    rows = rows_for(
        contract,
        "secret_scanning_alerts",
        repository="secret-fixture/alpha",
        secret_scanning_hide_secret=True,
    )
    assert len(rows) == 3 and all(r["secret"] is None for r in rows)
    alerts = [r for r in requests if "/secret-scanning/alerts" in r.url.path]
    assert len(alerts) == 6
    assert all(r.url.params["hide_secret"] == "true" for r in alerts)


def test_locations_cover_all_thirteen_variants_and_page_spanning_ordinals(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, secret.respond)
    rows = rows_for(
        contract,
        "secret_scanning_locations",
        repository="secret-fixture/alpha",
        secret_scanning_alert_number=1,
    )
    assert [r["location_ordinal"] for r in rows] == list(range(1, 15))
    assert {r["location_type"] for r in rows} == set(secret.LOCATION_TYPES)
    assert rows[0]["details"]["matched_types"] == ["variant_1"]
    assert rows[1]["details"]["matched_types"] == ["variant_2"]
    assert rows[2]["details"]["matched_types"] == ["variant_3"]
    assert rows[12]["details"]["matched_types"] == ["variant_13"]
    assert rows[0]["details"]["variant_1"]["start_line"] == 1.0
    assert rows[-1]["details"]["variant_1"]["start_line"] == 2.0
    assert rows[0]["details"]["variant_2"] is None
    assert sum(r.url.path.endswith("/locations") for r in requests) == 14


def test_location_retrieval_resets_local_ordinal_per_alert_not_per_page(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, secret.respond)
    rows = rows_for(contract, "secret_scanning_locations", repository="secret-fixture/alpha")
    assert len(rows) == 15
    assert [(r["alert_number"], r["location_ordinal"]) for r in rows][-2:] == [(1, 14), (2, 1)]


def test_scan_history_is_latest_category_snapshot_and_pending_time_is_unknown(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, secret.respond)
    rows = rows_for(contract, "secret_scanning_scan_snapshots", repository="secret-fixture/alpha")
    assert len(rows) == 1 and len(rows[0]["incremental_scans"]) == 2
    assert rows[0]["backfill_scans"][0]["started_at"] is None
    assert rows[0]["custom_pattern_backfill_scans"][0]["pattern_scope"] == "organization"
    assert rows[0]["generic_secrets_backfill_scans"][0]["status"] == "failed"


@pytest.mark.parametrize(
    "name,key,expected",
    [
        ("secret_scanning_bypass_requests", "request_id", [801, 802, 803]),
        ("secret_scanning_dismissal_requests", "request_id", [901, 902]),
        ("secret_scanning_custom_patterns", "pattern_id", [701, 703]),
    ],
)
def test_direct_organization_collections(pilot, secret, monkeypatch, name, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, secret.respond)
    rows = rows_for(contract, name, organization="secret-fixture")
    assert [r[key] for r in rows] == expected


def test_scoped_patterns_do_not_invent_global_owner_namespace(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, secret.respond)
    repo = rows_for(contract, "secret_scanning_custom_patterns", repository="secret-fixture/alpha")
    org = rows_for(contract, "secret_scanning_custom_patterns", organization="secret-fixture")
    assert repo[0]["pattern_id"] == org[0]["pattern_id"] == 701
    assert (repo[0]["scope_kind"], repo[0]["scope_id"]) == ("repository", 1011)
    assert (org[0]["scope_kind"], org[0]["scope_id"]) == ("organization", 1010)
    assert repo[0]["repository_id"] == 1011 and repo[0]["organization_id"] is None
    assert org[0]["organization_id"] == 1010 and org[0]["repository_id"] is None
    assert repo[0]["must_match"] == ["SYNTHETIC_"]


def test_configuration_retains_rounded_percentages_as_observations(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, secret.respond)
    rows = rows_for(contract, "secret_scanning_pattern_configurations", organization="secret-fixture")
    assert rows[0]["organization_id"] == 1010
    provider = rows[0]["provider_pattern_overrides"][0]
    assert (provider["alert_total"], provider["false_positives"], provider["false_positive_rate"]) == (
        7,
        2,
        29,
    )
    assert rows[0]["custom_pattern_overrides"][0]["false_positive_rate"] == 33


def test_delegated_request_roles_and_alert_number_text_are_not_coerced(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, secret.respond)
    row = rows_for(
        contract,
        "secret_scanning_dismissal_requests",
        repository="secret-fixture/alpha",
        secret_scanning_alert_number=2,
    )[0]
    assert row["request_number"] == 91 and row["data"][0]["alert_number"] == "2"
    assert row["requester_login"] == "alice"
    assert row["responses"][0]["reviewer"]["actor_name"] == "bob"


def test_malformed_location_variant_fails_without_erasing_details(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    changed = deepcopy(secret.LOCATIONS)
    changed[1][0]["details"].pop("commit_sha")
    monkeypatch.setattr(secret, "LOCATIONS", changed)
    install(monkeypatch, secret.respond)
    with pytest.raises(GeneratedContractError, match="variant"):
        rows_for(
            contract,
            "secret_scanning_locations",
            repository="secret-fixture/alpha",
            secret_scanning_alert_number=1,
        )


def test_missing_alert_identity_fails_instead_of_skipping_row(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    changed = deepcopy(secret.ALERTS)
    changed["alpha"][0].pop("number")
    monkeypatch.setattr(secret, "ALERTS", changed)
    install(monkeypatch, secret.respond)
    with pytest.raises(GeneratedContractError, match="required|NULL|non.null"):
        rows_for(contract, "secret_scanning_alerts", repository="secret-fixture/alpha")


def test_exact_bypass_number_mismatch_fails(pilot, secret, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        response = secret.respond(request)
        if request.url.path.endswith("/bypass-requests/secret-scanning/41"):
            data = response.json()
            data["number"] = 42
            return httpx.Response(200, json=data, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(
            contract,
            "secret_scanning_bypass_requests",
            repository="secret-fixture/alpha",
            secret_scanning_bypass_number=41,
        )


def test_later_location_page_error_is_not_partial_population(pilot, secret, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/locations") and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Not accessible"}, request=request)
        return secret.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="403|accessible"):
        rows_for(
            contract,
            "secret_scanning_locations",
            repository="secret-fixture/alpha",
            secret_scanning_alert_number=1,
        )


def test_incompatible_selectors_fail_before_http(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, secret.respond)
    with pytest.raises(GeneratedContractError, match="argument|route|consume"):
        rows_for(
            contract,
            "secret_scanning_alerts",
            repository="secret-fixture/alpha",
            secret_scanning_alert_number=1,
            secret_scanning_state="open",
        )
    assert requests == []


def test_empty_collections_are_empty_while_latest_snapshot_remains_one_repository(pilot, secret, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, secret.respond)
    for name in [
        "secret_scanning_alerts",
        "secret_scanning_locations",
        "secret_scanning_bypass_requests",
        "secret_scanning_dismissal_requests",
        "secret_scanning_custom_patterns",
    ]:
        assert rows_for(contract, name, repository="secret-fixture/empty") == []
    rows = rows_for(contract, "secret_scanning_scan_snapshots", repository="secret-fixture/empty")
    assert len(rows) == 1 and rows[0]["incremental_scans"] == []
