"""Assemble the reviewed GitHub semantic definitions into a Crossfield package.

Uses only the standard library; no DuckDB or worker imports. Run on the build
host. The inventory records the worker signature; this file owns business
definitions and report populations. Generated JSON is checked in for consumers.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_NAME = "github"
MODEL_ID = "queryfarm.github.reporting"
NAMESPACE = uuid.UUID("5f2482ab-ab61-4a85-8e56-f10b37f0a8bb")
ENGINE = "6b6099a3e9787f1b32c59fab61fcdd1d3bc835cd"
RAW_SOURCES = {"rest_responses", "graphql_responses", "api_endpoints"}
PUBLIC_ARGUMENTS = {
    "discussion_comments": {"number": "discussion_number"},
    "discussion_replies": {"node_id": "comment_node_id"},
    "projects": {"owner_type": "project_owner_type"},
    "project_items": {"number": "project_number", "owner_type": "project_owner_type"},
    "project_fields": {"number": "project_number", "owner_type": "project_owner_type"},
    "rest_responses": {
        "query": "rest_query",
        "accept": "rest_accept",
        "allow_not_found": "rest_allow_not_found",
    },
    "graphql_responses": {
        "query": "graphql_document",
        "variables": "graphql_variables",
        "operation_name": "graphql_operation_name",
    },
}


def validate_surface(inventory):
    """Detect omitted worker entries and REST manifest drift without importing a worker."""
    actual = {}
    collections = {
        "functions.py": "KEYED_FUNCTIONS",
        "search.py": "SEARCH_FUNCTIONS",
        "reference.py": "REFERENCE_FUNCTIONS",
        "datasets.py": "DATASET_FUNCTIONS",
    }
    for filename, collection in collections.items():
        tree = ast.parse((ROOT.parent / "vgi_github" / filename).read_text())
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        for node in tree.body:
            target = node.target if isinstance(node, ast.AnnAssign) else None
            if isinstance(node, ast.Assign):
                target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id != collection:
                continue
            for reference in node.value.elts:
                definition = classes[reference.id]
                for member in definition.body:
                    if isinstance(member, ast.ClassDef) and member.name == "Meta":
                        for item in member.body:
                            if isinstance(item, ast.Assign) and item.targets[0].id == "name":
                                actual[ast.literal_eval(item.value)] = reference.id
                    elif (
                        isinstance(member, ast.Assign)
                        and member.targets[0].id == "Meta"
                        and isinstance(member.value, ast.Call)
                    ):
                        actual[ast.literal_eval(member.value.args[0])] = reference.id
    worker = ast.parse((ROOT.parent / "vgi_github/worker.py").read_text())
    registrations = next(
        node.value
        for node in worker.body
        if isinstance(node, ast.Assign) and node.targets[0].id == "_FUNCTIONS"
    )
    if {node.value.id for node in registrations.elts} != set(collections.values()):
        raise ValueError("Worker main registration changed; review every new function collection")
    declared = {f["name"]: f["class"] for f in inventory["functions"] if f["schema"] == "main"}
    if actual != declared or sorted(actual) != inventory["coverage"]["main_functions"]:
        raise ValueError("Worker main-function inventory changed; review semantic coverage before generating")
    manifest = json.loads((ROOT.parent / "vgi_github/rest_manifest.json").read_text())
    operations = sorted(op["operation_id"] for op in manifest["operations"])
    if any(op["method"] != "GET" for op in manifest["operations"]):
        raise ValueError("Only GET operations can enter the approved REST response dispatcher")
    if operations != inventory["coverage"]["rest_operation_ids"]:
        raise ValueError("REST operation inventory changed; review and pin the new response coverage")
    if manifest["api_version"] != inventory["coverage"]["rest_api_version"]:
        raise ValueError("Pinned REST API version changed; review the semantic model")
    api_functions = {f["physical_name"]: f["name"] for f in inventory["functions"] if f["schema"] == "api"}
    if api_functions != inventory["coverage"]["api_functions"]:
        raise ValueError("Raw API semantic-source inventory changed")
    schemas = [
        node
        for node in ast.walk(worker)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Schema"
    ]
    api = next(
        node
        for node in schemas
        if any(
            keyword.arg == "path" and ast.literal_eval(keyword.value) == ["api"] for keyword in node.keywords
        )
    )
    registered_api = next(keyword.value for keyword in api.keywords if keyword.arg == "functions")
    if {node.id for node in registered_api.elts} != {
        f["class"] for f in inventory["functions"] if f["schema"] == "api"
    }:
        raise ValueError("Worker raw API registration changed; review semantic response coverage")
    tables = {}
    classes = {f["class"]: f["name"] for f in inventory["functions"]}
    for schema in schemas:
        path = ast.literal_eval(next(item.value for item in schema.keywords if item.arg == "path"))
        for keyword in schema.keywords:
            if keyword.arg != "tables":
                continue
            for table in keyword.value.elts:
                name = ast.literal_eval(next(item.value for item in table.keywords if item.arg == "name"))
                implementation = next(item.value.id for item in table.keywords if item.arg == "function")
                tables[".".join([*path, name])] = classes[implementation]
    if tables != inventory["coverage"]["catalog_tables"]:
        raise ValueError("Worker table aliases changed; record their semantic source coverage")
    rest = next(f for f in inventory["functions"] if f["name"] == "rest_responses")
    operation_arg = next(arg for arg in rest["arguments"] if arg["name"] == "operation_id")
    if operation_arg["allowed_values"] != operations:
        raise ValueError("REST dispatcher argument domain differs from the pinned operation inventory")


def text(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def literal(value):
    if value is None or isinstance(value, bool):
        return value
    return str(value)


def quote(value):
    return "'" + value.replace("'", "''") + "'"


def build(instance, origin):
    inventory = json.loads((ROOT / "source_inventory.json").read_text())
    validate_surface(inventory)
    functions = {f["name"]: f for f in inventory["functions"]}
    model = {
        "crossfield": 1,
        "name": MODEL_NAME,
        "id": MODEL_ID,
        "comment": "Approved live GitHub reporting. Complete keyed listings; search is capped discovery.",
        "invocations": {"version": 1, "input_contracts": {}, "sources": {}},
        "metrics": {},
        "policy": {
            "policy_version": 1,
            "metrics": [],
            "dimensions": [],
            "filter_dimensions": [],
            "detail_fields": [],
            "metric_semantics": {},
            "field_semantics": {},
            "dataset_semantics": {},
            "invocation_sources": [],
            "driving_grain_reduction": [],
        },
    }
    policy = model["policy"]
    sources = model["invocations"]["sources"]
    contracts = model["invocations"]["input_contracts"]
    reports = []

    def approve(dataset, name, field, comment):
        full = dataset + "." + name
        policy["detail_fields"].append(full)
        if field.get("dimension"):
            policy["dimensions"].append(full)
            policy["filter_dimensions"].append(full)
        policy["field_semantics"][full] = {"comment": comment, "sql_name": dataset + "_" + name}

    for name, function in functions.items():
        row_map = function["profile"] == "row_map_sync_v1"
        positional = [a for a in function["arguments"] if a["binding"] == "positional"]
        if row_map:
            driver = "repository_input" if [a["name"] for a in positional] == ["repo"] else name + "_input"
            function["driver"] = driver
            columns = [{"name": a["name"], "type": a["type"], "nullable": False} for a in positional]
            fields = {a["name"]: {"source_column": a["name"], "dimension": True} for a in positional}
            fresh = driver not in contracts
            contracts[driver] = {
                "id": MODEL_ID + "/inputs/" + driver,
                "dataset": {
                    "name": driver,
                    "id": MODEL_ID + "/datasets/" + driver,
                    "grain": [a["name"] for a in positional],
                    "fields": fields,
                },
                "columns": columns,
            }
            if fresh:
                for a in positional:
                    approve(driver, a["name"], fields[a["name"]], a["description"])
        arguments = []
        for a in function["arguments"]:
            arg = {
                "id": a["name"],
                "physical_name": a["name"],
                "type": a["type"],
                "nullable": a["nullable"],
                "binding": "scalar_or_driver" if row_map and a["binding"] == "positional" else "scalar",
            }
            if a["binding"] == "positional":
                arg["position"] = a["position"]
            else:
                arg["name"] = a["name"]
                if a["name"] not in PUBLIC_ARGUMENTS.get(name, {}) and not (
                    name == "project_items" and a["name"] == "fields"
                ):
                    fixed = 0 if a["name"] in {"max_rows", "max_pages", "cache_ttl"} else a["default"]
                    arg["allowed_values"] = [literal(fixed)]
            if "allowed_values" in a and "allowed_values" not in arg:
                arg["allowed_values"] = [literal(value) for value in a["allowed_values"]]
            arguments.append(arg)
        fields = {}
        columns = []
        for c in function["result_columns"]:
            dimension = (
                name not in RAW_SOURCES
                and c["type"] not in {"VARCHAR[]", "BLOB"}
                and c["name"]
                not in {
                    "body",
                    "message",
                    "description",
                    "html_url",
                    "homepage",
                    "fields_json",
                    "options_json",
                    "configuration_json",
                }
            )
            field = {"source_column": c["name"], "dimension": dimension}
            if c["type"] in {"TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE"}:
                field["timezone"] = "UTC"
            fields[c["name"]] = field
            approve(name, c["name"], field, c["description"])
            columns.append(
                {
                    "name": c["name"],
                    "type": c["type"],
                    "nullable": c["name"] not in function["required_nonnull_columns"],
                }
            )
        for member, argument in function.get("argument_grain", {}).items():
            fields[member] = {"source_argument": argument, "dimension": False}
            approve(name, member, fields[member], f"Request identity from the approved {argument} argument.")
        sources[name] = {
            "id": MODEL_ID + "/sources/" + name,
            "dataset": {
                "name": name,
                "id": MODEL_ID + "/datasets/" + name,
                "grain": function["grain"],
                "fields": fields,
            },
            "binding_key": "github_source",
            "provider_id": "queryfarm.vgi.github",
            "instance_id": instance,
            "function": {
                "schema": function["schema"],
                "name": function.get("physical_name", name),
                "arguments": arguments,
            },
            "profile": function["profile"],
            "result_columns": columns,
            "assertions": {
                "authority": MODEL_ID,
                "read_only": True,
                "execution_safe_bind": True,
                "input_from_args": row_map,
                "independent_rows": True,
                "requires_optimizer": False,
                "async": False,
            },
            "consistency": {"kind": "live_explicit", "authority": MODEL_ID},
            "settings": [],
            "required_secrets": [],
            "attachment_tags": {
                "vgi_github_reporting": "true",
                "vgi_github_operation_timeout_seconds": "120",
                "vgi_github_api_origin": origin,
            },
            "transport": {
                "finite_timeout_ms": 125000,
                "cooperative_cancellation": True,
                "authority": "queryfarm.vgi.posix-subprocess",
            },
        }
        policy["invocation_sources"].append(name)
        if row_map:
            policy["driving_grain_reduction"].append(name)
        policy["dataset_semantics"][name] = {
            "comment": function["description"],
            "tags": {"source_function": name, "observation": "live"},
        }

    def field(dataset, name, expression, kind, comment, dimension=True, unit=None):
        value = {"expression": expression, "type": kind, "dimension": dimension}
        if kind == "DATE":
            value.update(is_time=True, calendar="gregorian", granularity="day")
        if unit:
            value["unit"] = unit
        sources[dataset]["dataset"]["fields"][name] = value
        approve(dataset, name, value, comment)

    for dataset, names in {
        "pulls": ["created_at", "merged_at"],
        "issues": ["created_at", "closed_at"],
        "issue_comments": ["created_at"],
        "commits": ["committer_date"],
        "releases": ["published_at"],
        "stargazers": ["starred_at"],
        "workflow_runs": ["created_at"],
        "discussions": ["created_at", "answer_chosen_at"],
        "discussion_comments": ["created_at"],
        "discussion_replies": ["created_at"],
        "projects": ["created_at", "closed_at"],
        "project_items": ["created_at", "archived_at"],
    }.items():
        for name in names:
            label = name.removesuffix("_at").removesuffix("_date") + "_day"
            # Extract in the model-pinned UTC session. Governed plans reject
            # registered timezone casts; integer parts and string-to-DATE use
            # approved native functions. || preserves a NULL timestamp.
            timestamp = f"{dataset}.{name}"
            date = f"TO_DATE(YEAR({timestamp}) || '-' || MONTH({timestamp}) || '-' || DAY({timestamp}))"
            field(dataset, label, date, "DATE", f"UTC calendar date of {name}.")
    field(
        "pulls",
        "merge_hours",
        "DATEDIFF('millisecond', pulls.created_at, pulls.merged_at) / 3600000.0",
        "DOUBLE",
        "Elapsed creation-to-merge hours, including draft and waiting time; not review or business hours.",
        False,
        "h",
    )
    field(
        "issues",
        "close_hours",
        "DATEDIFF('millisecond', issues.created_at, issues.closed_at) / 3600000.0",
        "DOUBLE",
        "Elapsed creation to currently recorded closure; not time spent in open state across reopenings.",
        False,
        "h",
    )
    field(
        "discussions",
        "answer_hours",
        "DATEDIFF('millisecond', discussions.created_at, discussions.answer_chosen_at) / 3600000.0",
        "DOUBLE",
        "Elapsed creation-to-currently-selected-answer hours; not first response or business hours.",
        False,
        "h",
    )

    def metric(name, dataset, expression, comment, population=None, additive=True, unit=None):
        model["metrics"][name] = {"expression": expression}
        semantic = {
            "dataset": dataset,
            "additivity": "additive" if additive else "non_additive",
            "comment": comment,
        }
        if population:
            semantic.update(
                population=population,
                population_id=dataset + "/" + hashlib.sha256(population.encode()).hexdigest()[:12],
            )
        if unit:
            semantic["unit"] = unit
        policy["metrics"].append(name)
        policy["metric_semantics"][name] = semantic

    def count(name, dataset, comment, population=None):
        metric(name, dataset, "COUNT(*)", comment, population)

    count(
        "repository_count",
        "repos",
        "Visible repositories owned by the selected account, in a complete listing.",
    )
    metric(
        "repository_stars",
        "repo",
        "MAX(repo.stargazers_count)",
        "Current repository stars; one observation, never a historical sum.",
        additive=False,
    )
    metric(
        "repository_forks",
        "repo",
        "MAX(repo.forks_count)",
        "Current repository forks; one observation.",
        additive=False,
    )
    count("issue_count", "issues", "All listed issues, excluding pull requests.")
    count("open_issues", "issues", "Current open issues; not historical backlog.", "issues.state = 'open'")
    count(
        "closed_issues",
        "issues",
        "Issues currently closed, including repeated reopening/closing as one issue.",
        "issues.state = 'closed'",
    )
    metric(
        "mean_issue_close_hours",
        "issues",
        "AVG(issues.close_hours)",
        "Mean recorded closure duration for currently closed issues.",
        "issues.state = 'closed' AND issues.closed_at IS NOT NULL",
        False,
        "h",
    )
    count("pull_request_count", "pulls", "All pull requests in the complete selected repository population.")
    count(
        "open_pull_requests", "pulls", "Current open pull requests, including drafts.", "pulls.state = 'open'"
    )
    count(
        "open_draft_pull_requests",
        "pulls",
        "Current open draft pull requests.",
        "pulls.state = 'open' AND pulls.is_draft = TRUE",
    )
    count(
        "closed_unmerged_pull_requests",
        "pulls",
        "Closed pull requests with no merge timestamp.",
        "pulls.state = 'closed' AND pulls.merged_at IS NULL",
    )
    merged = "pulls.merged_at IS NOT NULL"
    count("merged_prs", "pulls", "Merged pull requests, including bots and draft waiting time.", merged)
    for name, expression, comment in [
        ("mean_merge_hours", "AVG(pulls.merge_hours)", "Mean elapsed hours; NULL for an empty merge cohort."),
        (
            "median_merge_hours",
            "MEDIAN(pulls.merge_hours)",
            "Exact continuous median elapsed hours; NULL for empty cohort.",
        ),
        (
            "p90_merge_hours",
            "PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY pulls.merge_hours)",
            "Exact continuous 90th percentile elapsed hours; non-additive.",
        ),
    ]:
        metric(name, "pulls", expression, comment, merged, False, "h")
    metric(
        "total_merge_hours",
        "pulls",
        "SUM(pulls.merge_hours)",
        "Sum elapsed hours; combine with merged_prs for a weighted mean.",
        merged,
        True,
        "h",
    )
    count(
        "issue_comment_count",
        "issue_comments",
        "Conversation comments on the selected issue or PR; excludes review comments.",
    )
    count(
        "commit_count",
        "commits",
        "Distinct listed commit identities on the default branch, using committer date for date reports.",
    )
    count(
        "verified_commit_count",
        "commits",
        "Listed commits whose signatures GitHub reports verified.",
        "commits.is_verified = TRUE",
    )
    count(
        "published_releases",
        "releases",
        "Published stable releases; excludes drafts and prereleases.",
        "releases.is_draft = FALSE AND releases.is_prerelease = FALSE AND releases.published_at IS NOT NULL",
    )
    count(
        "prereleases",
        "releases",
        "Published prereleases; excludes drafts.",
        "releases.is_draft = FALSE AND releases.is_prerelease = TRUE AND releases.published_at IS NOT NULL",
    )
    metric(
        "release_asset_downloads",
        "releases",
        "SUM(releases.download_count)",
        "Current cumulative downloads of attached assets, excluding generated source archives; "
        "not downloads during the report interval.",
        "releases.is_draft = FALSE",
        False,
    )
    count(
        "contributor_count",
        "contributors",
        "Contributors returned by GitHub's attributed default-branch contributor endpoint.",
    )
    metric(
        "attributed_commits",
        "contributors",
        "SUM(contributors.contributions)",
        "GitHub contributor contributions; not interchangeable with commit-history row count.",
    )
    count(
        "language_count", "languages", "Languages with entries in the current repository language response."
    )
    metric(
        "language_bytes",
        "languages",
        "SUM(languages.bytes)",
        "Current linguist-attributed bytes; not lines of code.",
    )
    count(
        "current_stargazers",
        "stargazers",
        "Currently visible stargazers; unstars disappear and no historical net-star metric is implied.",
    )
    count(
        "workflow_run_count",
        "workflow_runs",
        "Latest reported attempt of each run, one row per run ID; not all attempts.",
    )
    for name, outcome in [
        ("successful_runs", "success"),
        ("failed_runs", "failure"),
        ("timed_out_runs", "timed_out"),
        ("cancelled_runs", "cancelled"),
    ]:
        count(
            name,
            "workflow_runs",
            f"Runs whose latest reported conclusion is {outcome}.",
            f"workflow_runs.conclusion = '{outcome}'",
        )
    count(
        "eligible_runs",
        "workflow_runs",
        "Reliability denominator: success, failure and timed_out only.",
        "workflow_runs.conclusion IN ('success', 'failure', 'timed_out')",
    )
    metric(
        "ci_success_rate",
        "workflow_runs",
        "successful_runs * 1.0 / NULLIF(eligible_runs, 0)",
        "Success / (success + failure + timed_out), from latest reported run outcomes; "
        "NULL for zero denominator.",
        additive=False,
    )
    count("discussion_count", "discussions", "All visible discussions in the complete repository listing.")
    answered = "discussions.is_answered = TRUE"
    count("answered_discussions", "discussions", "Discussions with a currently selected answer.", answered)
    count(
        "unanswered_discussions",
        "discussions",
        "Discussions with no currently selected answer.",
        "discussions.is_answered = FALSE",
    )
    metric(
        "discussion_answer_rate",
        "discussions",
        "answered_discussions * 1.0 / NULLIF(discussion_count, 0)",
        "Currently answered / all visible discussions, across all categories; "
        "not an SLA or answerable-only rate.",
        additive=False,
    )
    for name, expression, description in [
        ("mean_discussion_answer_hours", "AVG(discussions.answer_hours)", "Mean"),
        ("median_discussion_answer_hours", "MEDIAN(discussions.answer_hours)", "Exact continuous median"),
    ]:
        metric(
            name,
            "discussions",
            expression,
            description + " creation-to-currently-selected-answer hours; NULL for an empty answered cohort.",
            answered,
            False,
            "h",
        )
    count(
        "discussion_comment_count",
        "discussion_comments",
        "Top-level comments on the selected discussion; excludes replies.",
    )
    count(
        "discussion_reply_count",
        "discussion_replies",
        "Replies to the selected discussion comment; not all comments in its discussion.",
    )
    count(
        "project_count", "projects", "Current visible Projects v2 owned by the selected organization or user."
    )
    count(
        "open_projects",
        "projects",
        "Projects currently open; not a historical backlog.",
        "projects.state = 'open'",
    )
    count(
        "closed_projects",
        "projects",
        "Projects currently closed; does not imply every item is complete.",
        "projects.state = 'closed'",
    )
    count(
        "project_item_count",
        "project_items",
        "Visible project item identities, including drafts and inaccessible content; "
        "not distinct issues across projects.",
    )
    for name, kind in [
        ("project_issue_items", "Issue"),
        ("project_pull_request_items", "PullRequest"),
        ("project_draft_items", "DraftIssue"),
    ]:
        count(
            name,
            "project_items",
            f"Project items whose declared content type is {kind}; "
            "inaccessible content remains in its declared category.",
            f"project_items.content_type = '{kind}'",
        )
    count(
        "archived_project_items",
        "project_items",
        "Project items with a recorded archive timestamp; not a completed-work measure.",
        "project_items.archived_at IS NOT NULL",
    )
    count(
        "project_field_count",
        "project_fields",
        "Current custom/system field definitions on the selected project; not populated item values.",
    )

    parameter_names = {
        "repo": "repository",
        "login": "login",
        "owner": "owner",
        "number": "issue_number",
        "query": "query",
    }

    def relation(source, detail=False, *, selected_project_fields=False):
        function = functions[source]
        params = []
        arguments = {}
        values = []
        for a in function["arguments"]:
            public_name = PUBLIC_ARGUMENTS.get(source, {}).get(a["name"])
            if source == "project_items" and a["name"] == "fields" and selected_project_fields:
                public_name = "project_fields"
            if a["binding"] == "positional" or public_name:
                name = public_name or parameter_names.get(a["name"], a["name"])
                params.append(
                    {"name": name, "type": a["type"], "nullable": False, "comment": a["description"]}
                )
                if function["profile"] == "row_map_sync_v1" and a["binding"] == "positional":
                    arguments[a["name"]] = {"member": function["driver"] + "." + a["name"]}
                    values.append({"parameter": name})
                else:
                    arguments[a["name"]] = {"parameter": name}
            else:
                arguments[a["name"]] = {
                    "literal": literal(
                        0 if a["name"] in {"max_rows", "max_pages", "cache_ttl"} else a["default"]
                    )
                }
        request = {"version": 1, "source_bindings": {source: {"arguments": arguments}}}
        if function["profile"] == "row_map_sync_v1":
            request["inputs"] = {"selection": {"definition": function["driver"], "rows": [values]}}
            request["source_bindings"][source].update(
                driver={"input": "selection"}, allow_driving_grain_reduction=True
            )
        if detail:
            request["detail_dataset"] = source
        sql = (
            "crossfield_pipeline("
            + quote(MODEL_NAME)
            + ","
            + quote(json.dumps(request, separators=(",", ":")))
        )
        sql += "".join(",$" + p["name"] for p in params) + ")"
        return sql, params, request

    # Expose provider inputs independently of saved report SELECTs. The semantic
    # compiler retains only the sources needed by the caller's metrics and
    # dimensions, so an owner or issue number is not required for a PR query.
    # Reusing repository_input also gives independent repository facts their
    # approved common driving grain without joining the raw API rows.
    semantic_parameters = {}
    semantic_request = {"version": 1, "inputs": {}, "source_bindings": {}}
    metric_sources = {value["dataset"] for value in policy["metric_semantics"].values()}
    for source in sorted(metric_sources):
        _, parameters, request = relation(source)
        for parameter in parameters:
            name = parameter["name"]
            definition = {key: value for key, value in parameter.items() if key != "name"}
            previous = semantic_parameters.setdefault(name, definition)
            if previous["type"] != definition["type"] or previous["nullable"] != definition["nullable"]:
                raise ValueError(f"Inconsistent semantic input {name!r}")
        source_binding = request["source_bindings"][source]
        for key, value in request.get("inputs", {}).items():
            input_name = value["definition"]
            previous = semantic_request["inputs"].setdefault(input_name, value)
            if previous != value:
                raise ValueError(f"Inconsistent semantic driver {input_name!r}")
            if source_binding.get("driver", {}).get("input") == key:
                source_binding["driver"]["input"] = input_name
        semantic_request["source_bindings"][source] = source_binding
    model["semantic_query"] = {"parameters": semantic_parameters, "request": semantic_request}

    def report(
        name,
        source,
        select,
        comment,
        *,
        detail=False,
        date=None,
        group=None,
        where=None,
        order=None,
        selected_project_fields=False,
    ):
        rel, params, _ = relation(source, detail, selected_project_fields=selected_project_fields)
        sql = f"SELECT {select} FROM {rel}"
        conditions = [where] if where else []
        if date:
            conditions.extend([f"{source}.{date} >= $start_day", f"{source}.{date} < $end_day"])
            params.extend(
                [
                    {
                        "name": "start_day",
                        "type": "DATE",
                        "nullable": False,
                        "comment": "Inclusive UTC calendar date.",
                    },
                    {
                        "name": "end_day",
                        "type": "DATE",
                        "nullable": False,
                        "comment": "Exclusive UTC calendar date.",
                    },
                ]
            )
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        if group:
            sql += " GROUP BY " + group
        if order:
            sql += " ORDER BY " + order
        reports.append(
            {
                "name": name,
                "report_id": str(uuid.uuid5(NAMESPACE, name)),
                "semantic_sql": sql,
                "parameters": params,
                "comment": comment,
                "tags": {
                    "source": source,
                    "consistency": "live",
                    "population": "response documents; no entity metric"
                    if source in RAW_SOURCES
                    else "capped discovery"
                    if source.startswith("search_")
                    else "complete endpoint within declared limits",
                },
            }
        )

    for source, f in functions.items():
        report(
            source + "_detail",
            source,
            ", ".join(f'{source}."{c["name"]}" AS "{c["name"]}"' for c in f["result_columns"]),
            f["description"]
            + (
                ". Capped search matches, not a complete population or approved total."
                if source.startswith("search_")
                else ". Response-level detail only; no entity aggregation or automatic nested expansion."
                if source in RAW_SOURCES
                else ". Complete visible source response within execution bounds."
            ),
            detail=True,
            order=", ".join(source + "." + k for k in f["grain"]),
        )
    report(
        "pr_overview",
        "pulls",
        "pull_request_count, open_pull_requests, open_draft_pull_requests, "
        "merged_prs, closed_unmerged_pull_requests",
        "Current PR state overview, all states and authors.",
    )
    merge_metrics = "merged_prs, mean_merge_hours, median_merge_hours, p90_merge_hours"
    report(
        "pr_merge_summary",
        "pulls",
        merge_metrics,
        "Merged-in-period throughput and elapsed creation-to-merge hours. Half-open UTC merge-date cohort.",
        date="merged_day",
    )
    report(
        "pr_merges_daily",
        "pulls",
        "pulls.merged_day AS merge_day, " + merge_metrics,
        "Daily merged cohort; missing days stay missing, never filled with zero.",
        date="merged_day",
        group="pulls.merged_day",
        order="pulls.merged_day",
    )
    report(
        "pr_merges_by_author",
        "pulls",
        "pulls.user_login AS author, " + merge_metrics,
        "Merged-in-period cohort by author; bots included. "
        "Means/percentiles cannot be averaged across authors.",
        date="merged_day",
        group="pulls.user_login",
        order="pulls.user_login NULLS LAST",
    )
    report(
        "merged_pr_detail",
        "pulls",
        "pulls.id AS id, pulls.repo AS repository, pulls.number AS number, pulls.title AS title, "
        "pulls.user_login AS author, pulls.created_at AS created_at, pulls.merged_at AS merged_at, "
        "pulls.merge_hours AS merge_hours, pulls.labels AS labels, pulls.html_url AS url",
        "The same merged cohort as pr_merge_summary, one row per PR.",
        detail=True,
        date="merged_day",
        order="pulls.id",
    )
    report(
        "issue_backlog",
        "issues",
        "issue_count, open_issues, closed_issues",
        "Current issue-only state, excluding PRs. No historical backlog reconstruction.",
    )
    report(
        "issue_closure_summary",
        "issues",
        "closed_issues, mean_issue_close_hours",
        "Currently closed issues whose recorded closure falls in the UTC interval.",
        date="closed_day",
    )
    report(
        "commits_summary",
        "commits",
        "commit_count, verified_commit_count",
        "Default-branch commits by committer UTC date; not developer productivity or deployments.",
        date="committer_day",
    )
    report(
        "release_summary",
        "releases",
        "published_releases, prereleases, release_asset_downloads",
        "Releases published in the interval. Download values are lifetime counts observed now, "
        "not interval download increments.",
        date="published_day",
    )
    report(
        "contributors_summary",
        "contributors",
        "contributor_count, attributed_commits",
        "Current GitHub contributor attribution.",
    )
    report(
        "languages_summary",
        "languages",
        "languages.language AS language, language_bytes",
        "Current bytes by detected language.",
        group="languages.language",
        order="languages.language",
    )
    report(
        "stars_summary",
        "stargazers",
        "current_stargazers",
        "Current visible stargazers; requires repository administrator access under this worker profile.",
    )
    report(
        "ci_summary",
        "workflow_runs",
        "workflow_run_count, eligible_runs, successful_runs, failed_runs, timed_out_runs, "
        "cancelled_runs, ci_success_rate",
        "Runs created in the interval, using each run's current/latest reported attempt. "
        "Cancellation and skipped/other outcomes excluded from reliability denominator.",
        date="created_day",
    )
    report(
        "ci_by_workflow",
        "workflow_runs",
        "workflow_runs.name AS workflow, workflow_run_count, eligible_runs, successful_runs, ci_success_rate",
        "Same created-in-period current run outcomes grouped by workflow name.",
        date="created_day",
        group="workflow_runs.name",
        order="workflow_runs.name",
    )
    report(
        "repository_summary",
        "repo",
        "repository_stars, repository_forks",
        "One current repository observation.",
    )
    report(
        "account_repository_summary",
        "repos",
        "repository_count",
        "Complete visible owned repository listing for an account.",
    )
    report(
        "discussion_overview",
        "discussions",
        "discussion_count, answered_discussions, unanswered_discussions, discussion_answer_rate",
        "Current selected-answer coverage across all visible discussion categories; not an SLA.",
    )
    report(
        "discussion_answer_summary",
        "discussions",
        "answered_discussions, mean_discussion_answer_hours, median_discussion_answer_hours",
        "Currently answered discussions whose recorded answer selection falls in the UTC interval.",
        date="answer_chosen_day",
    )
    report(
        "discussion_comments_summary",
        "discussion_comments",
        "discussion_comment_count",
        "Top-level comments created in the UTC interval on the selected discussion; excludes replies.",
        date="created_day",
    )
    report(
        "discussion_replies_summary",
        "discussion_replies",
        "discussion_reply_count",
        "Replies created in the UTC interval under the selected parent comment.",
        date="created_day",
    )
    report(
        "projects_summary",
        "projects",
        "project_count, open_projects, closed_projects",
        "Current visible Projects v2 by declared owner type; project closure is not item completion.",
    )
    report(
        "project_items_summary",
        "project_items",
        "project_item_count, project_issue_items, project_pull_request_items, "
        "project_draft_items, archived_project_items",
        "Current project membership by content kind, including inaccessible content; "
        "archive state is not completion.",
    )
    report(
        "project_fields_summary",
        "project_fields",
        "project_field_count",
        "Current project field definitions; values on items remain separate detail.",
    )
    report(
        "project_item_values_detail",
        "project_items",
        ", ".join(
            f'project_items."{c["name"]}" AS "{c["name"]}"'
            for c in functions["project_items"]["result_columns"]
        ),
        "Complete project item detail with explicitly selected custom field IDs; "
        "fields_json retains nested values.",
        detail=True,
        order="project_items.id",
        selected_project_fields=True,
    )
    _, params, request = relation("pulls")
    _, _, ci = relation("workflow_runs")
    request["source_bindings"].update(ci["source_bindings"])
    rel = (
        "crossfield_pipeline("
        + quote(MODEL_NAME)
        + ","
        + quote(json.dumps(request, separators=(",", ":")))
        + ",$repository)"
    )
    reports.append(
        {
            "name": "repository_activity",
            "report_id": str(uuid.uuid5(NAMESPACE, "repository_activity")),
            "semantic_sql": "SELECT repository_input.repo AS repository, merged_prs, "
            "workflow_run_count, ci_success_rate FROM " + rel + " GROUP BY repository_input.repo",
            "parameters": params,
            "comment": "Independent complete PR and CI populations aggregated before combination at "
            "the requested repository. All visible history, current run outcomes; "
            "separate live observations, "
            "not a transactional snapshot.",
            "tags": {
                "source": "pulls,workflow_runs",
                "consistency": "live",
                "population": "complete endpoint within declared limits",
            },
        }
    )
    return model, reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--instance", default="github.com")
    parser.add_argument("--api-origin", default="https://api.github.com")
    parser.add_argument("--revision", type=int, default=1)
    parser.add_argument(
        "--check", action="store_true", help="Check coverage and exact generated artifacts without writing"
    )
    args = parser.parse_args()
    if not 1 <= args.revision <= 2**63 - 1:
        parser.error("--revision must be between 1 and 9223372036854775807")
    model, reports = build(args.instance, args.api_origin.rstrip("/"))
    if not args.check:
        args.output.mkdir(parents=True, exist_ok=True)
    raw = text(model)
    package_id = NAMESPACE if args.instance == "github.com" else uuid.uuid5(NAMESPACE, args.instance)
    package = {
        "format": "crossfield.package",
        "version": 2,
        "package_id": str(package_id),
        "revision": args.revision,
        "entrypoint": "github-reporting.crossfield.json",
        "comment": "GitHub live reporting definitions, UTC. "
        "No transactional snapshot or historical backlog is implied.",
        "tags": {"owner": "Query Farm", "provider": "vgi-github", "instance": args.instance},
        "documents": [
            {
                "path": "github-reporting.crossfield.json",
                "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "content": raw,
            }
        ],
        "reports": reports,
        "capabilities": {
            "engine_source_sha": ENGINE,
            "semantic_contract": {"min": 1, "max": 1},
            "parser_profile": "crossfield_builtin_v1",
            "lifecycle_min": 3,
        },
        "approval": {
            "authority": MODEL_ID,
            "reference": "models/README.md; deterministic SQLLogicTest qualification",
        },
        "tag_metadata": {},
        "checks": [],
    }
    artifacts = {
        "github-reporting.crossfield.json": raw,
        "reports.json": text(reports),
        "github-reporting.package.json": text(package),
    }
    for name, content in artifacts.items():
        path = args.output / name
        if args.check:
            if not path.is_file() or path.read_text() != content:
                raise ValueError(f"Generated model artifact is stale: {path}")
        else:
            path.write_text(content)
    print(
        f"{'Checked' if args.check else 'Wrote'} {len(model['invocations']['sources'])} sources, "
        f"{len(model['metrics'])} metrics "
        f"and {len(reports)} reports to {args.output}"
    )


if __name__ == "__main__":
    main()
