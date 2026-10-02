# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http,haybarn]>=0.37.3",
#     "vgi-rpc>=0.47.2",
#     "httpx>=0.27",
# ]
# ///
"""Stdio entry point for the GitHub VGI worker (``uv run``).

ATTACH 'github' (TYPE vgi, LOCATION 'uv run github_worker.py');
"""

from __future__ import annotations

from vgi_github.worker import main

if __name__ == "__main__":
    main()
