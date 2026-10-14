"""Include maintained example SQL in guides, runnable files and normal SQLLogicTests.

This only assembles text. DuckDB executes and compares the tests; expected answers
are independently maintained in the test template, never obtained from execution.
"""

from __future__ import annotations

import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "generation/examples/research"
STATEMENTS = ("monthly_pr_activity", "activity_compare", "pr_focus", "activity_evidence", "user_cohort")
SQL_REFERENCE = re.compile(r"\{\{sql:([a-z_]+)\}\}")
SETUP = "SET TimeZone='UTC';\nSET crossfield_mode='semantic';"


def _statements(source: Path) -> dict[str, str]:
    result = {}
    for name in STATEMENTS:
        sql = (source / f"{name}.sql").read_text().strip()
        # A blank line ends a SQLLogicTest statement. Keeping each source as one
        # block lets the normal runner execute the SQL verbatim in every output.
        if not sql.endswith(";") or any(not line.strip() for line in sql.splitlines()):
            raise ValueError(f"Example {name} must be one nonempty SQL block ending in ';'")
        result[name] = sql
    return result


def _include(template: str, statements: dict[str, str]) -> str:
    def replacement(match: re.Match[str]) -> str:
        name = match[1]
        if name not in statements:
            raise ValueError(f"Unknown SQL example: {name}")
        return statements[name]

    rendered = SQL_REFERENCE.sub(replacement, template)
    if "{{sql:" in rendered:
        raise ValueError("Malformed SQL example reference")
    return rendered


def research_documentation(source: Path = SOURCE) -> str:
    return _include((source / "guide.md.in").read_text(), _statements(source)).rstrip()


def research_artifacts(source: Path = SOURCE) -> dict[str, str]:
    statements = _statements(source)
    script = (
        "-- Generated from generation/examples/research/*.sql. Edit those sources.\n"
        "-- Attach the generated github package as engineering first (see README.md).\n"
        "-- Prepared inputs: user, start/end UTC dates; compare/focus take two periods.\n"
        + SETUP
        + "\n\n"
        + "\n\n".join(statements[name] for name in STATEMENTS if name != "monthly_pr_activity")
        + "\n"
    )
    test = (
        "# Generated from generation/examples/research/research_examples.test.in.\n"
        "# SQL is included verbatim; expected results are maintained in that template.\n"
        + _include((source / "research_examples.test.in").read_text(), statements)
    )
    return {
        "models/generated-pilot/research.sql": script,
        "tests/crossfield/research_examples.test": test,
    }


ANALYSIS_EXAMPLES = (
    (
        "first_review",
        "First-review latency gives each reviewed PR one observation before the mean, median and P90. "
        "Pending or untimestamped records do not qualify; unreviewed PRs are absent, not zero-hour responses.",
    ),
    (
        "latest_review",
        "Latest-review counts select one submitted record per PR/reviewer by timestamp, then review ID. "
        "Missing timestamps and anonymous reviewers are excluded. Latest approvals count PR/reviewer pairs, "
        "not distinct people across PRs or GitHub merge eligibility.",
    ),
    (
        "monthly_share",
        "Repository shares require the complete approved user/month/repository grain, including identity "
        "and label columns. QUALIFY may select displayed groups after the denominator is computed; "
        "a repository WHERE filter cannot redefine that denominator. Hide identity columns in an outer "
        "projection if desired. An empty denominator yields NULL.",
    ),
    (
        "monthly_rank",
        "Monthly ranks compare only the selected visible user cohort. Equal counts share rank; users "
        "with no observed PRs have no activity row. This is activity volume, not an impact score.",
    ),
    (
        "reporting_zone",
        "UTC days and fixed US Eastern reporting days are explicit alternatives. The _eastern_day "
        "dimension uses America/New_York daylight-saving rules, never a GitHub profile location. "
        "Keep the required session TimeZone='UTC'; a changed session raises TIMEZONE_MISMATCH.",
    ),
)


def analysis_statements(source: Path = SOURCE.parent / "analysis") -> dict[str, str]:
    """The native analysis suite executes these same statements with fixed answers."""
    return {name: (source / f"{name}.sql").read_text().strip() for name, _ in ANALYSIS_EXAMPLES}


def analysis_documentation(source: Path = SOURCE.parent / "analysis") -> str:
    statements = analysis_statements(source)
    lines = [
        "## Review timing and activity composition",
        "",
        "These freely selectable metrics use model-owned stages and windows. The examples below "
        "use independently tested fixture accounts; replace example/researcher/alice/bob/carol with "
        "your repository owner and users. Keep every selected grouping column for fixed-grain windows.",
        "",
    ]
    for name, explanation in ANALYSIS_EXAMPLES:
        lines.extend([explanation, "", "```sql", statements[name], "```", ""])
    return "\n".join(lines).rstrip()
