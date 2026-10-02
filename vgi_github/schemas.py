"""Arrow schemas, and the flatteners that turn GitHub JSON into rows.

GitHub's payloads are deeply nested — an issue embeds its author, labels,
assignees, milestone and reactions as objects. Each flattener here lifts the
parts worth filtering and joining on into flat columns (``user_login`` rather
than a ``user`` struct), keeps genuinely list-valued things as lists
(``labels``), and drops the dozens of ``*_url`` API hypermedia links that
are only meaningful to a REST client.

Every conversion is total: one malformed value from one row must never fail the
batch it arrived in. A NULL is visible in the result; an exception loses every
row beside it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa

from vgi_github.meta import field

#: GitHub timestamps are ISO 8601 with a trailing ``Z``.
TIMESTAMP = pa.timestamp("us", tz="UTC")

#: The window a nanosecond-resolution consumer can hold. A value outside it
#: does not degrade in pandas or numpy ``datetime64[ns]``, it raises when the
#: client materializes the result, so it becomes NULL here instead.
_NS_FLOOR = datetime(1678, 1, 1, tzinfo=UTC)
_NS_CEILING = datetime(2262, 1, 1, tzinfo=UTC)


def to_timestamp(value: Any) -> datetime | None:
    """Parse an ISO 8601 string, or an epoch-seconds number, into an aware UTC datetime.

    Total: anything unparseable or unrepresentable becomes NULL rather than
    raising, and "representable" is judged by what a *consumer* can hold.
    """
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=UTC)
        except (ValueError, OverflowError, OSError):
            return None
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    if not _NS_FLOOR <= parsed <= _NS_CEILING:
        return None
    return parsed


def to_integer(value: Any) -> int | None:
    """Parse an integer, or None when the value is not one."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def column(rows: Sequence[dict[str, Any]], key: str, f: pa.Field) -> pa.Array:
    """Extract ``key`` from every row and build the Arrow array ``f`` declares.

    The conversion is chosen from the field's declared type, so a schema edit is
    the only thing needed to change how a column is parsed.
    """
    values = [row.get(key) for row in rows]
    if pa.types.is_timestamp(f.type):
        return pa.array([to_timestamp(v) for v in values], type=f.type)
    if pa.types.is_boolean(f.type):
        return pa.array([None if v is None else bool(v) for v in values], type=f.type)
    if pa.types.is_integer(f.type):
        return pa.array([to_integer(v) for v in values], type=f.type)
    if pa.types.is_string(f.type):
        return pa.array([None if v is None else str(v) for v in values], type=f.type)
    if pa.types.is_list(f.type) and pa.types.is_string(f.type.value_type):
        return pa.array(
            [
                [str(item) for item in v if item is not None] if isinstance(v, (list, tuple)) else None
                for v in values
            ],
            type=f.type,
        )
    # Anything else nested: let Arrow validate the shape, and isolate the rows
    # that do not match rather than losing the batch.
    try:
        return pa.array(values, type=f.type)
    except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError):
        return pa.array([_nullable(v, f.type) for v in values], type=f.type)


def _nullable(value: Any, kind: pa.DataType) -> Any:
    """``value`` if Arrow accepts it alone, else None."""
    if value is None:
        return None
    try:
        pa.array([value], type=kind)
    except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError):
        return None
    return value


def batch_from_rows(rows: Sequence[dict[str, Any]], schema: pa.Schema) -> pa.RecordBatch:
    """Build one RecordBatch by pulling each schema field out of ``rows`` by name."""
    return pa.RecordBatch.from_arrays([column(rows, f.name, f) for f in schema], schema=schema)


def _get(obj: Any, *path: str) -> Any:
    """``obj[path[0]][path[1]]...``, or None as soon as a level is missing."""
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _names(items: Any, key: str) -> list[str] | None:
    """``[item[key] for item in items]`` over a list of objects, tolerating junk."""
    if not isinstance(items, list):
        return None
    return [str(item[key]) for item in items if isinstance(item, dict) and item.get(key) is not None]


def repo_of_api_url(url: Any) -> str | None:
    """``owner/name`` from an API ``repository_url`` (``.../repos/owner/name``)."""
    if not isinstance(url, str) or "/repos/" not in url:
        return None
    tail = url.rsplit("/repos/", 1)[1].split("/")
    return f"{tail[0]}/{tail[1]}" if len(tail) >= 2 and tail[0] and tail[1] else None


# --------------------------------------------------------------------------
# Repositories
# --------------------------------------------------------------------------

REPO_SCHEMA = pa.schema(
    [
        field(
            "full_name",
            pa.string(),
            "Repository as 'owner/name' — the key every per-repository function takes.",
        ),
        field("id", pa.int64(), "GitHub's numeric repository id; survives renames and transfers."),
        field("owner_login", pa.string(), "Login of the user or organization that owns the repository."),
        field("owner_type", pa.string(), "Whether the owner is a 'User' or an 'Organization'."),
        field("name", pa.string(), "Repository name without the owner."),
        field("description", pa.string(), "The one-line description shown on the repository page."),
        field("html_url", pa.string(), "Link to the repository on github.com."),
        field("homepage", pa.string(), "Project website the owner configured, if any."),
        field("language", pa.string(), "Dominant language by bytes, as GitHub's linguist detects it."),
        field("topics", pa.list_(pa.string()), "Topic tags the owner applied, e.g. ['database', 'sql']."),
        field("license_spdx_id", pa.string(), "SPDX identifier of the detected license, e.g. 'MIT'."),
        field("visibility", pa.string(), "'public', 'private' or 'internal'."),
        field("is_private", pa.bool_(), "Whether the repository is private."),
        field("is_fork", pa.bool_(), "Whether this repository is a fork of another."),
        field("is_archived", pa.bool_(), "Whether the repository is archived (read-only)."),
        field("is_template", pa.bool_(), "Whether the repository is a template for new repositories."),
        field("default_branch", pa.string(), "Branch commits() lists when no sha is given, e.g. 'main'."),
        field("stargazers_count", pa.int64(), "Number of users who starred the repository."),
        field("forks_count", pa.int64(), "Number of forks."),
        field(
            "open_issues_count",
            pa.int64(),
            "Open issues PLUS open pull requests — GitHub counts both here, so this is not "
            "the open-issue count alone.",
        ),
        field(
            "watchers_count",
            pa.int64(),
            "Despite the name, GitHub reports the stargazer count here; kept for fidelity. "
            "Use stargazers_count.",
        ),
        field("size_kb", pa.int64(), "Repository size on disk in kilobytes, as GitHub measures it."),
        field("has_issues", pa.bool_(), "Whether the issue tracker is enabled."),
        field("has_wiki", pa.bool_(), "Whether the wiki is enabled."),
        field("has_discussions", pa.bool_(), "Whether GitHub Discussions is enabled."),
        field("created_at", TIMESTAMP, "When the repository was created."),
        field(
            "updated_at",
            TIMESTAMP,
            "When the repository object last changed (including stars); not a code-activity signal.",
        ),
        field("pushed_at", TIMESTAMP, "When a commit was last pushed to any branch; the activity signal."),
    ]
)


def flatten_repo(r: dict[str, Any]) -> dict[str, Any]:
    """One repository object as a :data:`REPO_SCHEMA` row."""
    return {
        "full_name": r.get("full_name"),
        "id": r.get("id"),
        "owner_login": _get(r, "owner", "login"),
        "owner_type": _get(r, "owner", "type"),
        "name": r.get("name"),
        "description": r.get("description"),
        "html_url": r.get("html_url"),
        "homepage": r.get("homepage") or None,
        "language": r.get("language"),
        "topics": r.get("topics"),
        "license_spdx_id": _get(r, "license", "spdx_id"),
        "visibility": r.get("visibility"),
        "is_private": r.get("private"),
        "is_fork": r.get("fork"),
        "is_archived": r.get("archived"),
        "is_template": r.get("is_template"),
        "default_branch": r.get("default_branch"),
        "stargazers_count": r.get("stargazers_count"),
        "forks_count": r.get("forks_count"),
        "open_issues_count": r.get("open_issues_count"),
        "watchers_count": r.get("watchers_count"),
        "size_kb": r.get("size"),
        "has_issues": r.get("has_issues"),
        "has_wiki": r.get("has_wiki"),
        "has_discussions": r.get("has_discussions"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
        "pushed_at": r.get("pushed_at"),
    }


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------

USER_SCHEMA = pa.schema(
    [
        field("login", pa.string(), "The account's handle — the key user() and repos() take."),
        field("id", pa.int64(), "GitHub's numeric account id; survives a login rename."),
        field("type", pa.string(), "'User', 'Organization' or 'Bot'."),
        field("name", pa.string(), "Display name, if set."),
        field("company", pa.string(), "Free-text company field, if set."),
        field("blog", pa.string(), "Website the account lists, if any."),
        field("location", pa.string(), "Free-text location, if set."),
        field("email", pa.string(), "Public email, if the account chose to publish one."),
        field("bio", pa.string(), "Profile bio, if set."),
        field("twitter_username", pa.string(), "X/Twitter handle, if set."),
        field("public_repos", pa.int64(), "Number of public repositories the account owns."),
        field("public_gists", pa.int64(), "Number of public gists."),
        field("followers", pa.int64(), "Number of followers."),
        field("following", pa.int64(), "Number of accounts this one follows."),
        field("html_url", pa.string(), "Link to the profile on github.com."),
        field("created_at", TIMESTAMP, "When the account was created."),
        field("updated_at", TIMESTAMP, "When the profile last changed."),
    ]
)


def flatten_user(u: dict[str, Any]) -> dict[str, Any]:
    """One user or organization object as a :data:`USER_SCHEMA` row."""
    return {
        "login": u.get("login"),
        "id": u.get("id"),
        "type": u.get("type"),
        "name": u.get("name"),
        "company": u.get("company"),
        "blog": u.get("blog") or None,
        "location": u.get("location"),
        "email": u.get("email"),
        "bio": u.get("bio"),
        "twitter_username": u.get("twitter_username"),
        "public_repos": u.get("public_repos"),
        "public_gists": u.get("public_gists"),
        "followers": u.get("followers"),
        "following": u.get("following"),
        "html_url": u.get("html_url"),
        "created_at": u.get("created_at"),
        "updated_at": u.get("updated_at"),
    }


# --------------------------------------------------------------------------
# Issues and pull requests
# --------------------------------------------------------------------------

ISSUE_SCHEMA = pa.schema(
    [
        field("repo", pa.string(), "Repository the issue belongs to, as 'owner/name'."),
        field("number", pa.int64(), "Issue number within the repository — what issue_comments() takes."),
        field("id", pa.int64(), "GitHub's globally unique issue id."),
        field("title", pa.string(), "Issue title."),
        field("state", pa.string(), "'open' or 'closed'."),
        field(
            "state_reason",
            pa.string(),
            "Why it is in its state: 'completed', 'not_planned', 'reopened' or 'duplicate'; NULL when unset.",
        ),
        field("user_login", pa.string(), "Login of the account that opened the issue."),
        field(
            "author_association",
            pa.string(),
            "The author's relationship to the repository: OWNER, MEMBER, COLLABORATOR, "
            "CONTRIBUTOR, FIRST_TIME_CONTRIBUTOR, FIRST_TIMER or NONE.",
        ),
        field("labels", pa.list_(pa.string()), "Names of the labels applied to the issue."),
        field("assignees", pa.list_(pa.string()), "Logins of everyone assigned to the issue."),
        field("milestone", pa.string(), "Title of the milestone the issue is filed under, if any."),
        field("comments", pa.int64(), "Number of comments on the issue."),
        field("reactions_total", pa.int64(), "Total reactions of every kind on the issue body."),
        field("reactions_plus_one", pa.int64(), "Thumbs-up reactions — the usual 'me too' signal."),
        field("is_locked", pa.bool_(), "Whether the conversation is locked."),
        field(
            "is_pull_request",
            pa.bool_(),
            "Whether this row is a pull request. GitHub's issue APIs return both; issues() "
            "excludes pull requests by default, search_issues() includes them unless the "
            "query says is:issue.",
        ),
        field("body", pa.string(), "Issue body as Markdown."),
        field("html_url", pa.string(), "Link to the issue on github.com."),
        field("created_at", TIMESTAMP, "When the issue was opened."),
        field("updated_at", TIMESTAMP, "When the issue last changed, including new comments."),
        field("closed_at", TIMESTAMP, "When the issue was closed; NULL while open."),
    ]
)


def flatten_issue(i: dict[str, Any], repo: str | None = None) -> dict[str, Any]:
    """One issue (or PR-as-issue) object as an :data:`ISSUE_SCHEMA` row.

    ``repo`` is stamped by a repository-scoped caller; without one it is read
    off ``repository_url``, which search results carry.
    """
    return {
        "repo": repo or repo_of_api_url(i.get("repository_url")),
        "number": i.get("number"),
        "id": i.get("id"),
        "title": i.get("title"),
        "state": i.get("state"),
        "state_reason": i.get("state_reason"),
        "user_login": _get(i, "user", "login"),
        "author_association": i.get("author_association"),
        "labels": _names(i.get("labels"), "name"),
        "assignees": _names(i.get("assignees"), "login"),
        "milestone": _get(i, "milestone", "title"),
        "comments": i.get("comments"),
        "reactions_total": _get(i, "reactions", "total_count"),
        "reactions_plus_one": _get(i, "reactions", "+1"),
        "is_locked": i.get("locked"),
        "is_pull_request": "pull_request" in i,
        "body": i.get("body"),
        "html_url": i.get("html_url"),
        "created_at": i.get("created_at"),
        "updated_at": i.get("updated_at"),
        "closed_at": i.get("closed_at"),
    }


PULL_SCHEMA = pa.schema(
    [
        field("repo", pa.string(), "Repository the pull request targets, as 'owner/name'."),
        field("number", pa.int64(), "Pull request number — shared with the issue namespace."),
        field("id", pa.int64(), "GitHub's globally unique pull request id."),
        field("title", pa.string(), "Pull request title."),
        field(
            "state",
            pa.string(),
            "'open' or 'closed'. A merged pull request is 'closed' — test merged_at IS NOT NULL for merged.",
        ),
        field("is_draft", pa.bool_(), "Whether the pull request is a draft."),
        field("user_login", pa.string(), "Login of the author."),
        field("author_association", pa.string(), "The author's relationship to the repository."),
        field("head_ref", pa.string(), "Branch the changes come from."),
        field(
            "head_repo", pa.string(), "Repository the head branch lives in ('owner/name'); differs for forks."
        ),
        field("head_sha", pa.string(), "Commit at the tip of the head branch."),
        field("base_ref", pa.string(), "Branch the changes would merge into."),
        field("labels", pa.list_(pa.string()), "Names of the labels applied."),
        field("assignees", pa.list_(pa.string()), "Logins of everyone assigned."),
        field("requested_reviewers", pa.list_(pa.string()), "Logins of reviewers still requested."),
        field("milestone", pa.string(), "Title of the milestone, if any."),
        field("merge_commit_sha", pa.string(), "The merge (or squash) commit once merged."),
        field("body", pa.string(), "Pull request description as Markdown."),
        field("html_url", pa.string(), "Link to the pull request on github.com."),
        field("created_at", TIMESTAMP, "When the pull request was opened."),
        field("updated_at", TIMESTAMP, "When it last changed."),
        field("closed_at", TIMESTAMP, "When it was closed or merged; NULL while open."),
        field("merged_at", TIMESTAMP, "When it was merged; NULL if it was closed unmerged or is open."),
    ]
)


def flatten_pull(p: dict[str, Any], repo: str | None = None) -> dict[str, Any]:
    """One pull request object as a :data:`PULL_SCHEMA` row."""
    return {
        "repo": repo or _get(p, "base", "repo", "full_name"),
        "number": p.get("number"),
        "id": p.get("id"),
        "title": p.get("title"),
        "state": p.get("state"),
        "is_draft": p.get("draft"),
        "user_login": _get(p, "user", "login"),
        "author_association": p.get("author_association"),
        "head_ref": _get(p, "head", "ref"),
        "head_repo": _get(p, "head", "repo", "full_name"),
        "head_sha": _get(p, "head", "sha"),
        "base_ref": _get(p, "base", "ref"),
        "labels": _names(p.get("labels"), "name"),
        "assignees": _names(p.get("assignees"), "login"),
        "requested_reviewers": _names(p.get("requested_reviewers"), "login"),
        "milestone": _get(p, "milestone", "title"),
        "merge_commit_sha": p.get("merge_commit_sha"),
        "body": p.get("body"),
        "html_url": p.get("html_url"),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
        "closed_at": p.get("closed_at"),
        "merged_at": p.get("merged_at"),
    }


ISSUE_COMMENT_SCHEMA = pa.schema(
    [
        field("repo", pa.string(), "Repository the comment belongs to, as 'owner/name'."),
        field("issue_number", pa.int64(), "Issue or pull request the comment is on."),
        field("id", pa.int64(), "GitHub's unique comment id."),
        field("user_login", pa.string(), "Login of the commenter."),
        field("author_association", pa.string(), "The commenter's relationship to the repository."),
        field("body", pa.string(), "Comment text as Markdown."),
        field("reactions_total", pa.int64(), "Total reactions on the comment."),
        field("html_url", pa.string(), "Link to the comment on github.com."),
        field("created_at", TIMESTAMP, "When the comment was posted."),
        field("updated_at", TIMESTAMP, "When the comment was last edited."),
    ]
)


def flatten_issue_comment(c: dict[str, Any], repo: str, number: int) -> dict[str, Any]:
    """One issue comment as an :data:`ISSUE_COMMENT_SCHEMA` row."""
    return {
        "repo": repo,
        "issue_number": number,
        "id": c.get("id"),
        "user_login": _get(c, "user", "login"),
        "author_association": c.get("author_association"),
        "body": c.get("body"),
        "reactions_total": _get(c, "reactions", "total_count"),
        "html_url": c.get("html_url"),
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
    }


# --------------------------------------------------------------------------
# Commits, releases, contributors, languages, stars
# --------------------------------------------------------------------------

COMMIT_SCHEMA = pa.schema(
    [
        field("repo", pa.string(), "Repository the commit was listed from, as 'owner/name'."),
        field("sha", pa.string(), "Full 40-character commit hash."),
        field("message", pa.string(), "Full commit message; the first line is the summary."),
        field("author_name", pa.string(), "Author name as recorded in the commit (git metadata)."),
        field("author_email", pa.string(), "Author email as recorded in the commit."),
        field("author_date", TIMESTAMP, "When the change was originally authored."),
        field(
            "author_login",
            pa.string(),
            "GitHub account matched to the author email; NULL when the email maps to no account.",
        ),
        field("committer_name", pa.string(), "Committer name as recorded in the commit."),
        field("committer_email", pa.string(), "Committer email as recorded in the commit."),
        field(
            "committer_date",
            TIMESTAMP,
            "When the commit was applied — differs from author_date after a rebase or cherry-pick.",
        ),
        field("committer_login", pa.string(), "GitHub account matched to the committer email."),
        field(
            "parent_shas",
            pa.list_(pa.string()),
            "Parent commit hashes; more than one means a merge commit.",
        ),
        field("comment_count", pa.int64(), "Number of commit comments."),
        field("is_verified", pa.bool_(), "Whether GitHub verified the commit's signature."),
        field("html_url", pa.string(), "Link to the commit on github.com."),
    ]
)


def flatten_commit(c: dict[str, Any], repo: str) -> dict[str, Any]:
    """One commit listing entry as a :data:`COMMIT_SCHEMA` row."""
    return {
        "repo": repo,
        "sha": c.get("sha"),
        "message": _get(c, "commit", "message"),
        "author_name": _get(c, "commit", "author", "name"),
        "author_email": _get(c, "commit", "author", "email"),
        "author_date": _get(c, "commit", "author", "date"),
        "author_login": _get(c, "author", "login"),
        "committer_name": _get(c, "commit", "committer", "name"),
        "committer_email": _get(c, "commit", "committer", "email"),
        "committer_date": _get(c, "commit", "committer", "date"),
        "committer_login": _get(c, "committer", "login"),
        "parent_shas": _names(c.get("parents"), "sha"),
        "comment_count": _get(c, "commit", "comment_count"),
        "is_verified": _get(c, "commit", "verification", "verified"),
        "html_url": c.get("html_url"),
    }


RELEASE_SCHEMA = pa.schema(
    [
        field("repo", pa.string(), "Repository the release belongs to, as 'owner/name'."),
        field("id", pa.int64(), "GitHub's unique release id."),
        field("tag_name", pa.string(), "Git tag the release points at, e.g. 'v1.2.0'."),
        field("name", pa.string(), "Release title; often the same as the tag."),
        field(
            "is_draft",
            pa.bool_(),
            "Whether the release is an unpublished draft (visible only with push access).",
        ),
        field("is_prerelease", pa.bool_(), "Whether the release is marked as a pre-release."),
        field("author_login", pa.string(), "Login of the account that created the release."),
        field("target_commitish", pa.string(), "Branch or commit the tag was created from."),
        field("assets_count", pa.int64(), "Number of downloadable assets attached."),
        field(
            "download_count",
            pa.int64(),
            "Total downloads across all attached assets. Source archives GitHub generates "
            "automatically are not counted.",
        ),
        field("body", pa.string(), "Release notes as Markdown."),
        field("html_url", pa.string(), "Link to the release on github.com."),
        field("created_at", TIMESTAMP, "When the release's commit was created."),
        field("published_at", TIMESTAMP, "When the release was published; NULL for a draft."),
    ]
)


def flatten_release(r: dict[str, Any], repo: str) -> dict[str, Any]:
    """One release as a :data:`RELEASE_SCHEMA` row."""
    assets = r.get("assets") if isinstance(r.get("assets"), list) else []
    downloads = sum(to_integer(a.get("download_count")) or 0 for a in assets if isinstance(a, dict))
    return {
        "repo": repo,
        "id": r.get("id"),
        "tag_name": r.get("tag_name"),
        "name": r.get("name"),
        "is_draft": r.get("draft"),
        "is_prerelease": r.get("prerelease"),
        "author_login": _get(r, "author", "login"),
        "target_commitish": r.get("target_commitish"),
        "assets_count": len(assets),
        "download_count": downloads,
        "body": r.get("body"),
        "html_url": r.get("html_url"),
        "created_at": r.get("created_at"),
        "published_at": r.get("published_at"),
    }


CONTRIBUTOR_SCHEMA = pa.schema(
    [
        field("repo", pa.string(), "Repository contributed to, as 'owner/name'."),
        field("login", pa.string(), "Contributor's login — feed it to user() for their profile."),
        field("id", pa.int64(), "Contributor's numeric account id."),
        field("type", pa.string(), "'User' or 'Bot'."),
        field("contributions", pa.int64(), "Commits to the default branch attributed to this account."),
        field("html_url", pa.string(), "Link to the contributor's profile."),
    ]
)


def flatten_contributor(c: dict[str, Any], repo: str) -> dict[str, Any]:
    """One contributor as a :data:`CONTRIBUTOR_SCHEMA` row."""
    return {
        "repo": repo,
        "login": c.get("login"),
        "id": c.get("id"),
        "type": c.get("type"),
        "contributions": c.get("contributions"),
        "html_url": c.get("html_url"),
    }


LANGUAGE_SCHEMA = pa.schema(
    [
        field("repo", pa.string(), "Repository measured, as 'owner/name'."),
        field("language", pa.string(), "Language name as GitHub's linguist reports it."),
        field("bytes", pa.int64(), "Bytes of code in this language; divide by the repo's sum for a share."),
    ]
)


def flatten_languages(payload: Any, repo: str) -> list[dict[str, Any]]:
    """The ``{language: bytes}`` object as one row per language, largest first."""
    if not isinstance(payload, dict):
        return []
    rows = [{"repo": repo, "language": k, "bytes": to_integer(v)} for k, v in payload.items()]
    return sorted(rows, key=lambda row: row["bytes"] or 0, reverse=True)


STARGAZER_SCHEMA = pa.schema(
    [
        field("repo", pa.string(), "Repository starred, as 'owner/name'."),
        field(
            "starred_at", TIMESTAMP, "When the star was given; the column a star-history chart is built on."
        ),
        field("login", pa.string(), "Login of the account that starred."),
        field("id", pa.int64(), "Numeric id of that account."),
        field("type", pa.string(), "'User' or 'Organization'."),
    ]
)


def flatten_stargazer(s: dict[str, Any], repo: str) -> dict[str, Any]:
    """One ``star+json`` stargazer entry as a :data:`STARGAZER_SCHEMA` row."""
    return {
        "repo": repo,
        "starred_at": s.get("starred_at"),
        "login": _get(s, "user", "login"),
        "id": _get(s, "user", "id"),
        "type": _get(s, "user", "type"),
    }


WORKFLOW_RUN_SCHEMA = pa.schema(
    [
        field("repo", pa.string(), "Repository the run belongs to, as 'owner/name'."),
        field("id", pa.int64(), "GitHub's unique run id."),
        field("name", pa.string(), "Workflow name, e.g. 'CI'."),
        field("workflow_id", pa.int64(), "Numeric id of the workflow definition that ran."),
        field("run_number", pa.int64(), "Per-workflow sequence number."),
        field("run_attempt", pa.int64(), "Attempt number; above 1 means the run was re-run."),
        field("event", pa.string(), "What triggered the run: 'push', 'pull_request', 'schedule', ..."),
        field(
            "status",
            pa.string(),
            "Lifecycle: 'queued', 'in_progress', 'completed', 'waiting', 'requested' or 'pending'.",
        ),
        field(
            "conclusion",
            pa.string(),
            "Outcome once completed: 'success', 'failure', 'cancelled', 'skipped', 'timed_out', "
            "'action_required', 'neutral' or 'stale'; NULL until the run completes.",
        ),
        field("head_branch", pa.string(), "Branch the run was triggered on."),
        field("head_sha", pa.string(), "Commit the run tested."),
        field("actor_login", pa.string(), "Account whose action triggered the run."),
        field("html_url", pa.string(), "Link to the run on github.com."),
        field("created_at", TIMESTAMP, "When the run was queued."),
        field("run_started_at", TIMESTAMP, "When the current attempt started executing."),
        field(
            "updated_at",
            TIMESTAMP,
            "When the run last changed; for a completed run, effectively when it finished.",
        ),
    ]
)


def flatten_workflow_run(w: dict[str, Any], repo: str) -> dict[str, Any]:
    """One workflow run as a :data:`WORKFLOW_RUN_SCHEMA` row."""
    return {
        "repo": repo,
        "id": w.get("id"),
        "name": w.get("name"),
        "workflow_id": w.get("workflow_id"),
        "run_number": w.get("run_number"),
        "run_attempt": w.get("run_attempt"),
        "event": w.get("event"),
        "status": w.get("status"),
        "conclusion": w.get("conclusion"),
        "head_branch": w.get("head_branch"),
        "head_sha": w.get("head_sha"),
        "actor_login": _get(w, "actor", "login"),
        "html_url": w.get("html_url"),
        "created_at": w.get("created_at"),
        "run_started_at": w.get("run_started_at"),
        "updated_at": w.get("updated_at"),
    }


# --------------------------------------------------------------------------
# Rate limit
# --------------------------------------------------------------------------

RATE_LIMIT_SCHEMA = pa.schema(
    [
        field(
            "resource",
            pa.string(),
            "Which budget this row describes: 'core' (most endpoints), 'search', 'graphql', ...",
        ),
        field(
            "request_limit",
            pa.int64(),
            "Requests allowed per window: 60/hour anonymously, 5,000 with a token.",
        ),
        field("used", pa.int64(), "Requests spent in the current window."),
        field("remaining", pa.int64(), "Count of requests left before the window resets."),
        field("reset_at", TIMESTAMP, "When the window resets and remaining returns to request_limit."),
        field(
            "authenticated",
            pa.bool_(),
            "Whether these figures are for a token (true) or this IP's anonymous budget (false).",
        ),
    ]
)


def flatten_rate_limit(payload: Any, *, authenticated: bool) -> list[dict[str, Any]]:
    """``/rate_limit``'s ``resources`` object as one row per budget."""
    resources = _get(payload, "resources")
    if not isinstance(resources, dict):
        return []
    return [
        {
            "resource": name,
            "request_limit": _get(r, "limit"),
            "used": _get(r, "used"),
            "remaining": _get(r, "remaining"),
            "reset_at": _get(r, "reset"),
            "authenticated": authenticated,
        }
        for name, r in sorted(resources.items())
        if isinstance(r, dict)
    ]
