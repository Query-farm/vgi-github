"""The two entry-point scripts must be runnable on their own.

`uv run github_worker.py` resolves dependencies from the script's PEP-723
header, not from `pyproject.toml`, so the two lists drift silently: the package
imports fine under `pytest` while the worker a client actually launches dies at
import. Adding `cryptography` for request signing broke exactly this way, and
nothing but an end-to-end ATTACH noticed.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("github_worker.py", "serve.py")

#: PEP 723 inline script metadata: a `# /// script` ... `# ///` comment block.
_BLOCK = re.compile(r"^# /// script$(.+?)^# ///$", re.MULTILINE | re.DOTALL)


def _script_dependencies(path: Path) -> set[str]:
    """The distribution names a script's inline metadata declares."""
    match = _BLOCK.search(path.read_text())
    assert match is not None, f"{path.name} has no PEP-723 script header"
    body = "".join(
        line.removeprefix("# ").removeprefix("#") for line in match.group(1).splitlines(keepends=True)
    )
    return {_name(spec) for spec in tomllib.loads(body)["dependencies"]}


def _name(requirement: str) -> str:
    """The bare distribution name from a requirement string."""
    return re.split(r"[\[><=!~;\s]", requirement, maxsplit=1)[0].strip().lower()


@pytest.fixture(scope="module")
def project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


@pytest.fixture(scope="module")
def project_dependencies() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return {_name(spec) for spec in data["project"]["dependencies"]}


class TestScriptHeaders:
    @pytest.mark.parametrize("script", SCRIPTS)
    def test_header_covers_every_runtime_dependency(
        self, script: str, project_dependencies: set[str]
    ) -> None:
        declared = _script_dependencies(ROOT / script)
        missing = project_dependencies - declared
        assert missing == set(), (
            f"{script} would fail at import: its PEP-723 header is missing {sorted(missing)}"
        )

    @pytest.mark.parametrize("script", SCRIPTS)
    def test_header_declares_nothing_unknown(self, script: str, project_dependencies: set[str]) -> None:
        """The scripts also pull vgi-rpc directly, but nothing beyond that."""
        extra = _script_dependencies(ROOT / script) - project_dependencies - {"vgi-rpc"}
        assert extra == set(), f"{script} declares dependencies the project does not: {sorted(extra)}"


def _vgi_python_requirements() -> dict[str, str]:
    """Every place a `vgi-python` requirement is declared, keyed by where."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    sources = {"pyproject dependencies": data["project"]["dependencies"]}
    for extra, specs in data["project"].get("optional-dependencies", {}).items():
        sources[f"pyproject [{extra}]"] = specs
    for script in SCRIPTS:
        match = _BLOCK.search((ROOT / script).read_text())
        assert match is not None
        body = "".join(line.removeprefix("# ").removeprefix("#") for line in match.group(1).splitlines(True))
        sources[script] = tomllib.loads(body)["dependencies"]
    return {where: spec for where, specs in sources.items() for spec in specs if _name(spec) == "vgi-python"}


@pytest.mark.parametrize("where", sorted(_vgi_python_requirements()))
def test_vgi_python_pulls_in_a_filter_engine(where: str) -> None:
    """vgi-python needs an in-process DuckDB engine, and the dev group's `duckdb` hides its absence."""
    spec = _vgi_python_requirements()[where]
    bracket = re.search(r"\[([^\]]*)\]", spec)
    extras = {e.strip() for e in bracket.group(1).split(",")} if bracket else set()
    assert "haybarn" in extras, f"{where}: {spec!r} lacks the `haybarn` extra"


class TestLicenseMetadata:
    """MIT must survive in the forms GitHub and packaging tools actually read."""

    def test_license_is_an_spdx_expression(self, project: dict) -> None:
        assert project["license"] == "MIT"

    def test_no_deprecated_license_classifier(self, project: dict) -> None:
        assert [c for c in project.get("classifiers", []) if c.startswith("License ::")] == []

    def test_license_file_is_bare_mit(self) -> None:
        """Anything appended after the MIT text breaks GitHub's license detection."""
        text = (ROOT / "LICENSE").read_text()
        assert text.startswith("MIT License") and "Query Farm LLC" in text
        assert text.rstrip().endswith("SOFTWARE.")

    def test_data_terms_live_in_notice(self) -> None:
        notice = (ROOT / "NOTICE").read_text()
        assert "github-terms-of-service" in notice and "MIT License" in notice
