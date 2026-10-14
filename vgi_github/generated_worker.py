"""Opt-in pilot: python -m vgi_github.generated_worker adds the generated schema."""

from __future__ import annotations

import sys
from dataclasses import replace

from vgi import Worker
from vgi.catalog import Schema

from vgi_github import auth
from vgi_github.generated_runtime import load_functions
from vgi_github.worker import _GITHUB_CATALOG, _SHARED_SERVER_FLAGS, GitHubCatalog

GENERATED_FUNCTIONS = load_functions()
GENERATED_CATALOG = replace(
    _GITHUB_CATALOG,
    schemas=[
        *_GITHUB_CATALOG.schemas,
        Schema(
            path=["generated"],
            comment="Reviewed pilot entities compiled from pinned GitHub schemas",
            functions=GENERATED_FUNCTIONS,
        ),
    ],
)


class GeneratedGitHubCatalog(GitHubCatalog):
    """Inherit normal attach metadata, credentials and reporting policy."""

    catalog = GENERATED_CATALOG


class GeneratedGitHubWorker(Worker):
    catalog = GENERATED_CATALOG
    catalog_interface = GeneratedGitHubCatalog


def main() -> None:
    serving = any(
        arg == flag or arg.startswith(flag + "=") for arg in sys.argv[1:] for flag in _SHARED_SERVER_FLAGS
    )
    if serving and not auth.sources_allowed_on_server():
        auth.disallow_local_sources()
    GeneratedGitHubWorker.main()


if __name__ == "__main__":
    main()
