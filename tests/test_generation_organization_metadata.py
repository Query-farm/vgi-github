"""Organization metadata uses canonical properties, invitations, teams and issue types."""

import json
from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError

ORG = "organization-metadata-fixture"


@pytest.fixture
def metadata(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import organization_metadata_fixture

    return organization_metadata_fixture


def rows_for(contract, name, **arguments):
    f = next(f for f in contract["functions"] if f["name"] == name)
    output = run(f, {k: [v] for k, v in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,args,key,expected",
    [
        (
            "repository_property_definitions",
            {"organization": ORG},
            "property_name",
            ["risk", "labels", "flag", "unset"],
        ),
        (
            "repository_property_definitions",
            {"organization": ORG, "custom_property_name": "risk"},
            "property_name",
            ["risk"],
        ),
        (
            "repository_property_values",
            {"organization": ORG},
            "property_name",
            ["risk", "labels", "unset", "risk", "flag"],
        ),
        (
            "repository_property_values",
            {"organization": ORG, "property_repository_query": "name:alpha"},
            "property_name",
            ["risk", "labels", "unset"],
        ),
        ("issue_types", {"organization": ORG}, "issue_type_id", [3801, 3802]),
        ("issue_types", {"repository": f"{ORG}/alpha"}, "issue_type_id", [3801]),
        ("issue_types", {"repository": f"{ORG}/empty"}, "issue_type_id", []),
        ("issue_fields", {"organization": ORG}, "issue_field_id", [3901, 3902]),
        ("organization_outside_collaborators", {"organization": ORG}, "user_id", [4801, 4802]),
        (
            "organization_outside_collaborators",
            {"organization": ORG, "outside_collaborator_filter": "2fa_disabled"},
            "user_id",
            [4801],
        ),
        (
            "organization_invitations",
            {"organization": ORG, "organization_invitation_population": "pending"},
            "invitation_id",
            [4101, 4102],
        ),
        (
            "organization_invitations",
            {"organization": ORG, "organization_invitation_population": "failed"},
            "invitation_id",
            [4103],
        ),
        (
            "organization_invitations",
            {
                "organization": ORG,
                "organization_invitation_population": "pending",
                "organization_invitation_role": "admin",
            },
            "invitation_id",
            [],
        ),
        (
            "organization_invitation_teams",
            {"organization": ORG, "organization_invitation_id": 4102},
            "team_id",
            [4201, 4202],
        ),
        ("organization_invitation_teams", {"team_numeric_id": 4201}, "invitation_id", [4101, 4102]),
        ("organization_invitation_teams", {"organization": ORG, "team_slug": "ui"}, "invitation_id", [4102]),
        ("teams", {"organization": ORG, "organization_invitation_id": 4102}, "team_id", [4201, 4202]),
    ],
)
def test_org_metadata_routes(pilot, metadata, monkeypatch, name, args, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, metadata.respond)
    assert [r[key] for r in rows_for(contract, name, **args)] == expected


def test_definition_defaults_and_values_preserve_distinct_typed_shapes(pilot, metadata, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, metadata.respond)
    definitions = rows_for(contract, "repository_property_definitions", organization=ORG)
    assert definitions[0]["default_value"]["variant_1"] == "medium"
    assert definitions[1]["default_value"]["variant_2"] == ["reviewed"]
    assert definitions[3]["default_value"] is None
    assert definitions[0]["allowed_values"] == ["low", "medium", "high"]
    assert definitions[2]["source_type"] == "enterprise"
    values = rows_for(contract, "repository_property_values", organization=ORG)
    assert [(r["repository_id"], r["property_name"]) for r in values] == [
        (3711, "risk"),
        (3711, "labels"),
        (3711, "unset"),
        (3712, "risk"),
        (3712, "flag"),
    ]
    assert values[1]["value"]["variant_2"] == ["critical", "reviewed"]
    assert values[2]["value"] is None
    assert values[4]["value"]["variant_1"] == "false"
    assert any(r.url.path == f"/repos/{ORG}/alpha/properties/values" for r in requests)
    assert rows_for(contract, "repository_property_values", repository=f"{ORG}/alpha") == values[:3]


def test_issue_types_share_organization_identity_and_fields_keep_ordered_options(
    pilot, metadata, monkeypatch
):
    _, contract, _ = pilot
    install(monkeypatch, metadata.respond)
    org = rows_for(contract, "issue_types", organization=ORG)
    repo = rows_for(contract, "issue_types", repository=f"{ORG}/alpha")
    assert org[:1] == repo and repo[0]["organization_id"] == 3700
    assert org[1]["is_enabled"] is False and org[1]["color"] is None
    fields = rows_for(contract, "issue_fields", organization=ORG)
    assert [option["id"] for option in fields[0]["options"]] == [3911, 3912]
    assert fields[0]["options"][1]["priority"] == 2 and fields[1]["options"] is None


def test_outside_collaborators_preserve_bot_accounts_without_claiming_membership(
    pilot, metadata, monkeypatch
):
    _, contract, _ = pilot
    install(monkeypatch, metadata.respond)
    rows = rows_for(contract, "organization_outside_collaborators", organization=ORG)
    assert [(r["user_id"], r["account_type"]) for r in rows] == [(4801, "User"), (4802, "Bot")]
    assert rows[1]["account"]["login"] == "metadata-bot"


def test_invitation_state_and_association_reverse_identity(pilot, metadata, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, metadata.respond)
    pending = rows_for(
        contract, "organization_invitations", organization=ORG, organization_invitation_population="pending"
    )
    by_team = rows_for(contract, "organization_invitations", team_numeric_id=4201)
    assert pending == by_team
    failed = rows_for(
        contract, "organization_invitations", organization=ORG, organization_invitation_population="failed"
    )
    assert failed[0]["invitation_state"] == "failed" and failed[0]["failed_reason"] == "Unconfirmed email"
    assert pending[1]["login"] is None and pending[1]["email"] == "external@example.com"
    forward = rows_for(
        contract, "organization_invitation_teams", organization=ORG, organization_invitation_id=4102
    )
    reverse = rows_for(contract, "organization_invitation_teams", team_numeric_id=4202)
    assert forward[1:] == reverse
    assert reverse[0]["organization_id"] == 3700 and reverse[0]["team_id"] == 4202


def test_discovery_identity_mismatch_and_missing_definition_fail(pilot, metadata, monkeypatch):
    _, contract, _ = pilot

    def drift(request):
        response = metadata.respond(request)
        if request.url.path == f"/orgs/{ORG}/properties/values":
            value = response.json()
            value[0]["repository_id"] = 99999
            return httpx.Response(200, json=value, headers=response.headers, request=request)
        return response

    install(monkeypatch, drift)
    with pytest.raises(GeneratedContractError, match="repository_id|assertion|identity"):
        rows_for(contract, "repository_property_values", organization=ORG)
    install(monkeypatch, metadata.respond)
    with pytest.raises(Exception, match="404"):
        rows_for(
            contract, "repository_property_definitions", organization=ORG, custom_property_name="missing"
        )


def test_later_page_denial_does_not_become_complete_collaborator_population(pilot, metadata, monkeypatch):
    _, contract, _ = pilot

    def denied(request):
        if request.url.path.endswith("/outside_collaborators") and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Page denied"}, request=request)
        return metadata.respond(request)

    install(monkeypatch, denied)
    with pytest.raises(Exception, match="403|denied"):
        rows_for(contract, "organization_outside_collaborators", organization=ORG)


def test_nullable_issue_schema_does_not_allow_identityless_rows(pilot, metadata, monkeypatch):
    _, contract, _ = pilot
    bad = deepcopy(metadata.TYPES)
    bad[0]["id"] = None
    monkeypatch.setattr(metadata, "TYPES", bad)
    install(monkeypatch, metadata.respond)
    with pytest.raises(GeneratedContractError, match="issue_type_id: NULL is not allowed"):
        rows_for(contract, "issue_types", organization=ORG)


@pytest.mark.parametrize(
    "name,args",
    [
        ("repository_property_definitions", {"organization": ORG, "custom_property_name": ""}),
        (
            "repository_property_values",
            {"repository": f"{ORG}/alpha", "property_repository_query": "name:alpha"},
        ),
        ("issue_types", {"organization": ORG, "repository": f"{ORG}/alpha"}),
        ("organization_invitations", {"organization": ORG, "organization_invitation_population": "accepted"}),
        (
            "organization_invitations",
            {
                "organization": ORG,
                "organization_invitation_population": "failed",
                "organization_invitation_role": "admin",
            },
        ),
        (
            "organization_invitation_teams",
            {"organization": ORG, "organization_invitation_id": 4102, "team_numeric_id": 4201},
        ),
    ],
)
def test_unrelated_or_invalid_arguments_reject_before_http(pilot, metadata, monkeypatch, name, args):
    _, contract, _ = pilot
    requests = install(monkeypatch, metadata.respond)
    with pytest.raises(
        GeneratedContractError, match="argument|minimum|length|enum|value|route|parameter|requires"
    ):
        rows_for(contract, name, **args)
    assert requests == []


def test_metadata_operations_are_explicit_and_property_values_stay_canonical():
    domain = json.loads((ROOT / "generation/domains/organization_metadata.json").read_text())
    assert {s["transport"]["operation_id"] for s in domain["entities"]} == {
        "orgs/custom-properties-for-repos-get-organization-definition",
        "orgs/custom-properties-for-repos-get-organization-definitions",
        "orgs/custom-properties-for-repos-get-organization-values",
        "repos/get",
        "orgs/list-issue-types",
        "repos/list-issue-types",
        "orgs/list-issue-fields",
        "orgs/list-outside-collaborators",
        "orgs/list-pending-invitations",
        "orgs/list-failed-invitations",
        "orgs/list-invitation-teams",
    }
    assert "repository_property_values" not in {f["name"] for f in domain["functions"]}
