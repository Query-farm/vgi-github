"""Git identities, complete populations and explicit object/actor roles."""

from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def git(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import git_fixture

    return git_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,arguments,key,expected",
    [
        ("commits", {}, "commit_sha", ["c" * 40, "b" * 40, "a" * 40]),
        ("commits", {"commit_ref": "feature"}, "commit_sha", ["b" * 40]),
        ("commits", {"git_commit_sha": "b" * 40}, "commit_sha", ["b" * 40]),
        ("commits", {"commit_comparison": "v1...main"}, "commit_sha", ["b" * 40, "c" * 40]),
        ("commits", {"commit_history_ref": "feature"}, "commit_sha", ["b" * 40, "a" * 40]),
        ("commits", {"commit_author": "alice"}, "commit_sha", ["a" * 40]),
        ("commits", {"commit_committer": "alice"}, "commit_sha", ["b" * 40]),
        ("commits", {"commit_path": "beta.txt"}, "commit_sha", ["c" * 40, "b" * 40]),
        ("commit_files", {}, "filename", ["beta.txt", "beta.txt", "binary.png", "alpha.txt"]),
        ("commit_files", {"commit_ref": "feature"}, "filename", ["beta.txt", "binary.png"]),
        ("branches", {}, "branch_name", ["main", "feature", "main-copy"]),
        ("branches", {"branch_name": "main"}, "branch_name", ["main"]),
        ("branches", {"branch_protected": True}, "branch_name", ["main"]),
        ("branches", {"head_commit_sha": "c" * 40}, "branch_name", ["main", "main-copy"]),
        ("repository_tags", {}, "tag_name", ["v1", "v0"]),
        ("git_references", {"reference_name": "heads/main"}, "ref_name", ["refs/heads/main"]),
        (
            "git_references",
            {"ref_prefix": "heads/"},
            "ref_name",
            ["refs/heads/main", "refs/heads/feature", "refs/heads/main-copy"],
        ),
        ("git_tag_objects", {"git_tag_sha": "2" * 40}, "tag_sha", ["2" * 40]),
        ("git_tag_objects", {"reference_name": "tags/v1"}, "tag_sha", ["2" * 40]),
        ("git_tag_objects", {"reference_name": "tags/v0"}, "tag_sha", []),
        ("git_trees", {"tree_sha": "d" * 40}, "tree_sha", ["d" * 40]),
        ("git_trees", {"commit_ref": "main"}, "tree_sha", ["d" * 40]),
        ("git_tree_entries", {"tree_sha": "d" * 40}, "path", ["alpha.txt", "copy.txt", "src", "module"]),
        (
            "git_tree_entries",
            {"recursive_tree_sha": "d" * 40},
            "path",
            ["alpha.txt", "copy.txt", "src", "module", "src/main.py"],
        ),
        ("git_blobs", {"blob_sha": "3" * 40}, "size_bytes", [10]),
        ("git_blobs", {"tree_sha": "d" * 40}, "size_bytes", [10]),
        ("git_blobs", {"recursive_tree_sha": "d" * 40}, "size_bytes", [10, 20]),
        ("commit_comparisons", {"commit_comparison": "v1...main"}, "total_commits", [2]),
        ("commit_pull_request_memberships", {"commit_ref": "main"}, "pull_request_number", [12]),
        ("commit_pull_request_memberships", {}, "pull_request_number", [12, 11, 11]),
    ],
)
def test_git_route_populations(pilot, git, monkeypatch, name, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, git.respond)
    rows = rows_for(contract, name, repository="git-fixture/alpha", **arguments)
    assert [row[key] for row in rows] == expected
    assert all(row["repository_id"] == 811 for row in rows)


def test_commit_routes_hydrate_same_canonical_values(pilot, git, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, git.respond)
    listed = rows_for(contract, "commits", repository="git-fixture/alpha")
    by_ref = rows_for(contract, "commits", repository="git-fixture/alpha", commit_ref="feature")
    by_git = rows_for(contract, "commits", repository="git-fixture/alpha", git_commit_sha=git.B)
    assert by_ref == by_git == [listed[1]]
    assert by_ref[0]["additions"] == 3 and by_ref[0]["deletions"] == 1
    assert by_ref[0]["parents"][0]["sha"] == git.A


def test_commit_metadata_keeps_one_request_when_files_have_more_pages(pilot, git, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, git.respond)
    rows = rows_for(contract, "commits", repository="git-fixture/alpha", commit_ref="feature")
    assert len(rows) == 1 and rows[0]["commit_sha"] == git.B
    assert (rows[0]["additions"], rows[0]["deletions"], rows[0]["changes"]) == (3, 1, 4)
    metadata_requests = [request for request in requests if "/commits/" in request.url.path]
    assert len(metadata_requests) == 1
    assert metadata_requests[0].url.params.get("page") is None


def test_comparison_summary_keeps_first_page_files_when_commits_continue(pilot, git, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, git.respond)
    rows = rows_for(
        contract, "commit_comparisons", repository="git-fixture/alpha", commit_comparison="v1...main"
    )
    assert len(rows) == 1 and rows[0]["total_commits"] == 2
    assert [row["filename"] for row in rows[0]["files"]] == ["beta.txt", "binary.png"]
    comparison_requests = [request for request in requests if "/compare/" in request.url.path]
    assert len(comparison_requests) == 1
    assert comparison_requests[0].url.params.get("page") is None


def test_git_author_and_committer_roles_and_nullable_accounts(pilot, git, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, git.respond)
    rows = rows_for(contract, "commits", repository="git-fixture/alpha")
    assert rows[0]["author_account_id"] is None and rows[0]["committer_account_id"] is None
    assert rows[0]["author_email"] == "author@example.com"
    assert (rows[1]["author_login"], rows[1]["committer_login"]) == ("bob", "alice")
    assert rows[0]["authored_at"].day == 1 and rows[0]["committed_at"].day == 3


def test_typed_history_date_filters_survive_pages_and_use_iso(pilot, git, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, git.respond)
    rows = rows_for(
        contract,
        "commits",
        repository="git-fixture/alpha",
        commit_since=datetime(2026, 9, 2, tzinfo=UTC),
    )
    assert [row["commit_sha"] for row in rows] == [git.C, git.B]
    history = [request for request in requests if request.url.path.endswith("/commits")]
    assert len(history) == 2 and all("T" in request.url.params["since"] for request in history)


def test_file_pages_are_complete_and_missing_binary_patch_is_unknown(pilot, git, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, git.respond)
    rows = rows_for(contract, "commit_files", repository="git-fixture/alpha", commit_ref="feature")
    assert len(rows) == 2
    assert rows[0]["previous_filename"] == "alpha.txt"
    assert rows[1]["patch"] is None
    assert any(request.url.params.get("page") == "2" for request in requests)


def test_comparison_files_are_net_changes_and_commits_are_fully_paged(pilot, git, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, git.respond)
    rows = rows_for(
        contract, "commit_comparisons", repository="git-fixture/alpha", commit_comparison="v1...main"
    )
    assert len(rows) == 1 and len(rows[0]["files"]) == 2 and rows[0]["total_commits"] == 2
    commits = rows_for(contract, "commits", repository="git-fixture/alpha", commit_comparison="v1...main")
    assert [row["commit_sha"] for row in commits] == [git.B, git.C]


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("git_trees", {"tree_sha": "d" * 40}),
        ("git_tree_entries", {"recursive_tree_sha": "d" * 40}),
        ("git_blobs", {"recursive_tree_sha": "d" * 40}),
    ],
)
def test_truncated_tree_fails_before_claiming_complete_population(pilot, git, monkeypatch, name, arguments):
    _, contract, _ = pilot

    def respond(request):
        response = git.respond(request)
        if "/git/trees/" in request.url.path:
            payload = response.json()
            payload["truncated"] = True
            return httpx.Response(200, json=payload, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="assertion|truncated"):
        rows_for(contract, name, repository="git-fixture/alpha", **arguments)


def test_comparison_file_ceiling_rejects_possible_truncation(pilot, git, monkeypatch):
    _, contract, _ = pilot
    monkeypatch.setattr(
        git, "COMPARISON_FILES", [git.change(f"file-{i}", git.BLOB1, 1, 0) for i in range(300)]
    )
    install(monkeypatch, git.respond)
    with pytest.raises(GeneratedContractError, match="assertion|300|length"):
        rows_for(
            contract, "commit_comparisons", repository="git-fixture/alpha", commit_comparison="v1...main"
        )


def test_commit_file_ceiling_rejects_possible_truncation(pilot, git, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        response = git.respond(request)
        if request.url.path.endswith("/commits/" + git.B):
            payload = response.json()
            payload["files"] = [git.change(f"file-{i}", git.BLOB1, 1, 0) for i in range(3000)]
            headers = dict(response.headers)
            headers.pop("link", None)
            return httpx.Response(200, json=payload, headers=headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="3000|ceiling|limit|cap"):
        rows_for(contract, "commit_files", repository="git-fixture/alpha", commit_ref="feature")


def test_missing_comparison_next_page_fails_total_check(pilot, git, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        response = git.respond(request)
        if "/compare/" in request.url.path:
            headers = dict(response.headers)
            headers.pop("link", None)
            return httpx.Response(200, json=response.json(), headers=headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="total_count"):
        rows_for(contract, "commits", repository="git-fixture/alpha", commit_comparison="v1...main")


def test_refs_empty_prefix_and_default_select_every_namespace(pilot, git, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, git.respond)
    default = rows_for(contract, "git_references", repository="git-fixture/alpha")
    explicit = rows_for(contract, "git_references", repository="git-fixture/alpha", ref_prefix="")
    assert default == explicit and len(default) == 6
    assert {row["object_type"] for row in default} == {"commit", "tag", "blob"}


def test_blob_repeated_paths_deduplicate_only_object_grain(pilot, git, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, git.respond)
    entries = rows_for(
        contract, "git_tree_entries", repository="git-fixture/alpha", recursive_tree_sha=git.TREE
    )
    blobs = rows_for(contract, "git_blobs", repository="git-fixture/alpha", recursive_tree_sha=git.TREE)
    assert sum(row["size_bytes"] or 0 for row in entries) == 40
    assert sum(row["size_bytes"] for row in blobs) == 30
    assert all(row["encoding"] == "base64" for row in blobs)


def test_wrong_git_object_identity_is_rejected(pilot, git, monkeypatch):
    _, contract, _ = pilot
    changed = deepcopy(git.BLOBS)
    changed[git.BLOB1]["sha"] = git.BLOB2
    monkeypatch.setattr(git, "BLOBS", changed)
    install(monkeypatch, git.respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(contract, "git_blobs", repository="git-fixture/alpha", blob_sha=git.BLOB1)


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("commits", {"commit_ref": "main", "commit_author": "alice"}),
        ("branches", {"branch_name": "main", "head_commit_sha": "c" * 40}),
        ("git_tree_entries", {"tree_sha": "d" * 40, "recursive_tree_sha": "d" * 40}),
        ("git_blobs", {"blob_sha": "3" * 40, "tree_sha": "d" * 40}),
    ],
)
def test_incompatible_git_selectors_fail_before_http(pilot, monkeypatch, name, arguments):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid selection must fail before HTTP"))
    with pytest.raises(GeneratedContractError):
        rows_for(contract, name, repository="git-fixture/alpha", **arguments)
