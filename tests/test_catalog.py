"""The catalog shape the DuckDB extension will see on ATTACH."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow as pa
import pytest
from vgi.catalog import SchemaObjectType
from vgi.catalog.contents_codec import decode_inventory
from vgi.client import Client
from vgi.protocol import CatalogAttachRequest, CatalogContentsResponse

from vgi_github import auth
from vgi_github.functions import KEYED_FUNCTIONS
from vgi_github.meta import comment_of
from vgi_github.search import SEARCH_FUNCTIONS
from vgi_github.worker import _GITHUB_CATALOG, GitHubCatalog, GitHubWorker

SCHEMA = _GITHUB_CATALOG.schemas[0]


class TestCatalogContents:
    def test_bulk_serialization_matches_per_schema_rpcs(self) -> None:
        worker = GitHubWorker()
        attached = worker.catalog_attach(
            CatalogAttachRequest(
                name="github", options=None, data_version_spec=None, implementation_version=None
            )
        )
        assert attached.supports_catalog_contents
        assert attached.catalog_version_frozen
        assert attached.attach_opaque_data_required
        attach = bytes(attached.attach_opaque_data)
        response = worker.catalog_contents(attach)
        decoded = CatalogContentsResponse.deserialize_from_bytes(response.serialize_to_bytes())
        assert decoded.catalog_version == attached.catalog_version
        assert not decoded.not_modified
        schemas = decode_inventory(decoded)
        assert [s.schema.path for s in schemas] == [["main"], ["rest"], ["api"]]
        main = schemas[0]
        assert [s.schema for s in schemas] == worker.catalog_schemas(attach).to_infos()
        assert main.tables == worker.catalog_schema_contents_tables(attach, ["main"]).to_infos()
        assert len(main.tables) == 1
        assert (
            main.table_functions
            == worker.catalog_schema_contents_functions(
                attach, ["main"], SchemaObjectType.TABLE_FUNCTION
            ).to_infos()
        )
        assert len(main.table_functions) == len(SCHEMA.functions)
        for kind in (
            "views",
            "scalar_functions",
            "aggregate_functions",
            "scalar_macros",
            "table_macros",
            "indexes",
        ):
            assert getattr(main, kind) == []

    def test_client_bulk_contents_keep_attach_state_out_of_metadata(self) -> None:
        script = Path(__file__).resolve().parent.parent / "github_worker.py"
        attach_tokens = set()
        previous_schemas = None
        with Client([sys.executable, str(script)], pool=None, worker_limit=1) as client:
            for mode, ttl in [("off", 0), ("required", 300), ("auto", 60)]:
                attached = client.catalog_attach(
                    name="github",
                    options={"auth": mode, "cache_ttl": ttl},
                    data_version_spec=None,
                    implementation_version=None,
                )
                assert attached.supports_catalog_contents
                assert attached.attach_opaque_data_required
                assert attached.attach_opaque_data
                token = bytes(attached.attach_opaque_data)
                assert token not in attach_tokens
                attach_tokens.add(token)
                contents = client.contents(attach_opaque_data=attached.attach_opaque_data)
                assert [list(s.schema.path) for s in contents.schemas] == [["main"], ["rest"], ["api"]]
                assert all(s.schema.attach_opaque_data is None for s in contents.schemas)
                if previous_schemas is not None:
                    assert contents.schemas == previous_schemas
                previous_schemas = contents.schemas
                main = contents.schemas[0]
                assert main.schema.comment == SCHEMA.comment
                assert main.schema.tags == SCHEMA.tags
                assert [t.name for t in main.tables] == ["rate_limit"]
                assert {f.name for f in main.table_functions} == {f.Meta.name for f in SCHEMA.functions}


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


class TestAttachCaching:
    @pytest.mark.parametrize("mode", ["auto", "required", "off"])
    @pytest.mark.parametrize("ttl", [0, 300])
    def test_policy_round_trip(self, mode, ttl) -> None:
        result = GitHubCatalog().catalog_attach(
            name="github",
            options={"auth": mode, "cache_ttl": ttl},
            data_version_spec=None,
            implementation_version=None,
        )
        assert json.loads(result.attach_opaque_data) == {"auth": mode, "token_source": "", "cache_ttl": ttl}
        assert auth.mode_of(result.attach_opaque_data) == mode
        assert auth.cache_ttl_of(result.attach_opaque_data) == ttl

    @pytest.mark.parametrize("ttl", [-1, 1.5, True, "300", None])
    def test_invalid_ttl_rejected_at_attach(self, ttl) -> None:
        with pytest.raises(ValueError, match="cache_ttl must be a non-negative integer"):
            GitHubCatalog().catalog_attach(name="github", options={"cache_ttl": ttl})

    @pytest.mark.parametrize("data", [None, b"required", b'{"auth":"auto","token_source":""}'])
    def test_old_attach_payloads_keep_origin_policy(self, data) -> None:
        assert auth.cache_ttl_of(data) == 0
