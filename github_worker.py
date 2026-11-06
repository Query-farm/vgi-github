# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http,duckdb]>=0.49.0",
#     "vgi-rpc>=0.53.1",
#     "httpx>=0.28.1",
#     "graphql-core>=3.2.6,<3.3",
# ]
# ///
"""Stdio entry point for the GitHub VGI worker (``uv run``).

ATTACH 'github' (TYPE vgi, LOCATION 'uv run github_worker.py');
"""

from __future__ import annotations

from vgi_github.worker import main

if __name__ == "__main__":
    main()
