"""The catalog shape the DuckDB extension will see on ATTACH."""

from __future__ import annotations

import json

import pyarrow as pa

from vgi_github.functions import KEYED_FUNCTIONS
from vgi_github.meta import comment_of
from vgi_github.search import SEARCH_FUNCTIONS
from vgi_github.worker import _GITHUB_CATALOG

SCHEMA = _GITHUB_CATALOG.schemas[0]


class TestLateralComposability:
    """Blended registration is what makes correlated LATERAL work."""

    def test_keyed_functions_are_blended(self) -> None:
        for func in KEYED_FUNCTIONS:
            assert func.get_metadata().input_from_args is True, func.Meta.name

    def test_no_finalize_override(self) -> None:
        """DuckDB rejects LATERAL on a table function that registers a finalize."""
        for func in KEYED_FUNCTIONS:
            assert func.has_finalize_override() is False, func.Meta.name

    def test_search_functions_are_streaming_scans(self) -> None:
        for func in SEARCH_FUNCTIONS:
            assert func.get_metadata().input_from_args is False, func.Meta.name


class TestMetadata:
    def test_every_function_is_registered(self) -> None:
        names = {f.Meta.name for f in SCHEMA.functions}
        assert {f.Meta.name for f in KEYED_FUNCTIONS + SEARCH_FUNCTIONS} <= names

    def test_every_function_asks_for_the_github_secret(self) -> None:
        for func in SCHEMA.functions:
            types = [s.secret_type for s in func.Meta.required_secrets]
            assert types == ["github"], func.Meta.name

    def test_every_column_is_documented(self) -> None:
        for func in SCHEMA.functions:
            for f in func.FIXED_SCHEMA:
                assert comment_of(f), f"{func.Meta.name}.{f.name}"

    def test_declared_result_schema_matches_the_arrow_schema(self) -> None:
        for func in SCHEMA.functions:
            declared = json.loads(func.Meta.tags["vgi.result_columns_schema"])
            assert [c["name"] for c in declared] == func.FIXED_SCHEMA.names, func.Meta.name

    def test_no_function_claims_filter_pushdown(self) -> None:
        """DuckDB does not push filters into table-in-out functions.

        Declaring it on a blended function would advertise an optimisation that
        never happens, and the docs steer filtering to named arguments instead.
        """
        for func in SCHEMA.functions:
            assert not func.get_metadata().filter_pushdown, func.Meta.name

    def test_no_reserved_word_columns(self) -> None:
        reserved = {"limit", "order", "group", "select", "from", "where", "user"}
        for func in SCHEMA.functions:
            assert not reserved & set(func.FIXED_SCHEMA.names), func.Meta.name

    def test_timestamps_are_utc(self) -> None:
        for func in SCHEMA.functions:
            for f in func.FIXED_SCHEMA:
                if pa.types.is_timestamp(f.type):
                    assert f.type.tz == "UTC", f"{func.Meta.name}.{f.name}"

    def test_executable_examples_parse(self) -> None:
        examples = json.loads(_GITHUB_CATALOG.tags["vgi.executable_examples"])
        assert examples and all({"name", "sql", "expected_result"} <= set(e) for e in examples)
