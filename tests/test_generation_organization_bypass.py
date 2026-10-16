"""Direct org bypass retrieval preserves unknown repository evidence and reviewer roles."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from tests.test_generation_commit_evaluations import rows_for
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def bypass(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import organization_bypass_fixture

    return organization_bypass_fixture


def test_org_bypass_keeps_unknown_repository_and_canonical_known_rows(pilot, bypass, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, bypass.respond)
    rows = rows_for(contract, "push_bypass_requests", organization=bypass.OWNER)
    assert [r["bypass_request_id"] for r in rows] == [53301, 53302, 53303]
    assert rows[1]["repository_id"] is None and rows[1]["repository"] is None
    assert [len(r["responses"]) for r in rows] == [2, 0, 1]
    assert rows[0]["requester_id"] == 53101 and rows[0]["responses"][0]["reviewer"]["actor_id"] == 53102
    assert all(r.url.params.get("time_period") is None for r in requests)
    assert rows_for(contract, "push_bypass_requests", repository=bypass.OWNER + "/alpha") == rows[:1]


def test_org_bypass_filters_forward_the_reviewed_query_fields(pilot, bypass, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, bypass.respond)
    rows = rows_for(
        contract,
        "push_bypass_requests",
        organization=bypass.OWNER,
        bypass_repository_name="alpha",
        bypass_reviewer="bypass-reviewer",
        bypass_requester="bypass-requester",
        bypass_time_period="month",
        bypass_request_status="approved",
    )
    assert [r["bypass_request_id"] for r in rows] == [53301]
    assert dict(requests[-1].url.params) == {
        "per_page": "100",
        "repository_name": "alpha",
        "reviewer": "bypass-reviewer",
        "requester": "bypass-requester",
        "time_period": "month",
        "request_status": "approved",
    }


def test_org_bypass_later_page_and_wrong_optional_org_identity_fail(pilot, bypass, monkeypatch):
    _, contract, _ = pilot

    def denied(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Page denied"}, request=request)
        return bypass.respond(request)

    install(monkeypatch, denied)
    with pytest.raises(Exception, match="403|denied"):
        rows_for(contract, "push_bypass_requests", organization=bypass.OWNER)
    wrong = deepcopy(bypass.ROWS)
    wrong[0]["organization"]["id"] = 99999
    monkeypatch.setattr(bypass, "ROWS", wrong)
    install(monkeypatch, bypass.respond)
    with pytest.raises(GeneratedContractError, match="reported_organization_id|assertion"):
        rows_for(contract, "push_bypass_requests", organization=bypass.OWNER)


def test_org_bypass_invalid_or_conflicting_filters_fail_before_http(pilot, bypass, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, bypass.respond)
    for args in [
        {"organization": bypass.OWNER, "repository": bypass.OWNER + "/alpha"},
        {"organization": bypass.OWNER, "bypass_time_period": "forever"},
        {"repository": bypass.OWNER + "/alpha", "bypass_repository_name": "alpha"},
    ]:
        with pytest.raises(GeneratedContractError, match="argument|route|enum|value"):
            rows_for(contract, "push_bypass_requests", **args)
    assert requests == []
