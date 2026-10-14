"""Composition owns collisions; Crossfield owns expression and model validity."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from vgi_github.generation.examples import analysis_documentation, analysis_statements
from vgi_github.generation.native_overlay import apply_native_overlay, merge_native
from vgi_github.generation.overlay import load_overlay

ROOT = Path(__file__).resolve().parents[1]


def base_model():
    return {
        "invocations": {
            "sources": {
                "reviews": {
                    "dataset": {"fields": {"id": {"source_column": "id"}}},
                    "function": {"name": "reviews", "schema": "generated"},
                }
            },
            "input_contracts": {},
        },
        "metrics": {"count": {"expression": "COUNT(*)"}},
        "policy": {"metrics": ["count"], "detail_fields": ["reviews.id"]},
        "semantic_query": {"parameters": {}, "request": {"source_bindings": {}}},
    }


def test_native_stages_local_times_and_callable_inputs_pass_without_reinterpretation():
    fragment = {
        "invocations": {
            "sources": {"reviews": {"dataset": {"fields": {"hour": {"expression": "HOUR(reviews.at)"}}}}},
            "derived_datasets": {"latest": {"semantic_query": {"metrics": {"rank": "latest_rank"}}}},
            "input_contracts": {"cohort": {"columns": [{"name": "id", "type": "BIGINT"}]}},
        },
        "metrics": {"latest_rank": {"expression": "ROW_NUMBER() OVER (ORDER BY reviews.at DESC)"}},
        "policy": {
            "metrics": ["count", "latest_rank"],
            "local_time_fields": {"reviews.eastern": {"instant": "reviews.at", "zone": "America/New_York"}},
        },
        "semantic_query": {
            "parameters": {"people": {"type": "STRUCT(id BIGINT)[]", "default": None}},
            "request": {"inputs": {"people": {"definition": "cohort", "rows_parameter": "people"}}},
        },
    }
    before = deepcopy(fragment)
    model = apply_native_overlay(base_model(), fragment)
    assert fragment == before
    assert model["policy"]["metrics"] == ["count", "latest_rank"]
    assert model["invocations"]["sources"]["reviews"]["function"]["schema"] == "generated"
    assert model["invocations"]["derived_datasets"] == fragment["invocations"]["derived_datasets"]
    assert model["policy"]["local_time_fields"] == fragment["policy"]["local_time_fields"]
    assert model["semantic_query"]["request"]["inputs"] == fragment["semantic_query"]["request"]["inputs"]
    assert model["metrics"]["latest_rank"] == fragment["metrics"]["latest_rank"]


@pytest.mark.parametrize(
    "fragment, message",
    [
        ({"metrics": {"COUNT": {"expression": "SUM(reviews.id)"}}}, "collides with a generated definition"),
        ({"metrics": []}, "metrics must be an object"),
        ({"invocations": {"version": 7}}, "may add derived datasets"),
        ({"invocations": {"sources": {"unknown": {}}}}, "unknown generated dataset"),
        ({"invocations": {"sources": {"reviews": {"function": {"name": "replacement"}}}}}, "fields only"),
        (
            {"invocations": {"sources": {"reviews": {"dataset": {"fields": {"ID": {}}}}}}},
            "collides with a generated field",
        ),
        ({"policy": {"metrics": "all"}}, "conflicting native definition"),
        ({"freeform_sql": "SELECT 1"}, "unsupported native Crossfield sections"),
    ],
)
def test_native_additions_cannot_replace_generated_meaning(fragment, message):
    with pytest.raises(ValueError, match=message):
        apply_native_overlay(base_model(), fragment)


def test_domain_ownership_rejects_partial_redefinition_with_both_locations(tmp_path):
    manifest = {
        "format": "vgi-github-semantic-overlay",
        "version": 1,
        "model": {"name": "sample"},
        "domains": ["first.json", "second.json"],
    }
    (tmp_path / "pilot.json").write_text(json.dumps(manifest))
    (tmp_path / "first.json").write_text(json.dumps({"crossfield": {"metrics": {"total": {"expression": "1"}}}}))
    (tmp_path / "second.json").write_text(json.dumps({"crossfield": {"metrics": {"total": {"type": "BIGINT"}}}}))
    with pytest.raises(ValueError, match=r"second.json: duplicate native definition.*first.json"):
        load_overlay(tmp_path / "pilot.json")


def test_domains_merge_disjoint_definitions_but_not_case_variant_names():
    target, origins = {}, {}
    merge_native(target, {"metrics": {"one": {"expression": "COUNT(*)"}}}, source="first", origins=origins)
    merge_native(target, {"metrics": {"two": {"expression": "SUM(x)"}}}, source="second", origins=origins)
    assert list(target["metrics"]) == ["one", "two"]
    with pytest.raises(ValueError, match="duplicate native definition.*first"):
        merge_native(target, {"metrics": {"ONE": {}}}, source="third", origins=origins)


def test_analysis_defines_populations_and_grain_without_a_python_recipe():
    native = json.loads((ROOT / "generation/domains/analysis.json").read_text())["crossfield"]
    assert set(native["invocations"]["derived_datasets"]) == {
        "first_review_prs", "submitted_reviews", "latest_reviewer_reviews"
    }
    stage = native["invocations"]["derived_datasets"]["first_review_prs"]
    assert stage["dataset"]["grain"] == ["repository_id", "pull_request_number"]
    assert stage["semantic_query"]["metrics"]["first_review_hours"] == "pr_first_review_hours"
    assert "submitted_at IS NOT NULL" in native["policy"]["metric_semantics"]["pr_first_review_hours"]["population"]
    assert "review_id DESC" in native["metrics"]["review_latest_rank"]["expression"]
    assert native["policy"]["local_time_fields"]["authored_pull_requests.authored_pr_created_eastern"]["zone"] == (
        "America/New_York"
    )
    assert native["policy"]["field_semantics"]["authored_pull_requests.repository_node_id"]["sql_name"] == (
        "activity_repository_id"
    )
    assembled = load_overlay(ROOT / "generation/pilot.json")
    for name, expression in native["metrics"].items():
        assert assembled["crossfield"]["metrics"][name] == expression


def test_analysis_guide_uses_exact_natively_tested_sql():
    native_test = (ROOT / "tests/crossfield/analysis.test").read_text()
    guide = analysis_documentation()
    for statement in analysis_statements().values():
        assert statement in native_test
        assert statement in guide
