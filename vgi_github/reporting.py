"""Validation for opt-in reporting, before projected Arrow output can omit bad rows."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from typing import Any

import pyarrow as pa

from vgi_github import auth
from vgi_github import github_api as api
from vgi_github.schemas import to_timestamp

IDENTITIES = {
    "repo": ("id", "full_name"),
    "repos": ("id", "full_name"),
    "user": ("id", "login"),
    "issues": ("repo", "id", "number"),
    "pulls": ("repo", "id", "number"),
    "issue_comments": ("repo", "issue_number", "id"),
    "commits": ("repo", "sha"),
    "releases": ("repo", "id"),
    "contributors": ("repo", "id"),
    "languages": ("repo", "language"),
    "stargazers": ("repo", "id"),
    "workflow_runs": ("repo", "id"),
    "search_repositories": ("id", "full_name"),
    "search_issues": ("repo", "id", "number"),
}

_REQUIRED_TIMES = {
    "pulls": ("created_at",),
    "issues": ("created_at",),
    "issue_comments": ("created_at",),
    "commits": ("committer_date",),
    "releases": ("created_at",),
    "stargazers": ("starred_at",),
    "workflow_runs": ("created_at",),
}


def output_schema(name: str, schema: pa.Schema, attach: bytes | None) -> pa.Schema:
    """Publish identity nullability for reporting without changing exploratory schemas."""
    if not auth.reporting_of(attach):
        return schema
    required = IDENTITIES.get(name, ())
    return pa.schema(
        [field.with_nullable(False) if field.name in required else field for field in schema],
        metadata=schema.metadata,
    )


def _timestamp(value: Any, name: str) -> datetime:
    # REST timestamp strings must carry an explicit offset, rather than having
    # a guessed zone turn a malformed duration into an approved observation.
    parsed = to_timestamp(value)
    aware = False
    if isinstance(value, str):
        with suppress(ValueError):
            aware = datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    if parsed is None or not aware:
        raise api.GitHubReportingError(f"GitHub reporting requires a valid timezone-aware {name}")
    return parsed


def validate_pull_payloads(rows: list[dict[str, Any]]) -> None:
    """Missing merge-state evidence must not silently turn into an unmerged PR."""
    if not api.reporting_enabled():
        return
    for row in rows:
        if "merged_at" not in row:
            raise api.GitHubReportingError("GitHub reporting pull request is missing merged_at")


def _nonnegative_integer(value: Any, label: str) -> None:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise api.GitHubReportingError(f"GitHub reporting requires a nonnegative integer {label}")


def validate_release_payloads(rows: list[dict[str, Any]]) -> None:
    """The total flattener must not repair malformed download counts to zero."""
    if not api.reporting_enabled():
        return
    for row in rows:
        assets = row.get("assets")
        if not isinstance(assets, list) or any(not isinstance(asset, dict) for asset in assets):
            raise api.GitHubReportingError("GitHub reporting release requires an assets array of objects")
        total = 0
        for asset in assets:
            value = asset.get("download_count")
            _nonnegative_integer(value, "asset download_count")
            total += value
        _nonnegative_integer(total, "release download_count")


def validate_languages(payload: dict[str, Any]) -> None:
    """Check byte counts before the exploratory flattener coerces values."""
    if api.reporting_enabled():
        for value in payload.values():
            _nonnegative_integer(value, "language bytes")


def validate_rows(name: str, rows: list[dict[str, Any]]) -> None:
    """Check identities and all supplied dates before output projection or SQL filtering."""
    if not api.reporting_enabled():
        return
    if name in ("repo", "user") and len(rows) != 1:
        raise api.GitHubReportingError(f"GitHub reporting {name} lookup requires exactly one valid object")
    identities = IDENTITIES[name]
    seen: dict[str, set[Any]] = {column: set() for column in identities if column != "repo"}
    for row in rows:
        api.remaining_time()
        for column in identities:
            value = row.get(column)
            if column in ("id", "number", "issue_number"):
                valid = type(value) is int and 0 < value <= 2**63 - 1
            else:
                valid = isinstance(value, str) and bool(value.strip())
            if not valid:
                raise api.GitHubReportingError(f"GitHub reporting {name} requires a valid non-NULL {column}")
        # Each listing is per key; number and id must both be unique. The
        # issue_number is the constant parent of a comment listing, not its key.
        for column, values in seen.items():
            if column == "issue_number":
                continue
            value = row[column]
            if column == "number":
                value = (row.get("repo"), value)
            if value in values:
                raise api.GitHubReportingError(
                    f"GitHub reporting {name} contains duplicate {column} {value!r}"
                )
            values.add(value)
        for column in {
            "repo": ("stargazers_count", "forks_count"),
            "repos": ("stargazers_count", "forks_count"),
            "contributors": ("contributions",),
            "languages": ("bytes",),
            "releases": ("download_count",),
        }.get(name, ()):
            _nonnegative_integer(row.get(column), column)
        for column in {
            "pulls": ("is_draft",),
            "commits": ("is_verified",),
            "releases": ("is_draft", "is_prerelease"),
        }.get(name, ()):
            if type(row.get(column)) is not bool:
                raise api.GitHubReportingError(f"GitHub reporting {name} requires a boolean {column}")
        times: dict[str, datetime] = {}
        for column, value in row.items():
            if (column.endswith("_at") or column in ("author_date", "committer_date")) and value is not None:
                times[column] = _timestamp(value, column)
        for column in _REQUIRED_TIMES.get(name, ()):
            if column not in times:
                raise api.GitHubReportingError(f"GitHub reporting {name} requires {column}")
        if name in ("pulls", "issues"):
            if row.get("state") not in ("open", "closed"):
                raise api.GitHubReportingError(f"GitHub reporting {name} has invalid state")
            if row["state"] == "closed" and "closed_at" not in times:
                raise api.GitHubReportingError(f"GitHub reporting {name} requires closed_at for closed rows")
            if "closed_at" in times and times["closed_at"] < times["created_at"]:
                raise api.GitHubReportingError(f"GitHub reporting {name} has a negative closure duration")
        if (
            name == "pulls"
            and "merged_at" in times
            and (row["state"] != "closed" or times["merged_at"] < times["created_at"])
        ):
            raise api.GitHubReportingError("GitHub reporting pull request has invalid merged duration/state")
        if name == "releases" and row["is_draft"] is False and "published_at" not in times:
            raise api.GitHubReportingError("GitHub reporting published release requires published_at")
        if name == "workflow_runs":
            status, conclusion = row.get("status"), row.get("conclusion")
            if status not in {"requested", "queued", "pending", "in_progress", "waiting", "completed"}:
                raise api.GitHubReportingError("GitHub reporting workflow run has invalid status")
            if status == "completed":
                if conclusion not in {
                    "success",
                    "failure",
                    "neutral",
                    "cancelled",
                    "skipped",
                    "timed_out",
                    "action_required",
                    "stale",
                    "startup_failure",
                }:
                    raise api.GitHubReportingError(
                        "GitHub reporting completed workflow requires a valid conclusion"
                    )
                # A cancelled/skipped run may never have started. It still
                # belongs in outcome totals; absent timing is not a duration.
                if "updated_at" not in times:
                    raise api.GitHubReportingError("GitHub reporting completed workflow requires updated_at")
            elif conclusion is not None:
                raise api.GitHubReportingError(
                    "GitHub reporting unfinished workflow cannot have a conclusion"
                )
            if (
                "run_started_at" in times
                and "updated_at" in times
                and times["updated_at"] < times["run_started_at"]
            ):
                raise api.GitHubReportingError("GitHub reporting workflow run has invalid completed duration")
