"""Canonical team identity, effective memberships and access retrieval directions."""

import json

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def teams(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import team_identity_fixture

    return team_identity_fixture


def rows_for(contract, name, **arguments):
    function = next(f for f in contract["functions"] if f["name"] == name)
    output = run(function, {k: [v] for k, v in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,arguments,key,expected",
    [
        ("teams", {"team_numeric_id": 3201}, "team_id", [3201]),
        ("teams", {"organization": "team-fixture"}, "team_id", [3201, 3202, 3203, 3204]),
        ("teams", {"organization": "team-fixture", "team_slug": "platform"}, "team_id", [3201]),
        ("teams", {"authenticated_user": True}, "team_id", [3201, 3202]),
        ("teams", {"parent_team_numeric_id": 3201}, "team_id", [3202, 3203]),
        ("teams", {"organization": "team-fixture", "parent_team_slug": "platform"}, "team_id", [3202, 3203]),
        ("teams", {"parent_team_numeric_id": 3203}, "team_id", []),
        ("team_memberships", {"team_numeric_id": 3201}, "user_id", [903, 3401, 3402]),
        ("team_memberships", {"team_numeric_id": 3201, "team_member_role": "maintainer"}, "user_id", [903]),
        (
            "team_memberships",
            {"organization": "team-fixture", "team_slug": "platform", "team_member_role": "member"},
            "user_id",
            [3401, 3402],
        ),
        (
            "team_memberships",
            {"team_numeric_id": 3201, "team_member_user": "team-carol"},
            "membership_state",
            ["pending"],
        ),
        (
            "team_memberships",
            {"organization": "team-fixture", "team_slug": "platform", "team_member_user": "team-carol"},
            "membership_state",
            ["pending"],
        ),
        ("team_memberships", {"authenticated_user": True}, "team_id", [3201, 3202]),
        ("organization_invitations", {"team_numeric_id": 3201}, "invitation_id", [3501, 3502]),
        (
            "organization_invitations",
            {"organization": "team-fixture", "team_slug": "platform"},
            "invitation_id",
            [3501, 3502],
        ),
        ("organization_invitations", {"team_numeric_id": 3202}, "invitation_id", [3502]),
        ("team_repository_access", {"team_numeric_id": 3201}, "repository_id", [3601, 3602]),
        (
            "team_repository_access",
            {"organization": "team-fixture", "team_slug": "platform"},
            "repository_id",
            [3601, 3602],
        ),
        ("team_repository_access", {"repository": "team-fixture/alpha"}, "team_id", [3201, 3202]),
        (
            "team_repository_access",
            {"team_numeric_id": 3201, "repository": "team-fixture/alpha", "team_repository_permission": True},
            "repository_id",
            [3601],
        ),
        (
            "team_repository_access",
            {
                "organization": "team-fixture",
                "team_slug": "platform",
                "repository": "team-fixture/alpha",
                "team_repository_permission": True,
            },
            "repository_id",
            [3601],
        ),
        ("repositories", {"team_numeric_id": 3201}, "repository_id", [3601, 3602]),
    ],
)
def test_team_routes_select_declared_populations(pilot, teams, monkeypatch, name, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, teams.respond_all)
    assert [r[key] for r in rows_for(contract, name, **arguments)] == expected


def test_canonical_team_identity_and_nonrecursive_children(pilot, teams, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, teams.respond_all)
    numeric = rows_for(contract, "teams", team_numeric_id=3202)
    named = rows_for(contract, "teams", organization="team-fixture", team_slug="ui")
    children = rows_for(contract, "teams", parent_team_numeric_id=3201)
    assert numeric == named == children[:1]
    assert [r["team_id"] for r in children] == [3202, 3203]
    assert numeric[0]["parent"]["id"] == numeric[0]["parent_team_id"] == 3201
    assert numeric[0]["members_count"] == 2
    summary = rows_for(contract, "teams", organization="team-fixture")
    assert all(row["members_count"] is None and row["created_at"] is None for row in summary)


def test_membership_objects_do_not_invent_inheritance_and_summary_is_active(pilot, teams, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, teams.respond_all)
    summaries = rows_for(contract, "team_memberships", team_numeric_id=3201)
    assert [row["membership_inherited"] for row in summaries] == [False, True, False]
    assert all(row["membership_state"] == "active" and row["membership_url"] is None for row in summaries)
    objects = rows_for(contract, "team_memberships", team_numeric_id=3201, team_member_user="team-alice")
    assert objects[0]["membership_inherited"] is None
    assert objects[0]["member_role"] == "member" and objects[0]["user_id"] == 3401
    auth = rows_for(contract, "team_memberships", authenticated_user=True)
    assert [(r["team_id"], r["user_id"], r["member_role"]) for r in auth] == [
        (3201, 903, "maintainer"),
        (3202, 903, "member"),
    ]


def test_shared_invitation_identity_and_inviter_role(pilot, teams, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, teams.respond_all)
    platform = rows_for(contract, "organization_invitations", team_numeric_id=3201)
    ui = rows_for(contract, "organization_invitations", team_numeric_id=3202)
    assert platform[1:] == ui
    assert ui[0]["organization_id"] == 3300 and ui[0]["invitation_id"] == 3502
    assert ui[0]["login"] is None and ui[0]["email"] == "external@example.com"
    assert ui[0]["inviter"]["id"] == 903 and ui[0]["team_count"] == 2


def test_access_roles_match_forward_reverse_and_exact_media(pilot, teams, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, teams.respond_all)
    forward = rows_for(contract, "team_repository_access", team_numeric_id=3201)
    reverse = rows_for(contract, "team_repository_access", repository="team-fixture/alpha")
    exact = rows_for(
        contract,
        "team_repository_access",
        team_numeric_id=3201,
        repository="team-fixture/alpha",
        team_repository_permission=True,
    )
    assert forward[:1] == reverse[:1] == exact
    assert forward[0]["permissions"]["push"] is True
    assert reverse[1]["permissions"]["push"] is False
    assert forward[1]["permissions"] is None and forward[1]["role_name"] is None
    assert requests[-1].headers["accept"] == "application/vnd.github.v3.repository+json"


@pytest.mark.parametrize("numeric", [False, True])
def test_repository_checks_retain_unconfirmed_visibility(pilot, teams, monkeypatch, numeric):
    _, contract, _ = pilot
    install(monkeypatch, teams.respond_all)
    args = {"team_numeric_id": 3201} if numeric else {"organization": "team-fixture", "team_slug": "platform"}
    for name, status in [("alpha", 204), ("gamma", 404)]:
        row = rows_for(
            contract,
            "team_repository_permission_checks",
            **args,
            repository=f"team-fixture/{name}",
            team_repository_check=True,
        )[0]
        assert row["team_id"] == 3201 and row["status_code"] == status
    with pytest.raises(Exception, match="404"):
        rows_for(
            contract,
            "team_repository_access",
            **args,
            repository="team-fixture/gamma",
            team_repository_permission=True,
        )


def test_active_membership_checks_are_not_pending_membership_rows(pilot, teams, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, teams.respond_all)
    for login, status in [("team-alice", 204), ("team-carol", 404)]:
        row = rows_for(
            contract,
            "team_membership_checks",
            team_numeric_id=3201,
            team_member_user=login,
            team_membership_check=True,
        )[0]
        assert row["status_code"] == status
    assert (
        rows_for(contract, "team_memberships", team_numeric_id=3201, team_member_user="team-carol")[0][
            "membership_state"
        ]
        == "pending"
    )


def test_later_page_failure_and_identity_drift_fail_closed(pilot, teams, monkeypatch):
    _, contract, _ = pilot

    def denied(request):
        if request.url.path == "/teams/3201/members" and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Page denied"}, request=request)
        return teams.respond_all(request)

    install(monkeypatch, denied)
    with pytest.raises(Exception, match="403|denied"):
        rows_for(contract, "team_memberships", team_numeric_id=3201)

    def drift(request):
        response = teams.respond_all(request)
        if request.url.path == "/teams/3201":
            value = response.json()
            value["id"] = 3202
            return httpx.Response(200, json=value, request=request)
        return response

    install(monkeypatch, drift)
    with pytest.raises(GeneratedContractError, match="assertion|identity|match"):
        rows_for(contract, "teams", team_numeric_id=3201)


@pytest.mark.parametrize(
    "name,args",
    [
        ("teams", {"team_numeric_id": 3201, "organization": "team-fixture"}),
        (
            "teams",
            {"parent_team_numeric_id": 3201, "parent_team_slug": "platform", "organization": "team-fixture"},
        ),
        ("team_memberships", {"team_numeric_id": 3201, "team_member_role": "admin"}),
        ("team_memberships", {"organization": "team-fixture", "team_member_user": "team-alice"}),
        ("team_memberships", {"team_slug": "platform", "team_member_user": "team-alice"}),
        (
            "team_memberships",
            {"team_numeric_id": 3201, "team_member_user": "team-alice", "team_member_role": "member"},
        ),
        ("organization_invitations", {"organization": "team-fixture"}),
        ("team_repository_access", {"team_numeric_id": 3201, "repository": "team-fixture/alpha"}),
        (
            "team_repository_permission_checks",
            {
                "team_numeric_id": 3201,
                "organization": "team-fixture",
                "repository": "team-fixture/alpha",
                "team_repository_check": True,
            },
        ),
    ],
)
def test_conflicting_or_incomplete_scopes_reject_before_http(pilot, teams, monkeypatch, name, args):
    _, contract, _ = pilot
    requests = install(monkeypatch, teams.respond_all)
    with pytest.raises(GeneratedContractError, match="argument|population|enum|value|route|requires|Specify"):
        rows_for(contract, name, **args)
    assert requests == []


def test_all_pinned_team_operations_have_canonical_business_routes():
    domain = json.loads((ROOT / "generation/domains/team_identity.json").read_text())
    operations = {e["transport"]["operation_id"] for e in domain["entities"]}
    assert {o for o in operations if o.startswith("teams/")} == {
        "teams/list",
        "teams/get-by-name",
        "teams/list-pending-invitations-in-org",
        "teams/list-members-in-org",
        "teams/get-membership-for-user-in-org",
        "teams/list-repos-in-org",
        "teams/check-permissions-for-repo-in-org",
        "teams/list-child-in-org",
        "teams/get-legacy",
        "teams/list-pending-invitations-legacy",
        "teams/list-members-legacy",
        "teams/get-member-legacy",
        "teams/get-membership-for-user-legacy",
        "teams/list-repos-legacy",
        "teams/check-permissions-for-repo-legacy",
        "teams/list-child-legacy",
        "teams/list-for-authenticated-user",
    }
    assert {f["name"] for f in domain["functions"]} == {
        "organization_invitations",
        "team_repository_access",
        "team_membership_checks",
        "team_repository_permission_checks",
    }
