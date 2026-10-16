"""Independent typed-cohort traversal contracts through the real producer protocol."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_functions import _Out
from tests.test_generated_runtime import column, connected_contract, run
from vgi_github import github_api as api
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.cohorts import compile_cohorts


def users_contract():
    root = {"name": "users", "entity": "profile", "arguments": {"user": {"parameter": "user"}}}
    argument = {"name": "user", "type": "VARCHAR", "nullable": False, "position": 0, "min_length": 1}
    profile = {
        "name": "profile",
        "description": "A public user identity",
        "arguments": [argument],
        "columns": [column("user_id", "BIGINT", path=["id"]), column("login")],
        "grain": ["user_id"],
        "semantics": {},
        "transport": {
            "kind": "rest",
            "method": "GET",
            "path": "/users/{user}",
            "path_bindings": {"user": {"argument": "user"}},
            "query_bindings": {},
            "result_path": [],
            "result_shape": "object",
            "pagination": {"kind": "none"},
        },
    }
    events = {
        "name": "events",
        "description": "Independent per-user events",
        "arguments": [argument],
        "columns": [column("event_id", "BIGINT", path=["id"])],
        "grain": ["event_id"],
        "semantics": {},
        "transport": {
            "kind": "rest",
            "method": "GET",
            "path": "/users/{user}/events",
            "path_bindings": {"user": {"argument": "user"}},
            "query_bindings": {},
            "result_path": [],
            "result_shape": "array",
            "pagination": {"kind": "link"},
        },
    }
    users = {
        "name": "users",
        "description": "User cohort root",
        "arguments": [deepcopy(argument)],
        "columns": [
            column("user_id", "BIGINT", source_stage="users", source_column="user_id"),
            column("login", source_stage="users", source_column="login"),
        ],
        "grain": ["user_id"],
        "semantics": {},
        "traversal": {"stages": [deepcopy(root)], "output_stage": "users"},
    }
    activity = {
        "name": "activity",
        "description": "User event descendants",
        "arguments": [deepcopy(argument)],
        "columns": [
            column("user_id", "BIGINT", source_stage="users", source_column="user_id"),
            column("login", source_stage="users", source_column="login"),
            column("event_id", "BIGINT", source_stage="events", source_column="event_id"),
        ],
        "grain": ["user_id", "event_id"],
        "semantics": {},
        "traversal": {
            "stages": [
                deepcopy(root),
                {
                    "name": "events",
                    "entity": "events",
                    "arguments": {"user": {"stage": "users", "column": "login"}},
                },
            ],
            "output_stage": "events",
        },
    }
    contract = {"entities": [profile, events], "functions": [users, activity], "scopes": {}}
    return compile_cohorts(
        contract,
        {
            "users": {
                "parameter": "users",
                "argument": "user",
                "field": "login",
                "comment": "User logins to enumerate independently.",
                "example": [{"login": "alice"}],
            }
        },
    )


def repositories_contract():
    contract = connected_contract()
    child = contract["functions"][0]
    root = {
        "name": "repositories",
        "description": "Repository cohort root",
        "arguments": deepcopy(child["arguments"][:3]),
        "columns": [
            column("repository_id", "BIGINT", source_stage="repositories", source_column="repository_id"),
            column("repository", source_stage="repositories", source_column="repository"),
        ],
        "grain": ["repository_id"],
        "semantics": {},
        "traversal": {"stages": [deepcopy(child["traversal"]["stages"][0])], "output_stage": "repositories"},
    }
    contract["functions"].insert(0, root)
    return compile_cohorts(
        contract,
        {
            "repositories": {
                "parameter": "repositories",
                "argument": "repository",
                "field": "repository",
                "resource": "repository",
                "comment": "Selected repositories.",
                "example": [{"repository": "o/r"}],
            }
        },
    )


def test_cohort_contract_reaches_root_and_descendants_with_exact_nullable_type():
    contract = users_contract()
    for function in contract["functions"]:
        scalar, collection = function["arguments"]
        assert scalar["nullable"] and scalar["default"] is None
        assert collection["type"] == 'STRUCT("login" VARCHAR)[]'
        assert collection["nullable"] and collection["default"] is None
        assert collection["schema"]["item"]["fields"][0]["nullable"] is False


def test_cohort_enumerates_each_root_and_every_child_page_before_advancing(monkeypatch):
    contract = users_contract()
    out = _Out()

    def handle(request):
        path = request.url.path
        login = path.split("/")[2]
        if not path.endswith("/events"):
            return httpx.Response(200, json={"id": {"alice": 1, "idle": 2, "bob": 3}[login], "login": login})
        if login == "idle":
            return httpx.Response(200, json=[])
        if login == "alice" and "page" not in request.url.params:
            return httpx.Response(
                200, json=[{"id": 1}], headers={"Link": f'<{api.base_url()}{path}?page=2>; rel="next"'}
            )
        if login == "alice":
            assert sum(batch.num_rows for batch in out.batches) == 1
            return httpx.Response(200, json=[{"id": 2}])
        assert sum(batch.num_rows for batch in out.batches) == 2
        return httpx.Response(200, json=[{"id": 1}])

    requests = install(monkeypatch, handle)
    run(
        contract["functions"][1],
        {"users": [[{"login": name} for name in ["alice", "idle", "bob"]]]},
        contract=contract,
        out=out,
    )
    assert [(row["user_id"], row["event_id"]) for batch in out.batches for row in batch.to_pylist()] == [
        (1, 1),
        (1, 2),
        (3, 1),
    ]
    assert [request.url.path for request in requests] == [
        "/users/alice",
        "/users/alice/events",
        "/users/alice/events",
        "/users/idle",
        "/users/idle/events",
        "/users/bob",
        "/users/bob/events",
    ]
    assert out.finished


@pytest.mark.parametrize("function_index", [0, 1])
def test_empty_cohort_finishes_without_any_provider_call(monkeypatch, function_index):
    contract = users_contract()
    requests = install(monkeypatch, lambda request: pytest.fail("an empty cohort must not fetch"))
    out = run(contract["functions"][function_index], {"users": [[]]}, contract=contract)
    assert out.finished and not requests and not out.batches


@pytest.mark.parametrize("supplied", [None, []])
def test_null_cohort_uses_singular_argument_but_empty_conflicts_with_it(monkeypatch, supplied):
    contract = users_contract()
    requests = install(monkeypatch, lambda request: httpx.Response(200, json={"id": 1, "login": "alice"}))
    if supplied is None:
        out = run(contract["functions"][0], {"user": ["alice"], "users": [None]}, contract=contract)
        assert out.finished and len(requests) == 1
    else:
        with pytest.raises(GeneratedContractError, match="exactly one"):
            run(contract["functions"][0], {"user": ["alice"], "users": [supplied]}, contract=contract)
        assert not requests


@pytest.mark.parametrize(
    "rows",
    [
        [None],
        [{"login": None}],
        [{"login": ""}],
        [{"login": "   "}],
        [{"login": "alice"}, {"login": "ALICE"}],
        [{"login": "alice"}, {"login": ""}],
    ],
)
def test_entire_user_cohort_is_validated_before_first_request(monkeypatch, rows):
    contract = users_contract()
    requests = install(monkeypatch, lambda request: pytest.fail("invalid cohort must fail before HTTP"))
    with pytest.raises(GeneratedContractError):
        run(contract["functions"][1], {"users": [rows]}, contract=contract)
    assert not requests


@pytest.mark.parametrize(
    "inputs",
    [
        {"repository": ["o/r"], "repositories": [[{"repository": "o/s"}]]},
        {"owner": ["o"], "repositories": [[{"repository": "o/s"}]]},
        {"organization": ["o"], "repositories": [[{"repository": "o/s"}]]},
        {"pull_request_number": [7], "repositories": [[{"repository": "o/r"}]]},
        {"repositories": [[{"repository": "o/r"}, {"repository": "O/R"}]]},
        {"repositories": [[{"repository": "o/r"}, {"repository": "broken"}]]},
    ],
)
def test_repository_cohort_conflicts_and_bad_names_fail_before_http(monkeypatch, inputs):
    contract = repositories_contract()
    requests = install(
        monkeypatch, lambda request: pytest.fail("invalid repository cohort must fail before HTTP")
    )
    with pytest.raises((GeneratedContractError, api.GitHubInputError)):
        run(contract["functions"][1], inputs, contract=contract)
    assert not requests


def test_distinct_input_aliases_cannot_duplicate_canonical_user_identity(monkeypatch):
    contract = users_contract()
    requests = install(monkeypatch, lambda request: httpx.Response(200, json={"id": 1, "login": "canonical"}))
    out = _Out()
    with pytest.raises(GeneratedContractError, match="duplicate row identity"):
        run(
            contract["functions"][0],
            {"users": [[{"login": "old-name"}, {"login": "new-name"}]]},
            contract=contract,
            out=out,
        )
    assert len(requests) == 2 and sum(batch.num_rows for batch in out.batches) == 1 and not out.finished
