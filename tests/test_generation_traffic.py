"""Rolling traffic totals, bucket grains and bounded popular populations stay distinct."""

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
from vgi_github.github_api import GitHubError


@pytest.fixture
def traffic(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import traffic_fixture

    return traffic_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_traffic_declares_four_operations_and_nonadditive_unique_metrics():
    domain = json.loads((ROOT / "generation/domains/traffic.json").read_text())
    assert {source["transport"]["operation_id"] for source in domain["entities"]} == {
        "repos/get-clones",
        "repos/get-views",
        "repos/get-top-paths",
        "repos/get-top-referrers",
    }
    assert len(domain["entities"]) == len(domain["functions"]) == len(domain["relationships"]) == 6
    for entity in domain["functions"]:
        assert entity["grain"][0] == "repository_id"
        for name, metric in entity["semantics"]["crossfield"]["metric_semantics"].items():
            if "unique" in name:
                assert metric["additivity"] == "non_additive"


def test_traffic_window_unique_counts_are_not_sums_of_bucket_uniques(pilot, traffic, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, traffic.respond)
    rows = rows_for(contract, "repository_clone_traffic", organization="traffic-fixture")
    assert [
        (r["repository_id"], r["total_count"], r["unique_count"], r["traffic_granularity"]) for r in rows
    ] == [
        (6501, 8, 4, "day"),
        (6502, 0, 0, "day"),
    ]
    assert sum(bucket["uniques"] for bucket in rows[0]["buckets"]) == 5
    assert rows[0]["buckets"][0]["timestamp"] == datetime(2026, 5, 4, tzinfo=UTC)
    assert rows[1]["buckets"] == []
    assert any(r.url.params.get("page") == "2" for r in requests)
    assert all(r.url.params.get("per") == "day" for r in requests if "/traffic/" in r.url.path)
    weekly = rows_for(
        contract, "repository_clone_traffic", owner="traffic-fixture", traffic_granularity="week"
    )
    assert [(r["total_count"], r["unique_count"], len(r["buckets"])) for r in weekly] == [
        (8, 4, 1),
        (0, 0, 0),
    ]


@pytest.mark.parametrize(
    "name,day_count,week_count",
    [
        ("repository_clone_traffic_buckets", 2, 1),
        ("repository_view_traffic_buckets", 3, 2),
    ],
)
def test_traffic_bucket_grains_include_aggregation(pilot, traffic, monkeypatch, name, day_count, week_count):
    _, contract, _ = pilot
    install(monkeypatch, traffic.respond)
    daily = rows_for(contract, name, organization="traffic-fixture")
    weekly = rows_for(contract, name, organization="traffic-fixture", traffic_granularity="week")
    assert len(daily) == day_count
    assert len(weekly) == week_count
    assert {r["traffic_granularity"] for r in daily} == {"day"}
    assert {r["traffic_granularity"] for r in weekly} == {"week"}
    assert sum(r["event_count"] for r in daily) == sum(r["event_count"] for r in weekly)


@pytest.mark.parametrize(
    "name,keys",
    [
        ("repository_top_paths", ["/one", "/two", "/"]),
        ("repository_top_referrers", ["Google", "Direct"]),
    ],
)
def test_popular_populations_keep_order_and_repository_grain(pilot, traffic, monkeypatch, name, keys):
    _, contract, _ = pilot
    install(monkeypatch, traffic.respond)
    rows = rows_for(contract, name, organization="traffic-fixture")
    key = "path" if name.endswith("paths") else "referrer"
    assert [r[key] for r in rows] == keys
    assert [r["response_position"] for r in rows] == ([1, 2, 1] if key == "path" else [1, 2])


def test_traffic_empty_cohort_and_nonempty_cohort_do_not_change_window_semantics(pilot, traffic, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, traffic.respond)
    assert rows_for(contract, "repository_view_traffic", repositories=[]) == []
    assert requests == []
    rows = rows_for(
        contract, "repository_view_traffic", repositories=[{"repository": "traffic-fixture/beta"}]
    )
    assert [(r["repository_id"], r["total_count"], r["unique_count"]) for r in rows] == [(6502, 2, 2)]


@pytest.mark.parametrize("failure", ["denied", "wrong_nested_type", "duplicate_bucket", "unadvertised_page"])
def test_traffic_invalid_or_inaccessible_population_fails(pilot, traffic, monkeypatch, failure):
    _, contract, _ = pilot

    def handler(request):
        if request.url.path.endswith("/traffic/clones"):
            if failure == "denied":
                return httpx.Response(403, json={"message": "Forbidden"})
            payload = deepcopy(traffic.TRAFFIC[("alpha", "clones", "day")])
            if failure == "wrong_nested_type":
                payload["clones"][0]["uniques"] = "2"
            if failure == "duplicate_bucket":
                payload["clones"][1]["timestamp"] = payload["clones"][0]["timestamp"]
            headers = (
                {"Link": '<https://api.github.com/next>; rel="next"'}
                if failure == "unadvertised_page"
                else {}
            )
            return httpx.Response(200, json=payload, headers=headers)
        return traffic.respond(request)

    install(monkeypatch, handler)
    with pytest.raises((GeneratedContractError, GitHubError)):
        rows_for(contract, "repository_clone_traffic_buckets", repository="traffic-fixture/alpha")
