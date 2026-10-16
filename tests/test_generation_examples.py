"""Published SQL stays shared while expected answers remain independently owned."""

from __future__ import annotations

import re
import shutil

import pytest

from vgi_github.generation.examples import SOURCE, research_artifacts, research_documentation


def test_sql_edit_reaches_guide_and_native_test_without_rewriting_answers(tmp_path):
    source = tmp_path / "research"
    shutil.copytree(SOURCE, source)
    original = research_artifacts(source)
    monthly = source / "monthly_pr_activity.sql"
    sql = monthly.read_text().replace(
        "ORDER BY pull_request_created_month;", "ORDER BY pull_request_created_month ASC;"
    )
    monthly.write_text(sql)
    updated = research_artifacts(source)
    assert sql.strip() in updated["tests/crossfield/research_examples.test"]
    assert sql.strip() in research_documentation(source)
    # Numerical expectations stay independently authored after the query delimiter.
    path = "tests/crossfield/research_examples.test"
    expected_blocks = r"(?ms)^----\n(.*?)(?:\n\n|\Z)"
    original_answers = re.findall(expected_blocks, original[path])
    assert original_answers
    assert original_answers == re.findall(expected_blocks, updated[path])


def test_prepared_sql_edit_reaches_script_and_native_test_without_rewriting_answers(tmp_path):
    source = tmp_path / "research"
    shutil.copytree(SOURCE, source)
    original = research_artifacts(source)
    focus = source / "pr_focus.sql"
    sql = focus.read_text().replace("ORDER BY repository;", "ORDER BY repository ASC;")
    focus.write_text(sql)
    updated = research_artifacts(source)
    assert sql.strip() in updated["models/generated-pilot/research.sql"]
    assert sql.strip() in updated["tests/crossfield/research_examples.test"]
    delimiter = "# Monthly grouping"
    path = "tests/crossfield/research_examples.test"
    assert original[path].split(delimiter)[1] == updated[path].split(delimiter)[1]


def test_unknown_documentation_sql_reference_fails_generation(tmp_path):
    source = tmp_path / "research"
    shutil.copytree(SOURCE, source)
    (source / "guide.md.in").write_text("{{sql:misspelled_example}}")
    with pytest.raises(ValueError, match="Unknown SQL example"):
        research_documentation(source)


def test_blank_line_cannot_silently_truncate_native_test_statement(tmp_path):
    source = tmp_path / "research"
    shutil.copytree(SOURCE, source)
    monthly = source / "monthly_pr_activity.sql"
    monthly.write_text(monthly.read_text().replace("FROM engineering", "\nFROM engineering"))
    with pytest.raises(ValueError, match="one nonempty SQL block"):
        research_artifacts(source)
