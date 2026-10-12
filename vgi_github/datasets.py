"""Typed Projects (REST) and Discussions (GraphQL), with bounded automatic paging."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated

import pyarrow as pa
from vgi.arguments import Arg, SecretLookupEntry
from vgi.invocation import BindResponse
from vgi.metadata import FunctionExample
from vgi.table_in_out_function import RowTransformFunction

from vgi_github import auth
from vgi_github import github_api as api
from vgi_github.functions import _fan_out
from vgi_github.meta import docs, examples, field
from vgi_github.schemas import TIMESTAMP, _get


def _schema(*columns):
    return pa.schema([field(name, kind, description) for name, kind, description in columns])


DISCUSSION_SCHEMA = _schema(
    ("repo", pa.string(), "Repository as owner/name; input to discussion_comments"),
    ("number", pa.int64(), "Discussion number within the repository"),
    ("node_id", pa.string(), "Global GraphQL discussion identifier"),
    ("title", pa.string(), "Discussion title"),
    ("body", pa.string(), "Discussion body in Markdown"),
    ("user_login", pa.string(), "Author login; NULL for a deleted author"),
    ("category_id", pa.string(), "GraphQL category identifier; accepted by the category_id filter"),
    ("category_name", pa.string(), "Discussion category name"),
    ("is_answered", pa.bool_(), "Whether an answer has been selected"),
    ("answer_comment_id", pa.string(), "Global node ID of the selected answer, if any"),
    ("comments", pa.int64(), "GitHub's discussion comment connection totalCount"),
    ("upvote_count", pa.int64(), "Number of upvotes on the discussion"),
    ("locked", pa.bool_(), "Whether the discussion is locked"),
    ("created_at", TIMESTAMP, "Discussion creation time in UTC"),
    ("updated_at", TIMESTAMP, "Last discussion update time in UTC"),
    ("answer_chosen_at", TIMESTAMP, "Time an answer was selected, or NULL"),
    ("html_url", pa.string(), "Browser URL of the discussion"),
)

DISCUSSION_COMMENT_SCHEMA = _schema(
    ("repo", pa.string(), "Repository containing the discussion"),
    ("discussion_number", pa.int64(), "Discussion number within the repository"),
    ("node_id", pa.string(), "Global comment ID; input to discussion_replies"),
    ("reply_to_id", pa.string(), "Global parent comment ID; NULL for top-level comments"),
    ("body", pa.string(), "Comment body in Markdown"),
    ("user_login", pa.string(), "Author login; NULL for a deleted author"),
    ("is_answer", pa.bool_(), "Whether this comment is the selected answer"),
    ("replies", pa.int64(), "Number of replies; read them with discussion_replies"),
    ("upvote_count", pa.int64(), "Number of upvotes on the comment"),
    ("created_at", TIMESTAMP, "Comment creation time in UTC"),
    ("updated_at", TIMESTAMP, "Last comment update time in UTC"),
    ("html_url", pa.string(), "Browser URL of the comment"),
)

_PROJECT_KEY = (
    ("owner", pa.string(), "Project owner login"),
    ("owner_type", pa.string(), "organization or user; pass the same owner_type to project functions"),
)
PROJECT_SCHEMA = _schema(
    *_PROJECT_KEY,
    ("number", pa.int64(), "Project number within its owner; input to project_items and project_fields"),
    ("id", pa.int64(), "Numeric project ID"),
    ("node_id", pa.string(), "Global GraphQL project identifier"),
    ("title", pa.string(), "Project title"),
    ("description", pa.string(), "Project description"),
    ("short_description", pa.string(), "Concise project description"),
    ("state", pa.string(), "Project state: open or closed"),
    ("is_public", pa.bool_(), "Whether the project is public"),
    ("is_template", pa.bool_(), "Whether the project is a template"),
    ("creator_login", pa.string(), "Login of the project creator"),
    ("created_at", TIMESTAMP, "Project creation time in UTC"),
    ("updated_at", TIMESTAMP, "Last project update time in UTC"),
    ("closed_at", TIMESTAMP, "Project closure time, or NULL"),
)
PROJECT_ITEM_SCHEMA = _schema(
    *_PROJECT_KEY,
    ("project_number", pa.int64(), "Project number within its owner"),
    ("id", pa.int64(), "Numeric project item ID; distinct from its content ID"),
    ("node_id", pa.string(), "Global GraphQL project item identifier"),
    ("content_type", pa.string(), "GitHub content type: Issue, PullRequest or DraftIssue"),
    ("content_id", pa.int64(), "Numeric ID of the issue, pull request or draft; NULL if inaccessible"),
    ("content_number", pa.int64(), "Repository issue or pull request number; NULL for drafts"),
    ("title", pa.string(), "Content title; NULL if content is inaccessible"),
    ("body", pa.string(), "Content body in Markdown"),
    ("state", pa.string(), "Content state; NULL for drafts or inaccessible content"),
    ("user_login", pa.string(), "Content author login"),
    ("html_url", pa.string(), "Content browser URL; NULL for drafts or inaccessible content"),
    ("creator_login", pa.string(), "Login of the user who added the project item"),
    ("created_at", TIMESTAMP, "Time the item was added to the project, in UTC"),
    ("updated_at", TIMESTAMP, "Last project item update time in UTC"),
    ("archived_at", TIMESTAMP, "Project item archive time, or NULL"),
    ("fields_json", pa.string(), "Custom field values as JSON; fields selects IDs, default is title only"),
)
PROJECT_FIELD_SCHEMA = _schema(
    *_PROJECT_KEY,
    ("project_number", pa.int64(), "Project number within its owner"),
    ("id", pa.int64(), "Numeric field ID; pass as a string in project_items fields"),
    ("node_id", pa.string(), "Global GraphQL field identifier"),
    ("name", pa.string(), "Project field name"),
    ("data_type", pa.string(), "GitHub field type, such as text, number, date, single_select or iteration"),
    ("options_json", pa.string(), "Single-select options as JSON, including IDs, names and colors"),
    ("configuration_json", pa.string(), "Iteration configuration as JSON, or NULL"),
    ("created_at", TIMESTAMP, "Field creation time in UTC"),
    ("updated_at", TIMESTAMP, "Last field update time in UTC"),
)


@dataclass(frozen=True, kw_only=True)
class ListArgs:
    max_rows: Annotated[
        int,
        Arg("max_rows", default=100, ge=0, doc="Rows per input key; 0 walks all pages, bounded at 100 pages"),
    ] = 100
    cache_ttl: Annotated[
        int | None,
        Arg(
            "cache_ttl",
            default=None,
            ge=0,
            doc="Cache seconds; omitted/NULL inherits ATTACH, 0 = origin policy",
        ),
    ] = None


@dataclass(frozen=True, kw_only=True)
class DiscussionsArgs(ListArgs):
    repo: Annotated[str, Arg(0, doc="Repository as owner/name")]
    answered: Annotated[
        bool | None,
        Arg("answered", default=None, doc="Only answered/unanswered discussions; NULL includes both"),
    ] = None
    category_id: Annotated[
        str, Arg("category_id", default="", doc="GraphQL category ID; empty includes all")
    ] = ""
    sort: Annotated[
        str,
        Arg(
            "sort", default="updated", choices=("updated", "created"), doc="Order by update or creation time"
        ),
    ] = "updated"
    direction: Annotated[
        str, Arg("direction", default="desc", choices=("asc", "desc"), doc="Sort direction")
    ] = "desc"


@dataclass(frozen=True, kw_only=True)
class DiscussionCommentsArgs(ListArgs):
    repo: Annotated[str, Arg(0, doc="Repository as owner/name")]
    number: Annotated[int, Arg(1, doc="Discussion number within the repository")]


@dataclass(frozen=True, kw_only=True)
class DiscussionRepliesArgs(ListArgs):
    node_id: Annotated[str, Arg(0, doc="Global node_id of a discussion comment")]


@dataclass(frozen=True, kw_only=True)
class ProjectOwnerArgs(ListArgs):
    owner: Annotated[str, Arg(0, doc="Organization or user login that owns the project")]
    owner_type: Annotated[
        str,
        Arg(
            "owner_type",
            default="organization",
            choices=("organization", "user"),
            doc="Kind of project owner",
        ),
    ] = "organization"


@dataclass(frozen=True, kw_only=True)
class ProjectsArgs(ProjectOwnerArgs):
    query: Annotated[str, Arg("query", default="", doc="GitHub Projects filter syntax, e.g. is:open")] = ""


@dataclass(frozen=True, kw_only=True)
class ProjectFieldsArgs(ProjectOwnerArgs):
    number: Annotated[int, Arg(1, doc="Project number within its owner, not the global project ID")]


@dataclass(frozen=True, kw_only=True)
class ProjectItemsArgs(ProjectFieldsArgs):
    query: Annotated[str, Arg("query", default="", doc="GitHub project item filter syntax")] = ""
    fields: Annotated[
        str, Arg("fields", default="", doc="Comma-separated field IDs; omitted returns only the title field")
    ] = ""


def _metadata(name, schema, category, description, detail, sql):
    """Keep documentation and executable examples on every typed entry point."""
    return type(
        "Meta",
        (),
        {
            "name": name,
            "description": description,
            "categories": [category, "blended"],
            "projection_pushdown": True,
            "required_secrets": [SecretLookupEntry(secret_type=auth.SECRET_TYPE)],
            "tags": docs(
                category=category,
                result_schema=schema,
                llm=detail
                + " Composes under LATERAL; max_rows caps each input key, not the whole SQL result.",
                md=detail + "\n\nPagination is automatic. Default `max_rows=100`; `max_rows=0` walks all "
                "pages, bounded at 100, and fails if more remain. "
                "Filter with named arguments before the cap. "
                "GitHub errors fail the query. These datasets are not approved Crossfield reporting sources. "
                "Cache TTLs follow ATTACH unless overridden; GraphQL has no automatic response caching.",
                example_queries=examples((description, sql)),
            ),
            "examples": [FunctionExample(sql=sql, description=description)],
        },
    )


def _bind(cls, params):
    _check_mode(params)
    return BindResponse(output_schema=cls.FIXED_SCHEMA)


def _check_mode(params):
    if auth.reporting_of(params.attach_opaque_data):
        raise api.GitHubReportingError(
            "Projects and Discussions are not approved Crossfield reporting sources"
        )


def _emit(cls, params, batch, out, columns, fetch):
    _check_mode(params)
    if params.args.max_rows < 0:
        raise api.GitHubInputError("max_rows must be non-negative")
    _fan_out(
        params,
        batch,
        out,
        columns,
        fetch,
        cache_ttl=params.args.cache_ttl,
        function_name=cls.Meta.name,
    )


def _positive_number(number):
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise api.GitHubInputError("number must be a positive integer")
    return number


_COMMENT_FIELDS = """
    id body author { login } isAnswer replyTo { id } replies { totalCount }
    upvoteCount createdAt updatedAt url
    discussion { number repository { nameWithOwner } }
"""
DISCUSSIONS_QUERY = """
query Discussions($owner: String!, $name: String!, $first: Int!, $after: String,
                  $answered: Boolean, $category: ID, $order: DiscussionOrder!) {
  repository(owner: $owner, name: $name) {
    discussions(first: $first, after: $after, answered: $answered,
                categoryId: $category, orderBy: $order) {
      nodes {
        id number title body author { login } category { id name } isAnswered
        answer { id } comments { totalCount } upvoteCount locked
        createdAt updatedAt answerChosenAt url repository { nameWithOwner }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
COMMENTS_QUERY = (
    """
query DiscussionComments($owner: String!, $name: String!, $number: Int!, $first: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) {
      comments(first: $first, after: $after) {
        nodes { ...CommentFields }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
    + "fragment CommentFields on DiscussionComment {"
    + _COMMENT_FIELDS
    + "}"
)
REPLIES_QUERY = (
    """
query DiscussionReplies($id: ID!, $first: Int!, $after: String) {
  node(id: $id) {
    __typename
    ... on DiscussionComment {
      replies(first: $first, after: $after) {
        nodes { ...CommentFields }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
    + "fragment CommentFields on DiscussionComment {"
    + _COMMENT_FIELDS
    + "}"
)


def _connection_rows(query, variables, path, max_rows, credentials):
    """Page one connection, rejecting malformed or non-advancing cursors."""
    rows, seen = [], set()
    cursor = None
    for _ in range(api.MAX_PAGES):
        first = min(api.PER_PAGE, max_rows - len(rows)) if max_rows else api.PER_PAGE
        payload = api.graphql_query(
            query, {**variables, "first": first, "after": cursor}, credentials=credentials
        )
        current = payload.get("data")
        if not isinstance(current, dict):
            raise api.GitHubError(200, "GraphQL", "Missing query data")
        # A nullable repository/discussion/node can legitimately be absent on
        # the first page. Disappearance mid-walk must never look like completion.
        for key in path:
            if current is None:
                if cursor is None:
                    return []
                raise api.GitHubError(200, "GraphQL", "Resource disappeared during pagination")
            if not isinstance(current, dict) or key not in current:
                raise api.GitHubError(200, "GraphQL", "Missing connection in query response")
            current = current[key]
        if not isinstance(current, dict):
            raise api.GitHubError(200, "GraphQL", "Missing connection in query response")
        nodes, info = current.get("nodes"), current.get("pageInfo")
        if (
            not isinstance(nodes, list)
            or any(not isinstance(node, dict) for node in nodes)
            or not isinstance(info, dict)
            or type(info.get("hasNextPage")) is not bool
        ):
            raise api.GitHubError(200, "GraphQL", "Malformed connection or pageInfo")
        rows.extend(nodes)
        if max_rows and len(rows) >= max_rows:
            return rows[:max_rows]
        if not info["hasNextPage"]:
            return rows
        cursor = info.get("endCursor")
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise api.GitHubError(200, "GraphQL", "Pagination cursor is missing or repeated")
        seen.add(cursor)
    raise api.GitHubPageLimitError("GraphQL " + ".".join(path), len(rows))


def _discussion(row, repo):
    return {
        "repo": _get(row, "repository", "nameWithOwner") or repo,
        "number": row.get("number"),
        "node_id": row.get("id"),
        "title": row.get("title"),
        "body": row.get("body"),
        "user_login": _get(row, "author", "login"),
        "category_id": _get(row, "category", "id"),
        "category_name": _get(row, "category", "name"),
        "is_answered": row.get("isAnswered"),
        "answer_comment_id": _get(row, "answer", "id"),
        "comments": _get(row, "comments", "totalCount"),
        "upvote_count": row.get("upvoteCount"),
        "locked": row.get("locked"),
        "created_at": row.get("createdAt"),
        "updated_at": row.get("updatedAt"),
        "answer_chosen_at": row.get("answerChosenAt"),
        "html_url": row.get("url"),
    }


def _comment(row):
    return {
        "repo": _get(row, "discussion", "repository", "nameWithOwner"),
        "discussion_number": _get(row, "discussion", "number"),
        "node_id": row.get("id"),
        "reply_to_id": _get(row, "replyTo", "id"),
        "body": row.get("body"),
        "user_login": _get(row, "author", "login"),
        "is_answer": row.get("isAnswer"),
        "replies": _get(row, "replies", "totalCount"),
        "upvote_count": row.get("upvoteCount"),
        "created_at": row.get("createdAt"),
        "updated_at": row.get("updatedAt"),
        "html_url": row.get("url"),
    }


class DiscussionsFunction(RowTransformFunction[DiscussionsArgs]):
    FIXED_SCHEMA = DISCUSSION_SCHEMA
    Meta = _metadata(
        "discussions",
        FIXED_SCHEMA,
        "discussions",
        "Repository discussions with typed columns",
        "Read discussions through GraphQL with GitHub credentials. Filter answered status or category_id; "
        "sort by updated (default) or created, descending by default. "
        "Use discussion_comments(repo, number) for top-level comments.",
        "SELECT number, title, category_name, comments FROM github.main.discussions("
        "'duckdb/duckdb', answered => false, max_rows => 10)",
    )

    @classmethod
    def on_bind(cls, params):
        return _bind(cls, params)

    @classmethod
    def process(cls, params, state, batch, out):
        args = params.args

        def fetch(repo, hint, credentials):
            owner, name = api.split_repo(repo)
            if args.sort not in ("created", "updated") or args.direction not in ("asc", "desc"):
                raise api.GitHubInputError("sort must be created/updated and direction must be asc/desc")
            rows = _connection_rows(
                DISCUSSIONS_QUERY,
                {
                    "owner": owner,
                    "name": name,
                    "answered": args.answered,
                    "category": args.category_id or None,
                    "order": {"field": args.sort.upper() + "_AT", "direction": args.direction.upper()},
                },
                ("repository", "discussions"),
                args.max_rows,
                credentials,
            )
            return [_discussion(row, repo) for row in rows]

        _emit(cls, params, batch, out, ["repo"], fetch)


class DiscussionCommentsFunction(RowTransformFunction[DiscussionCommentsArgs]):
    FIXED_SCHEMA = DISCUSSION_COMMENT_SCHEMA
    Meta = _metadata(
        "discussion_comments",
        FIXED_SCHEMA,
        "discussions",
        "Top-level comments on a discussion",
        "Read top-level comments through GraphQL with GitHub credentials, in GitHub connection order. "
        "Replies are a separate connection: use discussion_replies(node_id) to read them. "
        "A missing discussion without GraphQL errors yields no rows.",
        "SELECT c.user_login, c.body FROM github.main.discussions('duckdb/duckdb', max_rows => 1) d, "
        "LATERAL github.main.discussion_comments(d.repo, d.number, max_rows => 10) c",
    )

    @classmethod
    def on_bind(cls, params):
        return _bind(cls, params)

    @classmethod
    def process(cls, params, state, batch, out):
        def fetch(key, hint, credentials):
            repo, number = key
            owner, name = api.split_repo(repo)
            rows = _connection_rows(
                COMMENTS_QUERY,
                {"owner": owner, "name": name, "number": _positive_number(number)},
                ("repository", "discussion", "comments"),
                params.args.max_rows,
                credentials,
            )
            return [_comment(row) for row in rows]

        _emit(cls, params, batch, out, ["repo", "number"], fetch)


class DiscussionRepliesFunction(RowTransformFunction[DiscussionRepliesArgs]):
    FIXED_SCHEMA = DISCUSSION_COMMENT_SCHEMA
    Meta = _metadata(
        "discussion_replies",
        FIXED_SCHEMA,
        "discussions",
        "Replies to a discussion comment",
        "Pass a comment's global node_id from discussion_comments. Reads the replies connection "
        "through GraphQL with GitHub credentials, retaining discussion and parent-comment identifiers. "
        "The max_rows cap applies to each parent comment.",
        "SELECT r.user_login, r.body FROM github.main.discussions('duckdb/duckdb', max_rows => 1) d, "
        "LATERAL github.main.discussion_comments(d.repo, d.number, max_rows => 1) c, "
        "LATERAL github.main.discussion_replies(c.node_id, max_rows => 10) r",
    )

    @classmethod
    def on_bind(cls, params):
        return _bind(cls, params)

    @classmethod
    def process(cls, params, state, batch, out):
        def fetch(node_id, hint, credentials):
            if not node_id.strip():
                raise api.GitHubInputError("node_id must be a non-empty GraphQL node ID")
            return [
                _comment(row)
                for row in _connection_rows(
                    REPLIES_QUERY, {"id": node_id}, ("node", "replies"), params.args.max_rows, credentials
                )
            ]

        _emit(cls, params, batch, out, ["node_id"], fetch)


def _project_path(owner, owner_type, number=None):
    if owner_type not in ("organization", "user"):
        raise api.GitHubInputError("owner_type must be organization or user")
    prefix = "orgs" if owner_type == "organization" else "users"
    path = f"/{prefix}/{api.segment(owner)}/projectsV2"
    return path if number is None else f"{path}/{_positive_number(number)}"


def _json(value):
    return None if value is None else json.dumps(value, ensure_ascii=False)


class ProjectsFunction(RowTransformFunction[ProjectsArgs]):
    FIXED_SCHEMA = PROJECT_SCHEMA
    Meta = _metadata(
        "projects",
        FIXED_SCHEMA,
        "projects",
        "Projects owned by an organization or user",
        "List Projects v2 through REST. owner_type defaults to organization; use user for personal projects. "
        "query passes GitHub Projects search syntax before the row cap. GitHub controls listing order. "
        "Pass owner and number to project_items or project_fields using the same owner_type.",
        "SELECT number, title, state FROM github.main.projects('github', query => 'is:open', max_rows => 10)",
    )

    @classmethod
    def on_bind(cls, params):
        return _bind(cls, params)

    @classmethod
    def process(cls, params, state, batch, out):
        def fetch(owner, hint, credentials):
            rows = api.collect(
                _project_path(owner, params.args.owner_type),
                {"q": params.args.query or None},
                limit=params.args.max_rows or None,
                missing_ok=False,
                hint=hint,
                credentials=credentials,
            )
            return [
                {
                    **row,
                    "owner": _get(row, "owner", "login") or owner,
                    "owner_type": params.args.owner_type,
                    "is_public": row.get("public"),
                    "creator_login": _get(row, "creator", "login"),
                }
                for row in rows
            ]

        _emit(cls, params, batch, out, ["owner"], fetch)


class ProjectItemsFunction(RowTransformFunction[ProjectItemsArgs]):
    FIXED_SCHEMA = PROJECT_ITEM_SCHEMA
    Meta = _metadata(
        "project_items",
        FIXED_SCHEMA,
        "projects",
        "Project items with typed content columns",
        "Read a project's issues, pull requests and drafts through REST. number is the owner's project "
        "number, not its global ID. owner_type defaults to organization. query filters before the cap. "
        "Content columns are NULL when content is inaccessible. fields accepts comma-separated field IDs "
        "from project_fields; custom values stay in fields_json. Omitted fields requests title only.",
        "SELECT i.content_type, i.title, i.state FROM github.main.projects('github', max_rows => 1) p, "
        "LATERAL github.main.project_items(p.owner, p.number, max_rows => 10) i",
    )

    @classmethod
    def on_bind(cls, params):
        return _bind(cls, params)

    @classmethod
    def process(cls, params, state, batch, out):
        def fetch(key, hint, credentials):
            owner, number = key
            rows = api.collect(
                _project_path(owner, params.args.owner_type, number) + "/items",
                {"q": params.args.query or None, "fields": params.args.fields or None},
                limit=params.args.max_rows or None,
                missing_ok=False,
                hint=hint,
                credentials=credentials,
            )
            return [
                {
                    **row,
                    "owner": owner,
                    "owner_type": params.args.owner_type,
                    "project_number": number,
                    "content_id": _get(row, "content", "id"),
                    "content_number": _get(row, "content", "number"),
                    "title": _get(row, "content", "title"),
                    "body": _get(row, "content", "body"),
                    "state": _get(row, "content", "state"),
                    "user_login": _get(row, "content", "user", "login"),
                    "html_url": _get(row, "content", "html_url"),
                    "creator_login": _get(row, "creator", "login"),
                    "fields_json": _json(row.get("fields")),
                }
                for row in rows
            ]

        _emit(cls, params, batch, out, ["owner", "number"], fetch)


class ProjectFieldsFunction(RowTransformFunction[ProjectFieldsArgs]):
    FIXED_SCHEMA = PROJECT_FIELD_SCHEMA
    Meta = _metadata(
        "project_fields",
        FIXED_SCHEMA,
        "projects",
        "Field definitions for a project",
        "Read field IDs, names and types through REST. owner_type defaults to organization. "
        "Single-select options and iteration configuration are retained as JSON. Pass field IDs to "
        "project_items(fields => '123,456') to include those values in fields_json.",
        "SELECT f.id, f.name, f.data_type FROM github.main.projects('github', max_rows => 1) p, "
        "LATERAL github.main.project_fields(p.owner, p.number, max_rows => 20) f",
    )

    @classmethod
    def on_bind(cls, params):
        return _bind(cls, params)

    @classmethod
    def process(cls, params, state, batch, out):
        def fetch(key, hint, credentials):
            owner, number = key
            rows = api.collect(
                _project_path(owner, params.args.owner_type, number) + "/fields",
                limit=params.args.max_rows or None,
                missing_ok=False,
                hint=hint,
                credentials=credentials,
            )
            return [
                {
                    **row,
                    "owner": owner,
                    "owner_type": params.args.owner_type,
                    "project_number": number,
                    "options_json": _json(row.get("options")),
                    "configuration_json": _json(row.get("configuration")),
                }
                for row in rows
            ]

        _emit(cls, params, batch, out, ["owner", "number"], fetch)


DATASET_FUNCTIONS = [
    DiscussionsFunction,
    DiscussionCommentsFunction,
    DiscussionRepliesFunction,
    ProjectsFunction,
    ProjectItemsFunction,
    ProjectFieldsFunction,
]
