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
    "discussions": ("repo", "number", "node_id"),
    "discussion_comments": ("repo", "discussion_number", "node_id"),
    "discussion_replies": ("repo", "discussion_number", "node_id", "reply_to_id"),
    "projects": ("owner", "owner_type", "number", "id", "node_id"),
    "project_items": ("owner", "owner_type", "project_number", "id", "node_id"),
    "project_fields": ("owner", "owner_type", "project_number", "id", "node_id"),
}

# Parent keys are constant within a listing, unlike its independent row IDs.
_DATASET_UNIQUE_FIELDS = {
    "discussions": ("number", "node_id"),
    "discussion_comments": ("node_id",),
    "discussion_replies": ("node_id",),
    "projects": ("number", "id", "node_id"),
    "project_items": ("id", "node_id"),
    "project_fields": ("id", "node_id"),
}
_DATASET_REQUIRED = {
    "discussions": ("is_answered", "comments", "upvote_count", "locked"),
    "discussion_comments": ("is_answer", "replies", "upvote_count"),
    "discussion_replies": ("is_answer", "replies", "upvote_count"),
    "projects": ("state", "is_public", "is_template"),
    "project_items": ("content_type",),
    "project_fields": ("name", "data_type"),
}

_REQUIRED_TIMES = {
    "pulls": ("created_at",),
    "issues": ("created_at",),
    "issue_comments": ("created_at",),
    "commits": ("committer_date",),
    "releases": ("created_at",),
    "stargazers": ("starred_at",),
    "workflow_runs": ("created_at",),
    **dict.fromkeys(_DATASET_REQUIRED, ("created_at", "updated_at")),
}


def output_schema(name: str, schema: pa.Schema, attach: bytes | None) -> pa.Schema:
    """Publish validated nullability without changing exploratory schemas."""
    if not auth.reporting_of(attach):
        return schema
    required = IDENTITIES.get(name, ())
    if name in _DATASET_REQUIRED:
        required += _DATASET_REQUIRED[name] + _REQUIRED_TIMES[name]
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


def validate_dataset_payloads(name: str, rows: list[dict[str, Any]]) -> None:
    """Distinguish declared optional values from missing population/state evidence."""
    if not api.reporting_enabled():
        return
    required = {
        "discussions": ("answer", "answerChosenAt"),
        "discussion_comments": ("replyTo",),
        "discussion_replies": ("replyTo",),
        "projects": ("closed_at",),
        "project_items": ("content", "archived_at"),
    }.get(name, ())
    for row in rows:
        api.remaining_time()
        for column in required:
            if column not in row:
                raise api.GitHubReportingError(f"GitHub reporting {name} is missing {column}")
        for column in {
            "discussions": ("answer",),
            "discussion_comments": ("replyTo",),
            "discussion_replies": ("replyTo",),
            "project_items": ("content",),
        }.get(name, ()):
            value = row[column]
            if value is not None and not isinstance(value, dict):
                raise api.GitHubReportingError(f"GitHub reporting {name} requires an object or NULL {column}")
            if column in ("answer", "replyTo") and value is not None:
                identity = value.get("id")
                if not isinstance(identity, str) or not identity.strip():
                    raise api.GitHubReportingError(f"GitHub reporting {name} requires a valid {column} id")
        if name == "project_items" and row["content"] is not None:
            content = row["content"]
            value = content.get("id")
            if type(value) is not int or not 0 < value <= 2**63 - 1:
                raise api.GitHubReportingError("GitHub reporting project_items requires a valid content id")
            # Draft content has no repository-local number or open/closed state.
            if row.get("content_type") in ("Issue", "PullRequest"):
                value = content.get("number")
                if type(value) is not int or not 0 < value <= 2**63 - 1:
                    raise api.GitHubReportingError(
                        "GitHub reporting project_items requires a valid content number"
                    )
                if content.get("state") not in ("open", "closed"):
                    raise api.GitHubReportingError("GitHub reporting project_items has invalid content state")


def validate_rows(name: str, rows: list[dict[str, Any]]) -> None:
    """Check identities and all supplied dates before output projection or SQL filtering."""
    if not api.reporting_enabled():
        return
    if name in ("repo", "user") and len(rows) != 1:
        raise api.GitHubReportingError(f"GitHub reporting {name} lookup requires exactly one valid object")
    identities = IDENTITIES[name]
    unique = _DATASET_UNIQUE_FIELDS.get(
        name, tuple(c for c in identities if c not in ("repo", "issue_number"))
    )
    seen: dict[str, set[Any]] = {column: set() for column in unique}
    for row in rows:
        api.remaining_time()
        for column in identities:
            value = row.get(column)
            if column in ("id", "number", "issue_number", "discussion_number", "project_number"):
                valid = type(value) is int and 0 < value <= 2**63 - 1
            else:
                valid = isinstance(value, str) and bool(value.strip())
            if not valid:
                raise api.GitHubReportingError(f"GitHub reporting {name} requires a valid non-NULL {column}")
        # Each listing is per input key; parent identifiers can repeat.
        for column, values in seen.items():
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
            "discussions": ("comments", "upvote_count"),
            "discussion_comments": ("replies", "upvote_count"),
            "discussion_replies": ("replies", "upvote_count"),
        }.get(name, ()):
            _nonnegative_integer(row.get(column), column)
        for column in {
            "pulls": ("is_draft",),
            "commits": ("is_verified",),
            "releases": ("is_draft", "is_prerelease"),
            "discussions": ("is_answered", "locked"),
            "discussion_comments": ("is_answer",),
            "discussion_replies": ("is_answer",),
            "projects": ("is_public", "is_template"),
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
        if name in _DATASET_REQUIRED:
            for column in ("updated_at", "answer_chosen_at", "archived_at"):
                if column in times and times[column] < times["created_at"]:
                    raise api.GitHubReportingError(f"GitHub reporting {name} has invalid {column} duration")
        if name == "discussions":
            answer = row.get("answer_comment_id")
            if row["is_answered"]:
                if not isinstance(answer, str) or not answer.strip() or "answer_chosen_at" not in times:
                    raise api.GitHubReportingError(
                        "GitHub reporting answered discussion requires answer ID/time"
                    )
            elif answer is not None or "answer_chosen_at" in times:
                raise api.GitHubReportingError("GitHub reporting unanswered discussion has answer ID/time")
        if name == "discussion_comments" and row.get("reply_to_id") is not None:
            raise api.GitHubReportingError(
                "GitHub reporting top-level discussion comment cannot have reply_to_id"
            )
        if name.startswith("project") and row["owner_type"] not in ("organization", "user"):
            raise api.GitHubReportingError(f"GitHub reporting {name} has invalid owner_type")
        if name == "project_items" and row.get("content_type") not in ("Issue", "PullRequest", "DraftIssue"):
            raise api.GitHubReportingError("GitHub reporting project_items has invalid content_type")
        if name == "project_fields":
            for column in ("name", "data_type"):
                if not isinstance(row.get(column), str) or not row[column].strip():
                    raise api.GitHubReportingError(f"GitHub reporting project_fields requires {column}")
        if name in ("pulls", "issues", "projects"):
            if row.get("state") not in ("open", "closed"):
                raise api.GitHubReportingError(f"GitHub reporting {name} has invalid state")
            if row["state"] == "closed" and "closed_at" not in times:
                raise api.GitHubReportingError(f"GitHub reporting {name} requires closed_at for closed rows")
            if "closed_at" in times and times["closed_at"] < times["created_at"]:
                raise api.GitHubReportingError(f"GitHub reporting {name} has a negative closure duration")
            if name == "projects" and row["state"] == "open" and "closed_at" in times:
                raise api.GitHubReportingError("GitHub reporting open project cannot have closed_at")
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
