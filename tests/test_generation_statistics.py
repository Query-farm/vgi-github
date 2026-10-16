"""Statistics preserve typed tuples/series, pending responses and nullable authors."""

import json
from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.github_api import GitHubError


@pytest.fixture
def statistics(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import statistics_fixture

    return statistics_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_statistics_selects_five_operations_with_explicit_tuple_contracts():
    domain = json.loads((ROOT / "generation/domains/statistics.json").read_text())
    assert {source["transport"]["operation_id"] for source in domain["entities"]} == {
        "repos/get-code-frequency-stats",
        "repos/get-commit-activity-stats",
        "repos/get-contributors-stats",
        "repos/get-participation-stats",
        "repos/get-punch-card-stats",
    }
    assert len(domain["entities"]) == len(domain["functions"]) == 5
    assert len(domain["relationships"]) == 6
    for source in domain["entities"]:
        if "item_length" in source["transport"]:
            assert source["transport"]["item_length"] == 3
            assert [c["source_index"] for c in source["columns"] if "source_index" in c] == [0, 1, 2]


def test_code_frequency_preserves_signed_values_and_explicit_204_empty(pilot, statistics, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, statistics.respond)
    rows = rows_for(contract, "repository_code_frequency", organization="statistics-fixture")
    assert [(r["repository_id"], r["week_epoch"], r["additions"], r["deletions"]) for r in rows] == [
        (6601, 1704585600, 12, -4),
        (6601, 1705190400, 8, -3),
    ]
    assert rows_for(contract, "repository_code_frequency", repository="statistics-fixture/beta") == []


def test_commit_activity_and_punch_cards_keep_distinct_temporal_meanings(pilot, statistics, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, statistics.respond)
    rows = rows_for(contract, "repository_commit_activity", organization="statistics-fixture")
    assert [r["commit_count"] for r in rows] == [4, 3, 2]
    assert rows[0]["daily_commits"] == [0, 1, 0, 2, 1, 0, 0]
    punch = rows_for(contract, "repository_commit_punch_card", owner="statistics-fixture")
    assert [(r["day_of_week"], r["hour_of_day"], r["commit_count"]) for r in punch] == [
        (0, 9, 2),
        (2, 14, 5),
        (6, 22, 3),
    ]


def test_nullable_contributors_are_retained_as_snapshot_positions(pilot, statistics, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, statistics.respond)
    rows = rows_for(contract, "repository_contributor_statistics", organization="statistics-fixture")
    assert [
        (r["repository_id"], r["response_position"], r["author_id"], r["total_commits"]) for r in rows
    ] == [
        (6601, 1, 6650, 7),
        (6601, 2, None, 2),
        (6602, 1, 6651, 3),
    ]
    assert rows[1]["author"] is None
    assert rows[0]["weeks"][1] == {"w": 1705190400, "a": 8, "d": 3, "c": 3}
    assert rows[1]["weeks"][0]["a"] == 0


def test_participation_retains_ordered_series_and_empty_cohorts(pilot, statistics, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, statistics.respond)
    assert rows_for(contract, "repository_participation_statistics", repositories=[]) == []
    assert requests == []
    rows = rows_for(
        contract,
        "repository_participation_statistics",
        repositories=[{"repository": "statistics-fixture/alpha"}],
    )
    assert len(rows) == 1
    assert len(rows[0]["all_commits"]) == len(rows[0]["owner_commits"]) == 52
    assert rows[0]["all_commits"][-2:] == [4, 3]
    assert rows[0]["owner_commits"][-2:] == [1, 1]


@pytest.mark.parametrize(
    "failure",
    [
        "pending",
        "large_repository",
        "extra_tuple_item",
        "bool_tuple",
        "duplicate_week",
        "invalid_nested_week",
    ],
)
def test_statistics_pending_and_malformed_data_cannot_be_zero_or_complete(
    pilot, statistics, monkeypatch, failure
):
    _, contract, _ = pilot

    def handler(request):
        if "/stats/" in request.url.path:
            if failure == "pending":
                return httpx.Response(202, json={"message": "Computing statistics"})
            if failure == "large_repository":
                return httpx.Response(422, json={"message": "Repository has too many commits"})
            if failure == "invalid_nested_week":
                rows = deepcopy(statistics.STATISTICS[("alpha", "contributors")])
                rows[0]["weeks"][0]["w"] = "1704585600"
            else:
                rows = deepcopy(statistics.STATISTICS[("alpha", "code_frequency")])
                if failure == "extra_tuple_item":
                    rows[0].append(99)
                if failure == "bool_tuple":
                    rows[0][1] = True
                if failure == "duplicate_week":
                    rows[1][0] = rows[0][0]
            return httpx.Response(200, json=rows)
        return statistics.respond(request)

    install(monkeypatch, handler)
    name = (
        "repository_contributor_statistics"
        if failure == "invalid_nested_week"
        else "repository_code_frequency"
    )
    with pytest.raises((GeneratedContractError, GitHubError)):
        rows_for(contract, name, repository="statistics-fixture/alpha")
