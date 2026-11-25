# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "vgi-python[http,duckdb]>=0.55.2,<0.56",
#     "vgi-rpc>=0.57.1",
#     "httpx>=0.28.1",
#     "graphql-core>=3.2.6,<3.3",
# ]
# ///
"""HTTP entry point for the GitHub VGI worker (``uv run serve.py --port 8000``)."""

from __future__ import annotations

from vgi_github.worker import main_http

if __name__ == "__main__":
    main_http()
