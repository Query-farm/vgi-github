"""Identity-preserving profile routes and independent directed social populations."""

import json

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def identity(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import user_identity_fixture

    return user_identity_fixture


def rows_for(contract, name, **arguments):
    entity = next(f for f in contract["functions"] if f["name"] == name)
    output = run(entity, {k: [v] for k, v in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,arguments,key,expected",
    [
        ("users", {"user_account_id": 2901}, "user_login", ["identity-alice"]),
        ("users", {"user_account_id": 2904}, "user_login", []),
        ("users", {"user_account_id": 2905}, "user_login", []),
        ("users", {"authenticated_user": True}, "user_id", [903]),
        ("users", {"user_directory": True}, "user_id", [903, 2901, 2902, 2903]),
        ("users", {"user_directory": True, "user_since_id": 2901}, "user_id", [2902, 2903]),
        ("users", {"user_directory": True, "user_since_id": 9999}, "user_id", []),
        ("user_follow_relationships", {"follower_user": "identity-alice"}, "followed_id", [903, 2902, 2903]),
        ("user_follow_relationships", {"followed_user": "identity-alice"}, "follower_id", [903, 2902]),
        (
            "user_follow_relationships",
            {"authenticated_user": True, "follow_direction": "followers"},
            "follower_id",
            [2901, 2903],
        ),
        (
            "user_follow_relationships",
            {"authenticated_user": True, "follow_direction": "following"},
            "followed_id",
            [2902, 2901],
        ),
        (
            "user_follow_checks",
            {"follower_user": "identity-alice", "followed_user": "identity-bob"},
            "status_code",
            [204],
        ),
        (
            "user_follow_checks",
            {"follower_user": "identity-bob", "followed_user": "identity-carol"},
            "status_code",
            [404],
        ),
        (
            "user_follow_checks",
            {"authenticated_user": True, "followed_user": "identity-bob"},
            "status_code",
            [204],
        ),
        (
            "user_follow_checks",
            {"authenticated_user": True, "followed_user": "identity-carol"},
            "status_code",
            [404],
        ),
        (
            "user_emails",
            {"authenticated_user": True, "user_email_population": "all"},
            "email",
            ["public@example.com", "private@example.com", "pending@example.com"],
        ),
        (
            "user_emails",
            {"authenticated_user": True, "user_email_population": "public"},
            "email",
            ["public@example.com"],
        ),
        (
            "user_social_accounts",
            {"user": "identity-alice"},
            "provider",
            ["mastodon", "mastodon", "linkedin"],
        ),
        ("user_social_accounts", {"user": "identity-bob"}, "provider", []),
        ("user_social_accounts", {"authenticated_user": True}, "user_id", [903]),
        ("user_context_observations", {"user": "identity-alice"}, "subject_type", ["none"]),
        (
            "user_context_observations",
            {
                "user": "identity-alice",
                "user_context_subject_type": "repository",
                "user_context_subject_id": "123",
            },
            "subject_id",
            ["123"],
        ),
    ],
)
def test_identity_and_social_routes(pilot, identity, monkeypatch, name, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, identity.respond)
    assert [row[key] for row in rows_for(contract, name, **arguments)] == expected


def test_directory_hydrates_only_personal_users_and_preserves_stable_id(pilot, identity, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, identity.respond)
    directory = rows_for(contract, "users", user_directory=True)
    named = rows_for(contract, "users", user="identity-alice")
    numeric = rows_for(contract, "users", user_account_id=2901)
    assert directory[1:2] == named == numeric
    assert len([r for r in requests if r.url.path == "/users"]) == 6
    assert not any(r.url.path in {"/users/identity-org", "/users/identity-bot"} for r in requests)
    cursor_requests = [r for r in requests if r.url.path == "/users"]
    assert [r.url.params.get("since") for r in cursor_requests] == [
        None,
        "903",
        "2901",
        "2902",
        "2903",
        "2904",
    ]


def test_opposite_follow_directions_share_one_ordered_pair_identity(pilot, identity, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, identity.respond)
    outgoing = rows_for(contract, "user_follow_relationships", follower_user="identity-alice")
    incoming = rows_for(contract, "user_follow_relationships", followed_user="identity-bob")
    edge_out = next(r for r in outgoing if r["followed_id"] == 2902)
    edge_in = next(r for r in incoming if r["follower_id"] == 2901)
    assert (
        edge_out
        == edge_in
        == {
            "follower_id": 2901,
            "follower_login": "identity-alice",
            "followed_id": 2902,
            "followed_login": "identity-bob",
        }
    )
    auth = rows_for(
        contract, "user_follow_relationships", authenticated_user=True, follow_direction="following"
    )
    named = rows_for(contract, "user_follow_relationships", follower_user="package-fixture-current")
    assert auth == named


def test_contact_flags_and_provider_urls_are_independent(pilot, identity, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, identity.respond)
    all_rows = rows_for(contract, "user_emails", authenticated_user=True, user_email_population="all")
    public_rows = rows_for(contract, "user_emails", authenticated_user=True, user_email_population="public")
    assert public_rows == all_rows[:1]
    assert sum(row["is_primary"] for row in all_rows) == 1
    assert sum(row["is_verified"] for row in all_rows) == 2
    assert all_rows[2]["visibility"] is None
    social = rows_for(contract, "user_social_accounts", user="identity-alice")
    assert len(social) == 3 and len({r["provider"] for r in social}) == 2
    assert len({r["url"] for r in social}) == 3


def test_context_lists_are_typed_and_empty_is_still_an_observation(pilot, identity, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, identity.respond)
    plain = rows_for(contract, "user_context_observations", user="identity-alice")[0]
    contextual = rows_for(
        contract,
        "user_context_observations",
        user="identity-alice",
        user_context_subject_type="repository",
        user_context_subject_id="123",
    )[0]
    empty = rows_for(contract, "user_context_observations", user="identity-bob")
    assert plain["subject_type"] == "none" and plain["subject_id"] == ""
    assert contextual["contexts"] == [
        {"message": "Contributor to repository 123", "octicon": "repo"},
        {"message": "One open issue", "octicon": "issue-opened"},
    ]
    assert len(empty) == 1 and empty[0]["contexts"] == []


@pytest.mark.parametrize("numeric", [True, False])
def test_numeric_identity_mismatch_fails_in_direct_and_discovered_profiles(
    pilot, identity, monkeypatch, numeric
):
    _, contract, _ = pilot

    def respond(request):
        result = identity.respond(request)
        if request.url.path == ("/user/2901" if numeric else "/users/identity-alice"):
            body = result.json()
            body["id"] = 9999
            return httpx.Response(200, json=body, headers=result.headers, request=request)
        return result

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(contract, "users", **({"user_account_id": 2901} if numeric else {"user_directory": True}))


def test_exact_missing_account_remains_404(pilot, identity, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, identity.respond)
    with pytest.raises(Exception, match="404"):
        rows_for(contract, "users", user_account_id=9999)


def test_follow_check_permission_failure_is_not_a_negative_relationship(pilot, identity, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/following/identity-bob"):
            return httpx.Response(403, json={"message": "Follow check denied"}, request=request)
        return identity.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="403|denied"):
        rows_for(contract, "user_follow_checks", follower_user="identity-alice", followed_user="identity-bob")


@pytest.mark.parametrize(
    "name,args,path",
    [
        ("user_follow_relationships", {"follower_user": "identity-alice"}, "/following"),
        ("user_emails", {"authenticated_user": True, "user_email_population": "all"}, "/emails"),
        ("user_social_accounts", {"user": "identity-alice"}, "/social_accounts"),
    ],
)
def test_later_page_failure_is_not_silent_partial_success(pilot, identity, monkeypatch, name, args, path):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith(path) and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Identity page denied"}, request=request)
        return identity.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="403|denied"):
        rows_for(contract, name, **args)


@pytest.mark.parametrize(
    "name,args",
    [
        ("users", {"user_account_id": 2901, "user": "identity-alice"}),
        ("users", {"user_directory": True, "user_since_id": -1}),
        ("user_follow_relationships", {"follower_user": "identity-alice", "followed_user": "identity-bob"}),
        ("user_follow_relationships", {"authenticated_user": True}),
        ("user_follow_checks", {"follower_user": "identity-alice"}),
        ("user_emails", {"user": "identity-alice", "user_email_population": "all"}),
        ("user_social_accounts", {"user": "identity-alice", "authenticated_user": True}),
        ("user_context_observations", {"user": "identity-alice", "user_context_subject_id": "123"}),
        ("user_context_observations", {"user": "identity-alice", "user_context_subject_type": "repository"}),
    ],
)
def test_invalid_selections_fail_before_http(pilot, identity, monkeypatch, name, args):
    _, contract, _ = pilot
    requests = install(monkeypatch, identity.respond)
    with pytest.raises(
        GeneratedContractError, match="argument|route|population|required|requires|at least|NULL|non-null"
    ):
        rows_for(contract, name, **args)
    assert requests == []


def test_identity_family_has_all_thirteen_new_operations_and_reverse_follow_roles():
    domain = json.loads((ROOT / "generation/domains/user_identity.json").read_text())
    operations = {s["transport"]["operation_id"] for s in domain["entities"]}
    assert operations == {
        "users/get-by-id",
        "users/list",
        "users/get-by-username",
        "users/get-authenticated",
        "users/list-followers-for-user",
        "users/list-following-for-user",
        "users/list-followers-for-authenticated-user",
        "users/list-followed-by-authenticated-user",
        "users/check-following-for-user",
        "users/check-person-is-followed-by-authenticated",
        "users/list-emails-for-authenticated-user",
        "users/list-public-emails-for-authenticated-user",
        "users/list-social-accounts-for-authenticated-user",
        "users/list-social-accounts-for-user",
        "users/get-context-for-user",
    }
    relationships = [r for r in domain["relationships"] if r["from"] == "user_follow_relationships"]
    assert len(relationships) == 2
    assert {tuple(r["from_columns"]) for r in relationships} == {("follower_id",), ("followed_id",)}
    assert all(r["analytical"] is False for r in relationships)
    assert all(any(v["direction"] == "reverse" for v in r["retrievals"]) for r in relationships)
