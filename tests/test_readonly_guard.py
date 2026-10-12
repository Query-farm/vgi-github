"""Structural guard: this worker must never write to GitHub.

GitHub's write endpoints share a host, an auth header and often a path with
the reads. A token with write scope would happily authorize a POST, so the
read-only property is enforced in the source, not left to token scopes.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "vgi_github"

#: REST write verbs and untyped dispatch are never allowed. GraphQL POST has a
#: separate AST and runtime guard below because queries use POST on GitHub.
WRITE_VERBS = {"put", "patch", "delete", "request", "stream", "send"}


def test_no_http_write_calls_anywhere() -> None:
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            is_method_call = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            if is_method_call and node.func.attr in WRITE_VERBS:
                offenders.append(f"{path.name}: .{node.func.attr}()")
    assert offenders == [], offenders


def test_single_http_chokepoint() -> None:
    """Only github_api.py may touch httpx, so there is exactly one file to audit."""
    users = sorted(p.name for p in PACKAGE.rglob("*.py") if "httpx" in p.read_text())
    assert users == ["github_api.py"], users


def test_post_is_confined_to_validated_graphql_queries() -> None:
    posts = []
    all_posts = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text())
        all_posts.extend(
            (path.name, node.lineno)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "post"
        )
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "post"
                ):
                    posts.append((path.name, function.name))
                    guards = [
                        n
                        for n in ast.walk(function)
                        if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name)
                        and n.func.id == "validate_query"
                    ]
                    assert len(guards) == 1 and guards[0].lineno < node.lineno
                    assert any(
                        k.arg == "follow_redirects"
                        and isinstance(k.value, ast.Constant)
                        and k.value.value is False
                        for k in node.keywords
                    )
    assert posts == [("github_api.py", "graphql_query")]
    assert len(all_posts) == 1, "POST calls at module scope or in nested classes must also be audited"


def test_exactly_one_get_call() -> None:
    """The chokepoint itself issues a single `.get(` — everything else goes through it."""
    source = (PACKAGE / "github_api.py").read_text()
    gets = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "http"
    ]
    assert len(gets) == 1
