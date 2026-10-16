"""Copilot metadata populations do not claim downloaded usage-row coverage."""

from datetime import date

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError

OWNER = "copilot-report-fixture"


@pytest.fixture
def reports(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import copilot_reports_fixture

    return copilot_reports_fixture


def rows_for(contract, **arguments):
    entity = next(row for row in contract["functions"] if row["name"] == "copilot_report_metadata")
    result = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in result.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "kind,links", [("organization_day", 2), ("repositories_day", 1), ("user_teams_day", 0), ("users_day", 1)]
)
def test_one_day_report_metadata_is_typed_and_never_follows_signed_links(
    pilot, reports, monkeypatch, kind, links
):
    _, contract, _ = pilot
    requests = install(monkeypatch, reports.respond)
    row = rows_for(
        contract, organization=OWNER, copilot_report_kind=kind, copilot_report_day=date(2026, 9, 1)
    )[0]
    assert (row["organization_id"], row["report_kind"], row["report_start_day"], row["report_end_day"]) == (
        51000,
        kind,
        date(2026, 9, 1),
        date(2026, 9, 1),
    )
    assert row["requested_day"] == date(2026, 9, 1) and len(row["download_links"]) == links
    assert all(request.url.host == "api.github.com" for request in requests)


@pytest.mark.parametrize("kind,links", [("organization_latest", 1), ("users_latest", 3)])
def test_latest_window_uses_reported_dates_and_no_invented_requested_day(
    pilot, reports, monkeypatch, kind, links
):
    _, contract, _ = pilot
    install(monkeypatch, reports.respond)
    row = rows_for(contract, organization=OWNER, copilot_report_kind=kind)[0]
    assert row["requested_day"] is None
    assert (row["report_start_day"], row["report_end_day"], len(row["download_links"])) == (
        date(2026, 8, 5),
        date(2026, 9, 1),
        links,
    )


@pytest.mark.parametrize("kind", ["organization_day", "repositories_day", "user_teams_day", "users_day"])
def test_declared_204_is_absent_report_not_a_zero_usage_record(pilot, reports, monkeypatch, kind):
    _, contract, _ = pilot
    install(monkeypatch, reports.respond)
    assert (
        rows_for(contract, organization=OWNER, copilot_report_kind=kind, copilot_report_day=date(2026, 9, 2))
        == []
    )


def test_malformed_200_and_mismatched_report_day_fail(pilot, reports, monkeypatch):
    _, contract, _ = pilot
    value = {}

    def broken(request):
        if "/metrics/reports/" in request.url.path:
            return httpx.Response(200, json=value, request=request)
        return reports.respond(request)

    install(monkeypatch, broken)
    with pytest.raises(GeneratedContractError):
        rows_for(
            contract,
            organization=OWNER,
            copilot_report_kind="organization_day",
            copilot_report_day=date(2026, 9, 1),
        )
    value.update(download_links=[], report_day="2026-09-03")
    with pytest.raises(GeneratedContractError, match="report_start_day"):
        rows_for(
            contract,
            organization=OWNER,
            copilot_report_kind="organization_day",
            copilot_report_day=date(2026, 9, 1),
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"organization": OWNER, "copilot_report_kind": "organization_day"},
        {
            "organization": OWNER,
            "copilot_report_kind": "organization_latest",
            "copilot_report_day": date(2026, 9, 1),
        },
        {"organization": OWNER, "copilot_report_kind": "unknown"},
        {"copilot_report_kind": "users_latest"},
    ],
)
def test_report_selector_conflicts_fail_without_http(pilot, reports, monkeypatch, arguments):
    _, contract, _ = pilot
    requests = install(monkeypatch, reports.respond)
    with pytest.raises(GeneratedContractError):
        rows_for(contract, **arguments)
    assert requests == []
