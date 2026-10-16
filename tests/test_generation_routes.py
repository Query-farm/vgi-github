"""Alternative retrieval plans preserve one business grain and author role."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts import generate_semantic_catalog as generator
from tests.helpers import install
from tests.test_functions import _Out, _Params
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError, make_function
from vgi_github.generation.schema import compile_contract


@pytest.fixture
def connected(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import connected_fixture

    return connected_fixture


def scan(contract, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == "pull_requests")
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_routes_preserve_common_pr_fields_and_full_response_availability(pilot, connected, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, connected.respond)
    by_author = scan(contract, user="alice")
    assert [(row["repository_id"], row["pull_request_number"]) for row in by_author] == [
        (101, 1),
        (101, 3),
        (102, 1),
        (301, 1),
    ]
    assert [row["state"] for row in by_author] == ["closed", "open", "closed", "closed"]
    assert [label["name"] for label in by_author[0]["labels"]] == ["bug", "docs"]
    assert [assignee["login"] for assignee in by_author[0]["assignees"]] == ["alice", "bob"]
    requests.clear()
    intersection = scan(contract, repository="example/alpha", user="alice")
    detail_only = (
        "comments_count",
        "review_comments_count",
        "commits_count",
        "additions",
        "deletions",
        "changed_files",
        "merged",
        "mergeable",
        "rebaseable",
        "mergeable_state",
        "maintainer_can_modify",
        "merged_by",
    )
    assert intersection == [{**row, **dict.fromkeys(detail_only)} for row in by_author[:2]]
    assert [row["comments_count"] for row in by_author[:2]] == [0, 0]
    assert all(request.method == "GET" for request in requests)


def test_author_selection_prunes_reviews_before_fetching_them(pilot, connected, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        assert request.url.path != "/repos/example/alpha/pulls/2/reviews"
        return connected.respond(request)

    install(monkeypatch, respond)
    entity = next(value for value in contract["functions"] if value["name"] == "pull_request_reviews")
    output = run(entity, {"repository": ["example/alpha"], "user": ["alice"]}, contract=contract)
    rows = [row for batch in output.batches for row in batch.to_pylist()]
    assert [(row["review_id"], row["reviewer_login"]) for row in rows] == [(11, "bob"), (12, "alice")]


def test_author_route_emits_hydrated_pr_before_discovering_next_page(pilot, connected, monkeypatch):
    _, contract, _ = pilot
    output = _Out()
    discoveries = 0

    def respond(request):
        nonlocal discoveries
        if request.method == "POST":
            assert sum(batch.num_rows for batch in output.batches) == discoveries
            discoveries += 1
        return connected.respond(request)

    install(monkeypatch, respond)
    entity = next(value for value in contract["functions"] if value["name"] == "pull_requests")
    run(entity, {"user": ["alice"]}, contract=contract, out=output)
    assert discoveries == 4 and output.finished


def test_every_route_emits_the_common_public_schema(pilot, connected, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, connected.respond)
    entity = next(value for value in contract["functions"] if value["name"] == "pull_requests")
    function = make_function(entity, contract)
    for arguments in ({"user": "alice"}, {"repository": "example/alpha"}):
        params = _Params(SimpleNamespace(**arguments), function.FIXED_SCHEMA)
        state, output = function.initial_state(params), _Out()
        for _ in range(100):
            function.process(params, state, output)
            if output.finished:
                break
        assert output.finished and any(batch.num_rows for batch in output.batches)
        assert all(
            batch.schema.equals(function.FIXED_SCHEMA, check_metadata=True) for batch in output.batches
        )


def test_intersection_uses_canonical_author_identity_and_rejects_alias_duplicates(
    pilot, connected, monkeypatch
):
    _, contract, _ = pilot
    monkeypatch.setitem(connected.USERS, "old-alice", connected.USERS["alice"])
    requests = install(monkeypatch, connected.respond)
    assert len(scan(contract, repository="example/alpha", user="old-alice")) == 2
    requests.clear()
    with pytest.raises(GeneratedContractError, match="duplicate row identity"):
        scan(contract, repository="example/alpha", users=[{"login": "alice"}, {"login": "old-alice"}])
    assert not any(request.url.path.startswith("/repos/") for request in requests)


@pytest.mark.parametrize(
    "arguments",
    [
        {"repository": "example/alpha", "users": []},
        {"repositories": [], "user": "alice"},
        {"users": []},
    ],
)
def test_empty_intersection_performs_no_http(pilot, monkeypatch, arguments):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Empty selection must not fetch"))
    assert scan(contract, **arguments) == []


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"owner": "example", "repository": "example/alpha"},
        {"user": "alice", "users": [{"login": "bob"}]},
        {"repository": "example/alpha", "user": "alice", "users": [{"login": "bob"}]},
        {"user": "alice", "pull_request_number": 1},
    ],
)
def test_invalid_route_inputs_reject_before_http(pilot, monkeypatch, arguments):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid selection must not fetch"))
    with pytest.raises(GeneratedContractError):
        scan(contract, **arguments)


def test_alternative_routes_must_expose_identical_fields(pilot):
    overlay, _, _ = pilot
    overlay = deepcopy(overlay)
    function = next(value for value in overlay["functions"] if value["name"] == "pull_requests")
    route = next(route for route in function["routes"] if route["name"] == "labels")
    route["columns"] = [column for column in route["columns"] if column["name"] != "title"]
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match="same named public columns"):
        compile_contract(specs, sdl, overlay)


@pytest.fixture
def retrieval(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import research_fixture

    return research_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "entity,arguments,key,expected",
    [
        ("organizations", {"user": "alice"}, "organization_id", [100, 401]),
        ("organizations", {"users": [{"login": "alice"}, {"login": "carol"}]}, "organization_id", [100, 401]),
        ("organizations", {"owner": "example"}, "organization_id", [100]),
        ("organizations", {"owner": "public-user"}, "organization_id", []),
        ("organization_memberships", {"user": "alice"}, "organization_id", [100, 401]),
        ("organization_memberships", {"user": "bob"}, "organization_id", []),
        ("users", {"organization": "example"}, "user_id", [201, 203]),
        ("users", {"organization": "example", "team_slug": "core"}, "user_id", [201, 203]),
        ("users", {"organization": "example", "team_slug": "empty"}, "user_id", []),
        ("users", {"owner": "example"}, "user_id", [201, 202, 203]),
        ("teams", {"organization": "example", "team_slug": "docs"}, "team_id", [502]),
        ("teams", {"owner": "example"}, "team_id", [501, 502]),
        ("team_memberships", {"organization": "example", "team_slug": "core"}, "user_id", [201, 203]),
        ("team_memberships", {"organization": "example", "user": "alice"}, "team_id", [501, 502]),
        ("repositories", {"organization": "example", "team_slug": "core"}, "repository_id", [101, 102]),
        ("repositories", {"organization": "example", "team_slug": "empty"}, "repository_id", []),
        ("pull_requests", {"repository": "example/alpha", "label": "bug"}, "pull_request_id", [1001, 1002]),
        (
            "pull_requests",
            {"repository": "example/alpha", "label": "bug", "user": "alice"},
            "pull_request_id",
            [1001],
        ),
        ("pull_request_reviews", {"repository": "example/alpha", "label": "bug"}, "review_id", [11, 12, 13]),
        (
            "repository_labels",
            {"repository": "example/alpha", "pull_request_number": 1},
            "name",
            ["bug", "docs"],
        ),
        ("repository_labels", {"repository": "example/alpha", "issue_number": 2}, "name", ["bug"]),
        ("issues", {"repository": "example/alpha"}, "issue_node_id", ["I1", "I2", "I3"]),
        ("issues", {"organization": "example"}, "issue_node_id", ["I1", "I2", "I3", "I4"]),
        ("issues", {"repository": "example/alpha", "user": "alice"}, "issue_node_id", ["I1"]),
        ("issues", {"repository": "example/alpha", "label": "bug"}, "issue_node_id", ["I1", "I2"]),
        ("discussions", {"owner": "example"}, "discussion_node_id", ["D1", "D2", "D3"]),
        ("discussions", {"repository": "example/alpha", "user": "bob"}, "discussion_node_id", ["D2"]),
        ("issue_comments", {"repository": "example/alpha"}, "comment_node_id", ["IC1", "IC2", "IC3"]),
        (
            "issue_comments",
            {"repository": "example/alpha", "issue_number": 2},
            "comment_node_id",
            ["IC2", "IC3"],
        ),
        (
            "issue_comments",
            {"repository": "example/alpha", "issue_number": 2, "user": "bob"},
            "comment_node_id",
            ["IC2"],
        ),
        (
            "discussion_comments",
            {"organization": "example"},
            "comment_node_id",
            ["C1", "C2", "R1", "R2", "N1", "C3"],
        ),
        (
            "discussion_comments",
            {"repository": "example/alpha"},
            "comment_node_id",
            ["C1", "R1", "N1", "R2", "C2", "C3"],
        ),
        (
            "discussion_comments",
            {"repository": "example/alpha", "discussion_number": 1},
            "comment_node_id",
            ["C1", "R1", "N1", "R2", "C2"],
        ),
        (
            "discussion_comments",
            {"repository": "example/alpha", "discussion_number": 1, "user": "alice"},
            "comment_node_id",
            ["C1", "N1"],
        ),
        ("discussion_comments", {"discussion_comment_id": "C1"}, "comment_node_id", ["R1", "N1", "R2"]),
        ("discussion_comments", {"discussion_comment_id": "C1", "user": "alice"}, "comment_node_id", ["N1"]),
        ("commit_comments", {"owner": "example"}, "comment_node_id", ["CC1", "CC2", "CC3"]),
        ("commit_comments", {"repository": "example/alpha", "user": "bob"}, "comment_node_id", ["CC2"]),
    ],
)
def test_reverse_route_populations(pilot, retrieval, monkeypatch, entity, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, retrieval.respond)
    rows = rows_for(contract, entity, **arguments)
    assert [row[key] for row in rows] == expected


@pytest.mark.parametrize(
    "entity", ["issues", "discussions", "issue_comments", "discussion_comments", "commit_comments"]
)
def test_author_and_repository_routes_return_identical_canonical_rows(pilot, retrieval, monkeypatch, entity):
    _, contract, _ = pilot
    install(monkeypatch, retrieval.respond)
    by_author = rows_for(contract, entity, user="alice")
    by_repository = rows_for(contract, entity, repository="example/alpha", user="alice")
    assert sorted(by_repository, key=lambda row: str(row)) == sorted(by_author, key=lambda row: str(row))


def test_membership_pairs_are_not_collapsed_with_repeated_organizations(pilot, retrieval, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, retrieval.respond)
    rows = rows_for(contract, "organization_memberships", users=[{"login": "alice"}, {"login": "carol"}])
    assert [(row["organization_id"], row["user_id"]) for row in rows] == [(100, 201), (401, 201), (100, 203)]


def test_null_author_keeps_repository_activity(pilot, retrieval, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, retrieval.respond)
    issues = rows_for(contract, "issues", repository="example/alpha")
    assert [(row["issue_node_id"], row["author_id"]) for row in issues] == [
        ("I1", 201),
        ("I2", 202),
        ("I3", None),
    ]
    replies = rows_for(contract, "discussion_comments", discussion_comment_id="C1")
    assert [(row["comment_node_id"], row["author_id"]) for row in replies] == [
        ("R1", 202),
        ("N1", 201),
        ("R2", None),
    ]


@pytest.mark.parametrize(
    "entity,arguments",
    [
        ("users", {"team_slug": "core"}),
        ("repositories", {"team_slug": "core"}),
        ("team_memberships", {"user": "alice"}),
        ("team_memberships", {"organization": "example", "user": "alice", "users": []}),
        ("organizations", {"organization": "example", "user": "alice"}),
        ("issues", {"label": "bug"}),
        ("issue_comments", {"issue_number": 2}),
        ("discussion_comments", {"discussion_number": 1}),
        ("repository_labels", {"pull_request_number": 1}),
        ("pull_requests", {"repository": "example/alpha", "label": "bug", "pull_request_number": 1}),
    ],
)
def test_invalid_reverse_route_combinations_fail_before_http(pilot, monkeypatch, entity, arguments):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid selection must not fetch"))
    with pytest.raises(GeneratedContractError):
        rows_for(contract, entity, **arguments)


@pytest.mark.parametrize(
    "entity,arguments",
    [
        ("organizations", {"users": []}),
        ("organizations", {"repositories": []}),
        ("users", {"repositories": []}),
        ("issues", {"repositories": []}),
        ("discussion_comments", {"repositories": []}),
        ("team_memberships", {"organization": "example", "users": []}),
    ],
)
def test_empty_reverse_route_cohorts_skip_all_http(pilot, monkeypatch, entity, arguments):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Empty selection must not fetch"))
    assert rows_for(contract, entity, **arguments) == []


def test_recursive_replies_emit_before_fetching_the_next_page(pilot, retrieval, monkeypatch):
    _, contract, _ = pilot
    output = _Out()
    observations = []

    def respond(request):
        if request.method == "POST":
            import json

            body = json.loads(request.content)
            if body["variables"].get("node_id") == "C1":
                observations.append(
                    (
                        [row["comment_node_id"] for batch in output.batches for row in batch.to_pylist()],
                        body["variables"]["cursor"],
                    )
                )
        return retrieval.respond(request)

    install(monkeypatch, respond)
    entity = next(value for value in contract["functions"] if value["name"] == "discussion_comments")
    run(entity, {"repository": ["example/alpha"], "discussion_number": [1]}, contract=contract, out=output)
    assert observations == [(["C1"], None), (["C1", "R1", "N1"], "1")]


def test_late_reply_failure_propagates_after_rows_were_emitted(pilot, retrieval, monkeypatch):
    import json

    import httpx

    _, contract, _ = pilot
    output = _Out()

    def respond(request):
        if request.method == "POST":
            values = json.loads(request.content)["variables"]
            if values.get("node_id") == "C1" and values.get("cursor") == "1":
                return httpx.Response(403, json={"message": "Reply page denied"}, request=request)
        return retrieval.respond(request)

    install(monkeypatch, respond)
    entity = next(value for value in contract["functions"] if value["name"] == "discussion_comments")
    with pytest.raises(Exception, match="Reply page denied"):
        run(entity, {"discussion_comment_id": ["C1"]}, contract=contract, out=output)
    assert [row["comment_node_id"] for batch in output.batches for row in batch.to_pylist()] == ["R1", "N1"]


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("bad_selection", "selection parameters"),
        ("bad_fragment", "possible concrete types"),
        ("bad_narrowing", "possible implementation"),
        ("bad_child_schema", "complete source schema and grain"),
        ("bad_binding", "exact source field and parameter types"),
        ("bad_route", "unknown target route"),
    ],
)
def test_route_contracts_reject_invalid_navigation(pilot, mutation, error):
    from vgi_github.generation.artifacts import validate_semantics

    overlay, _, _ = pilot
    overlay = deepcopy(overlay)
    functions = {value["name"]: value for value in overlay["functions"]}
    sources = {value["name"]: value for value in overlay["entities"]}
    if mutation == "bad_selection":
        functions["organizations"]["routes"][0]["select"] = ["missing"]
    elif mutation == "bad_fragment":
        next(
            column
            for column in sources["repository_issues_source"]["columns"]
            if column["name"] == "author_id"
        )["on_types"] = ["Repository"]
    elif mutation == "bad_narrowing":
        sources["discussion_comment_replies_source"]["transport"]["field_types"]["node"] = "Actor"
    elif mutation == "bad_child_schema":
        sources["discussion_comment_replies_source"]["columns"].pop()
        functions["discussion_comments"]["routes"].sort(key=lambda route: route["name"] != "discussions")
    elif mutation == "bad_binding":
        overlay["relationships"][0]["retrievals"][0]["bindings"]["repository"] = "repository_id"
    elif mutation == "bad_route":
        overlay["relationships"][0]["retrievals"][0]["route"] = "missing"
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match=error):
        contract = compile_contract(specs, sdl, overlay)
        validate_semantics(contract, overlay)


def test_recursive_reply_cycle_rejects_instead_of_hanging(pilot, retrieval, monkeypatch):
    import retrieval_fixture

    _, contract, _ = pilot
    loop = deepcopy(retrieval_fixture.DISCUSSION_COMMENTS[0])
    loop["replyTo"] = {"id": "R1"}
    monkeypatch.setattr(
        retrieval_fixture, "DISCUSSION_COMMENTS", [*retrieval_fixture.DISCUSSION_COMMENTS, loop]
    )
    install(monkeypatch, retrieval.respond)
    with pytest.raises(GeneratedContractError, match="duplicate row identity"):
        rows_for(contract, "discussion_comments", repository="example/alpha", discussion_number=1)


def test_distinct_target_route_still_rejects_duplicate_transport_rows(pilot, retrieval, monkeypatch):
    import json

    import httpx

    _, contract, _ = pilot

    def respond(request):
        if request.url.path == "/repos/example/alpha/collaborators" and request.url.params.get("page") == "2":
            first = retrieval.respond(httpx.Request("GET", str(request.url.copy_set_param("page", "1"))))
            return httpx.Response(200, json=json.loads(first.content), request=request)
        return retrieval.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="duplicate row identity"):
        rows_for(contract, "users", repository="example/alpha")


@pytest.mark.parametrize(
    "entity,parameter,key,number,expected",
    [
        ("issues", "issue_number", "issue_node_id", 2, ["I2"]),
        ("discussions", "discussion_number", "discussion_node_id", 1, ["D1"]),
        ("discussions", "discussion_number", "discussion_node_id", 999, []),
    ],
)
def test_singleton_lookup_uses_the_entity_number(
    pilot, retrieval, monkeypatch, entity, parameter, key, number, expected
):
    _, contract, _ = pilot
    requests = install(monkeypatch, retrieval.respond)
    rows = rows_for(contract, entity, repository="example/alpha", **{parameter: number})
    assert [row[key] for row in rows] == expected
    assert len(requests) == (3 if entity == "issues" else 2)


def test_missing_issue_rest_lookup_is_an_error_not_an_empty_population(pilot, retrieval, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, retrieval.respond)
    with pytest.raises(Exception, match="404|Not Found"):
        rows_for(contract, "issues", repository="example/alpha", issue_number=999)
    assert len(requests) == 2
    assert requests[-1].url.path == "/repos/example/alpha/issues/999"


def test_unavailable_actor_identity_does_not_discard_the_fact(pilot, retrieval, monkeypatch):
    import retrieval_fixture

    _, contract, _ = pilot
    rows = deepcopy(retrieval_fixture.ISSUES)
    rows[2]["author"] = {"__typename": "EnterpriseUserAccount", "login": "enterprise-account"}
    monkeypatch.setattr(retrieval_fixture, "ISSUES", rows)
    install(monkeypatch, retrieval.respond)
    result = rows_for(contract, "issues", repository="example/alpha", issue_number=3)
    assert result[0]["author_login"] == "enterprise-account" and result[0]["author_id"] is None


def test_nonnullable_connection_null_is_an_error_not_an_empty_population(pilot, monkeypatch):
    import httpx

    _, contract, _ = pilot
    source = next(value for value in contract["entities"] if value["name"] == "repository_issues_source")
    install(
        monkeypatch,
        lambda request: httpx.Response(200, json={"data": {"repository": {"issues": None}}}, request=request),
    )
    with pytest.raises(GeneratedContractError, match="malformed GraphQL"):
        run(source, {"repository": ["example/alpha"]})
