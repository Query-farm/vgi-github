"""Codespace populations, machine contexts and sparse observations stay explicit."""

from copy import deepcopy

import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError

OWNER = "codespaces-fixture"
ALPHA = OWNER + "/alpha"


@pytest.fixture
def spaces(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import codespaces_fixture

    return codespaces_fixture


def rows_for(contract, name, **arguments):
    entity = next(row for row in contract["functions"] if row["name"] == name)
    result = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in result.batches for row in batch.to_pylist()]


def test_codespace_routes_keep_identity_and_distinct_access_populations(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, spaces.respond)
    org = rows_for(contract, "codespaces", organization=OWNER)
    assert [r["codespace_id"] for r in org] == [42001, 42002, 42003]
    assert [r["state"] for r in org] == ["Available", "Shutdown", "Unknown"]
    assert rows_for(contract, "codespaces", organization=OWNER, user="codespaces-bob") == org[1:2]
    assert rows_for(contract, "codespaces", repository=ALPHA) == org[:1]
    assert rows_for(contract, "codespaces", authenticated_user=True) == [org[0], org[2]]
    assert rows_for(contract, "codespaces", authenticated_user=True, codespace_repository_id=41002) == org[2:]
    assert rows_for(contract, "codespaces", codespace_name="fixture-space-a") == org[:1]
    assert org[1]["machine"] is None and org[1]["machine_cpus"] is None
    assert any(
        r.url.path == f"/orgs/{OWNER}/codespaces" and r.url.params.get("page") == "3" for r in requests
    )
    assert org[0]["owner"]["id"] == 48101 and org[1]["owner"]["id"] == 48102
    assert org[1]["billable_owner"]["id"] == 48101


def test_machine_eligibility_is_qualified_by_context(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, spaces.respond)
    rows = rows_for(
        contract,
        "codespace_machine_options",
        organization=OWNER,
        codespace_ref="main",
        codespace_location="WestUs2",
        codespace_client_ip="192.0.2.1",
    )
    assert [(r["availability_key"], r["machine_name"], r["cpus"]) for r in rows] == [
        (ALPHA, "small", 2),
        (ALPHA, "medium", 4),
        (OWNER + "/beta", "medium", 4),
    ]
    assert all(r["availability_scope"] == "repository" and r["codespace_id"] is None for r in rows)
    exact = rows_for(contract, "codespace_machine_options", codespace_name="fixture-space-a")
    assert [
        (r["availability_scope"], r["availability_key"], r["machine_name"], r["cpus"], r["codespace_id"])
        for r in exact
    ] == [("codespace", "fixture-space-a", "large", 8, 42001)]
    assert exact[0]["codespace_ref"] is None
    assert rows_for(contract, "codespace_machine_options", codespace_name="fixture-space-b") == []
    assert any(
        r.url.params.get("ref") == "main"
        and r.url.params.get("location") == "WestUs2"
        and r.url.params.get("client_ip") == "192.0.2.1"
        for r in requests
    )


def test_undeclared_codespace_state_fails_pinned_schema(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    rows = deepcopy(spaces.CODESPACES)
    rows[0]["state"] = "FutureState"
    monkeypatch.setattr(spaces, "CODESPACES", rows)
    install(monkeypatch, spaces.respond)
    with pytest.raises(GeneratedContractError, match="state.*declared enum"):
        rows_for(contract, "codespaces", codespace_name="fixture-space-a")


def test_devcontainer_pages_and_sparse_creation_defaults(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, spaces.respond)
    rows = rows_for(contract, "repository_devcontainers", organization=OWNER)
    assert [(r["repository_id"], r["devcontainer_path"]) for r in rows] == [
        (41001, ".devcontainer/devcontainer.json"),
        (41001, ".devcontainer/python/devcontainer.json"),
        (41002, ".devcontainer/devcontainer.json"),
    ]
    assert rows[1]["name"] is None and rows[2]["display_name"] is None
    assert any(r.url.path.endswith("/devcontainers") and r.url.params.get("page") == "2" for r in requests)
    defaults = rows_for(contract, "codespace_creation_defaults", organization=OWNER, codespace_ref="main")
    assert [
        (r["repository_id"], r["default_location"], r["default_devcontainer_path"]) for r in defaults
    ] == [(41001, "WestUs2", ".devcontainer/devcontainer.json"), (41002, None, None), (41003, "EastUs", None)]
    assert defaults[1]["billable_owner"] is None


def test_permission_observation_keeps_ref_path_and_caller_acceptance(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, spaces.respond)
    rows = rows_for(
        contract,
        "codespace_devcontainer_permissions",
        organization=OWNER,
        codespace_ref="topic/a",
        devcontainer_path=".devcontainer/devcontainer.json",
    )
    assert [(r["repository_id"], r["accepted"]) for r in rows] == [
        (41001, True),
        (41002, False),
        (41003, False),
    ]
    assert all(r["codespace_ref"] == "topic/a" for r in rows)


def test_exports_preserve_latest_selector_and_empty_observation(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, spaces.respond)
    latest = rows_for(
        contract,
        "codespace_export_observations",
        codespace_name="fixture-space-a",
        codespace_export_id="latest",
    )[0]
    assert latest["codespace_id"] == 42001 and latest["reported_export_id"] == "export-a"
    assert latest["codespace_export_id"] == "latest" and latest["state"] == "succeeded"
    exact = rows_for(
        contract,
        "codespace_export_observations",
        codespace_name="fixture-space-a",
        codespace_export_id="export-a",
    )[0]
    assert {k: v for k, v in latest.items() if k != "codespace_export_id"} == {
        k: v for k, v in exact.items() if k != "codespace_export_id"
    }
    empty = rows_for(
        contract,
        "codespace_export_observations",
        codespace_name="fixture-space-b",
        codespace_export_id="latest",
    )[0]
    assert empty["reported_export_id"] is None and empty["state"] is None and empty["completed_at"] is None


def test_lookup_name_and_member_identity_assertions(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    rows = deepcopy(spaces.CODESPACES)
    rows[0]["name"] = "different-name"

    def wrong_lookup(request):
        result = spaces.respond(request)
        if request.url.path == "/user/codespaces/fixture-space-a":
            import httpx

            return httpx.Response(200, json=rows[0], request=request)
        return result

    install(monkeypatch, wrong_lookup)
    with pytest.raises(GeneratedContractError, match="codespace_name"):
        rows_for(contract, "codespaces", codespace_name="fixture-space-a")


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("codespaces", {"user": "codespaces-bob"}),
        ("codespaces", {"codespace_name": "fixture-space-a", "repository": ALPHA}),
        ("codespaces", {"authenticated_user": False}),
        ("codespaces", {"organization": OWNER, "authenticated_user": True}),
        ("codespace_machine_options", {"codespace_name": "fixture-space-a", "codespace_ref": "main"}),
        (
            "codespace_devcontainer_permissions",
            {"repository": ALPHA, "devcontainer_path": ".devcontainer/devcontainer.json"},
        ),
        ("codespace_devcontainer_permissions", {"repository": ALPHA, "codespace_ref": "main"}),
        ("codespace_export_observations", {"codespace_name": "fixture-space-a"}),
        ("codespace_export_observations", {"codespace_export_id": "latest"}),
    ],
)
def test_invalid_or_incompatible_selectors_make_no_http(pilot, spaces, monkeypatch, name, arguments):
    _, contract, _ = pilot
    requests = install(monkeypatch, spaces.respond)
    with pytest.raises(GeneratedContractError):
        rows_for(contract, name, **arguments)
    assert requests == []
