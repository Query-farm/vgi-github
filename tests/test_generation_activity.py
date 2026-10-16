"""Activity retrieval directions preserve entity, caller and retained-feed populations."""

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
def activity(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import activity_fixture

    return activity_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_activity_selects_every_twenty_four_read_operation():
    domain = json.loads((ROOT / "generation/domains/activity.json").read_text())
    assert {row["transport"]["operation_id"] for row in domain["entities"]} == {
        "users/get-authenticated",
        "activity/check-repo-is-starred-by-authenticated-user",
        "activity/get-feeds",
        "activity/get-repo-subscription",
        "activity/get-stargazer-count-for-repo",
        "activity/get-stargazer-history-for-repo",
        "activity/get-thread",
        "activity/get-thread-subscription-for-authenticated-user",
        "activity/list-events-for-authenticated-user",
        "activity/list-notifications-for-authenticated-user",
        "activity/list-org-events-for-authenticated-user",
        "activity/list-public-events",
        "activity/list-public-events-for-repo-network",
        "activity/list-public-events-for-user",
        "activity/list-public-org-events",
        "activity/list-received-events-for-user",
        "activity/list-received-public-events-for-user",
        "activity/list-repo-events",
        "activity/list-repo-notifications-for-authenticated-user",
        "activity/list-repos-starred-by-authenticated-user",
        "activity/list-repos-starred-by-user",
        "activity/list-repos-watched-by-user",
        "activity/list-stargazers-for-repo",
        "activity/list-watched-repos-for-authenticated-user",
        "activity/list-watchers-for-repo",
    }
    assert len(domain["functions"]) == 10
    assert len(domain["relationships"]) == 14


@pytest.mark.parametrize("name,role", [("repository_stars", "stargazer"), ("repository_watchers", "watcher")])
def test_bidirectional_relations_share_canonical_rows(pilot, activity, monkeypatch, name, role):
    _, contract, _ = pilot
    requests = install(monkeypatch, activity.respond)
    by_repo = rows_for(contract, name, organization="activity-fixture")
    by_user = rows_for(contract, name, user="activity-fixture-user")
    by_caller = rows_for(contract, name)
    assert by_user == [row for row in by_repo if row[role + "_id"] == 6110]
    assert by_caller == [row for row in by_repo if row[role + "_id"] == 903]
    assert len(by_repo) == 2
    assert rows_for(contract, name, owner="activity-fixture") == by_repo
    assert (
        rows_for(
            contract,
            name,
            repositories=[{"repository": "activity-fixture/alpha"}, {"repository": "activity-fixture/beta"}],
        )
        == by_repo
    )
    assert rows_for(contract, name, repositories=[]) == []
    if name == "repository_stars":
        assert by_user[0]["starred_at"].day == 1
        assert by_caller[0]["starred_at"].day == 2
        assert {
            request.headers["accept"] for request in requests if request.url.path.endswith("/starred")
        } == {"application/vnd.github.star+json", "application/vnd.github.v3.star+json"}


def test_missing_stargazer_identity_fails_instead_of_silently_dropping_row(pilot, activity, monkeypatch):
    _, contract, _ = pilot

    def handler(request):
        if request.url.path.endswith("/stargazers"):
            return httpx.Response(200, json=[{"starred_at": "2026-01-01T00:00:00Z", "user": None}])
        return activity.respond(request)

    install(monkeypatch, handler)
    with pytest.raises(GeneratedContractError, match="stargazer_id|non-null|NULL"):
        rows_for(contract, "repository_stars", repository="activity-fixture/alpha")


def test_current_counts_and_weekly_history_are_distinct_populations(pilot, activity, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, activity.respond)
    current = rows_for(contract, "repository_star_counts", organization="activity-fixture")
    assert [(row["repository_id"], row["current_count"]) for row in current] == [(6101, 2), (6102, 0)]
    history = rows_for(contract, "repository_star_history", organization="activity-fixture")
    assert [(row["repository_id"], row["week_unix"], row["total"]) for row in history] == [
        (6101, 1754784000, 2),
        (6101, 1754179200, 1),
        (6102, 1754784000, 0),
    ]
    assert history[0]["days"] == [1, 1, 0, 0, 0, 0, 0]
    assert any(
        request.url.path.endswith("/history") and request.url.params.get("page") == "2"
        for request in requests
    )


def test_subscriptions_keep_requester_and_ignored_state(pilot, activity, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, activity.respond)
    rows = rows_for(contract, "repository_subscriptions", organization="activity-fixture")
    assert [(row["caller_id"], row["repository_id"], row["subscribed"], row["ignored"]) for row in rows] == [
        (903, 6101, False, True),
        (903, 6102, True, False),
    ]
    assert rows_for(contract, "repository_subscriptions") == [rows[1]]


def test_star_predicate_keeps_negative_without_repository_hydration(pilot, activity, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, activity.respond)
    assert (
        rows_for(contract, "repository_star_observations", repository="activity-fixture/alpha")[0][
            "status_code"
        ]
        == 204
    )
    assert (
        rows_for(contract, "repository_star_observations", repository="activity-fixture/missing")[0][
            "status_code"
        ]
        == 404
    )
    assert not any(request.url.path.startswith("/repos/") for request in requests)


def test_notification_parent_population_and_typed_decimal_thread_identity(pilot, activity, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, activity.respond)
    rows = rows_for(contract, "notifications")
    assert [
        (row["caller_id"], row["notification_thread_id"], row["repository_id"], row["unread"]) for row in rows
    ] == [(903, "7101", 6101, True), (903, "7102", 6101, False), (903, "7103", 6102, True)]
    assert rows_for(contract, "notifications", repository="activity-fixture/alpha") == rows[:2]
    assert rows_for(contract, "notifications", notification_thread_id="7102") == [rows[1]]
    assert rows_for(contract, "notifications", notification_participating=True) == [rows[0]]
    subscriptions = rows_for(contract, "notification_subscriptions")
    assert [(row["notification_thread_id"], row["subscribed"], row["ignored"]) for row in subscriptions] == [
        ("7101", True, False),
        ("7102", False, True),
        ("7103", True, False),
    ]
    assert subscriptions[1]["created_at"] is None
    assert any(request.url.path == "/notifications/threads/7103/subscription" for request in requests)
    assert rows[0]["updated_at_raw"] == "2026-05-01T00:00:00Z"


@pytest.mark.parametrize("identity", ["01", "-1", "1.0", " 1", "١", "9223372036854775808"])
def test_invalid_notification_integer_path_identity_never_reaches_thread_http(
    pilot, activity, monkeypatch, identity
):
    _, contract, _ = pilot
    requests = install(monkeypatch, activity.respond)
    with pytest.raises(GeneratedContractError, match="decimal|BIGINT|canonical|integer"):
        rows_for(contract, "notifications", notification_thread_id=identity)
    assert all(not request.url.path.startswith("/notifications/threads/") for request in requests)


@pytest.mark.parametrize(
    "arguments,identities",
    [
        ({}, ["E6101", "E6103"]),
        ({"activity_view": "public"}, ["E6101", "E6103"]),
        ({"user": "activity-fixture-user"}, ["E6101"]),
        ({"user": "activity-fixture-user", "activity_view": "performed"}, ["E6101"]),
        ({"user": "activity-fixture-user", "activity_view": "performed_public"}, ["E6101"]),
        ({"user": "activity-fixture-user", "activity_view": "received"}, ["E6101", "E6102"]),
        ({"user": "activity-fixture-user", "activity_view": "received_public"}, ["E6101"]),
        ({"organization": "activity-fixture"}, ["E6101", "E6103"]),
        (
            {
                "user": "activity-fixture-user",
                "organization": "activity-fixture",
                "activity_view": "organization_authenticated",
            },
            ["E6101", "E6102", "E6103"],
        ),
        ({"repository": "activity-fixture/alpha"}, ["E6101", "E6103"]),
        ({"repository": "activity-fixture/alpha", "activity_view": "network"}, ["E6101", "E6102", "E6103"]),
    ],
)
def test_event_populations_share_envelope_identity_and_keep_nullable_types(
    pilot, activity, monkeypatch, arguments, identities
):
    _, contract, _ = pilot
    install(monkeypatch, activity.respond)
    rows = rows_for(contract, "activity_events", **arguments)
    assert [row["event_id"] for row in rows] == identities
    assert "payload" not in rows[0]
    if "E6102" in identities:
        unknown = next(row for row in rows if row["event_id"] == "E6102")
        assert unknown["event_type"] is None
        assert unknown["created_at"] is None
        assert unknown["organization_id"] is None


def test_event_retention_boundary_fails_and_feed_urls_are_never_followed(pilot, activity, monkeypatch):
    _, original, _ = pilot
    contract = deepcopy(original)
    source = next(row for row in contract["entities"] if row["name"] == "activity_events_public_source")
    assert source["transport"]["pagination"]["reject_at_rows"] == 300
    source["transport"]["pagination"]["reject_at_rows"] = 2
    requests = install(monkeypatch, activity.respond)
    with pytest.raises(GeneratedContractError, match="completeness boundary"):
        rows_for(contract, "activity_events")
    requests.clear()
    feeds = rows_for(contract, "activity_feed_observations")
    assert feeds[0]["links"]["timeline"]["type"] == "application/atom+xml"
    assert len(feeds[0]["current_user_organization_urls"]) == 2
    assert len(requests) == 1
    assert requests[0].url.path == "/feeds"


@pytest.mark.parametrize(
    "name,failed_path",
    [
        ("repository_stars", "/repos/activity-fixture/alpha/stargazers"),
        ("repository_star_history", "/repos/activity-fixture/alpha/stargazers/history"),
        ("notifications", "/notifications"),
    ],
)
def test_later_activity_page_failure_aborts_population(pilot, activity, monkeypatch, name, failed_path):
    _, contract, _ = pilot

    def handler(request):
        if request.url.path == failed_path and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Forbidden"})
        return activity.respond(request)

    install(monkeypatch, handler)
    with pytest.raises(GitHubError, match="403"):
        rows_for(
            contract, name, **({} if name == "notifications" else {"repository": "activity-fixture/alpha"})
        )
