"""The shipped semantic package must cover every current worker entry point."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("github_semantic_builder", ROOT / "models/build_model.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
INVENTORY = json.loads((ROOT / "models/source_inventory.json").read_text())


def sql_type(value):
    if pa.types.is_timestamp(value):
        return "TIMESTAMPTZ" if value.tz else "TIMESTAMP"
    if pa.types.is_list(value):
        return sql_type(value.value_type) + "[]"
    return {pa.string(): "VARCHAR", pa.int64(): "BIGINT", pa.bool_(): "BOOLEAN", pa.binary(): "BLOB"}[value]


def test_complete_worker_and_rest_surface_is_pinned():
    builder.validate_surface(INVENTORY)
    assert len(INVENTORY["coverage"]["main_functions"]) == 21
    assert len(INVENTORY["coverage"]["rest_operation_ids"]) == 780


@pytest.mark.parametrize("function", INVENTORY["functions"], ids=lambda value: value["name"])
def test_inventory_matches_physical_output_columns(function):
    module = importlib.import_module(function["source_file"].removesuffix(".py").replace("/", "."))
    implementation = getattr(module, function["class"])
    actual = [(field.name, sql_type(field.type)) for field in implementation.FIXED_SCHEMA]
    expected = [
        (field["name"], field["type"].replace("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"))
        for field in function["result_columns"]
    ]
    assert actual == expected
    assert implementation.Meta.name == function.get("physical_name", function["name"])


def test_missing_main_function_fails_coverage_check():
    inventory = copy.deepcopy(INVENTORY)
    inventory["functions"] = [item for item in inventory["functions"] if item["name"] != "projects"]
    with pytest.raises(ValueError, match="main-function inventory changed"):
        builder.validate_surface(inventory)


def test_missing_rest_operation_fails_coverage_check():
    inventory = copy.deepcopy(INVENTORY)
    inventory["coverage"]["rest_operation_ids"].pop()
    with pytest.raises(ValueError, match="REST operation inventory changed"):
        builder.validate_surface(inventory)


def test_pinned_dispatcher_domain_cannot_silently_change():
    inventory = copy.deepcopy(INVENTORY)
    rest = next(item for item in inventory["functions"] if item["name"] == "rest_responses")
    rest["arguments"][0]["allowed_values"].pop()
    with pytest.raises(ValueError, match="dispatcher argument domain differs"):
        builder.validate_surface(inventory)


def test_raw_responses_do_not_approve_business_metrics():
    model, reports = builder.build("github.com", "https://api.github.com")
    assert model["name"] == "github"
    assert model["id"] == "queryfarm.github.reporting"
    assert all("crossfield_pipeline('github'," in report["semantic_sql"] for report in reports)
    assert len(model["invocations"]["sources"]) == 24
    assert len(model["metrics"]) == 51
    assert len(reports) == 49
    assert all(
        item["dataset"] not in builder.RAW_SOURCES for item in model["policy"]["metric_semantics"].values()
    )
    assert not (builder.RAW_SOURCES & model["semantic_query"]["request"]["source_bindings"].keys())
    assert {name + "_detail" for name in builder.RAW_SOURCES}.issubset({report["name"] for report in reports})


def test_generated_package_is_current_and_digests_match():
    subprocess.run([sys.executable, str(ROOT / "models/build_model.py"), "--check"], check=True, cwd=ROOT)


def test_project_metrics_keep_fixed_custom_field_population():
    model, reports = builder.build("github.com", "https://api.github.com")
    request = model["semantic_query"]["request"]
    assert request["source_bindings"]["project_items"]["arguments"]["fields"] == {"literal": ""}
    selected = next(report for report in reports if report["name"] == "project_item_values_detail")
    assert "project_fields" in {parameter["name"] for parameter in selected["parameters"]}
