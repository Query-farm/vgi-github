"""Actions log decoding: line parsing, archive layout, and streamed job/run log scans."""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pyarrow as pa
import pytest

from tests.helpers import install
from vgi_github import github_api as api
from vgi_github import logs
from vgi_github.auth import Credentials
from vgi_github.logs import (
    JobLogsArgs,
    JobLogsFunction,
    LogScanState,
    LogTextFunction,
    LogTsFunction,
    RunLogsArgs,
    RunLogsFunction,
    WorkflowCommandFunction,
    archive_members,
    decode_line,
    parse_command,
    split_line,
    strip_ansi,
)

FIXTURES = Path(__file__).parent / "fixtures" / "actions_logs"
JOB_LOG = (FIXTURES / "job.log").read_bytes()
RUN_ZIP = (FIXTURES / "run_logs.zip").read_bytes()
BLOB = "https://blob.example.test"


# --------------------------------------------------------------------------
# Line parsing
# --------------------------------------------------------------------------


def test_split_line_parses_the_runner_prefix() -> None:
    stamp, body = split_line("﻿2026-07-21T12:00:00.1234567Z hello world")
    assert stamp == datetime(2026, 7, 21, 12, 0, 0, 123456, tzinfo=UTC)
    assert body == "hello world"
    assert split_line("no prefix here") == (None, "no prefix here")
    assert split_line("2026-07-21T12:00:00Z ") == (datetime(2026, 7, 21, 12, tzinfo=UTC), "")


def test_strip_ansi_removes_csi_and_osc() -> None:
    assert strip_ansi("\x1b[31;1mred\x1b[0m plain") == "red plain"
    assert strip_ansi("\x1b]8;;https://x\x07link\x1b]8;;\x07") == "link"
    assert strip_ansi("untouched") == "untouched"


def test_parse_command_decodes_workflow_commands() -> None:
    cmd = parse_command("::error file=src/a.py,line=42,title=Type%3A bad::one%0Atwo, three%25")
    assert cmd is not None
    assert cmd.command == "error"
    assert cmd.properties == [("file", "src/a.py"), ("line", "42"), ("title", "Type: bad")]
    assert cmd.message == "one\ntwo, three%"
    bare = parse_command("::endgroup::")
    assert bare is not None and (bare.command, bare.properties, bare.message) == ("endgroup", [], "")
    marker = parse_command("##[Warning]Deprecated")
    assert marker is not None and (marker.command, marker.message) == ("warning", "Deprecated")
    assert parse_command("plain output") is None
    assert parse_command("::not a command") is None
    assert parse_command("##[unterminated") is None


def test_decode_line_tracks_groups() -> None:
    groups: list[str] = []
    lines = [
        "2026-07-21T12:00:00.0000000Z before",
        "2026-07-21T12:00:00.0000000Z ##[group]Outer",
        "2026-07-21T12:00:00.0000000Z ##[group]Inner",
        "2026-07-21T12:00:00.0000000Z inside",
        "2026-07-21T12:00:00.0000000Z ##[endgroup]",
        "2026-07-21T12:00:00.0000000Z ##[endgroup]",
        "2026-07-21T12:00:00.0000000Z ##[endgroup]",
        "2026-07-21T12:00:00.0000000Z after",
    ]
    paths = [decode_line(line, groups)["group_path"] for line in lines]
    assert paths == [
        [],
        ["Outer"],
        ["Outer", "Inner"],
        ["Outer", "Inner"],
        ["Outer", "Inner"],
        ["Outer"],
        [],  # an unmatched endgroup is tolerated
        [],
    ]
    row = decode_line("2026-07-21T12:00:00Z \x1b[1m::notice::hi\x1b[0m", [])
    assert row["text"] == "::notice::hi"
    assert row["raw"].startswith("2026-07-21T12:00:00Z \x1b[1m")
    assert (row["command"], row["command_message"]) == ("notice", "hi")


# --------------------------------------------------------------------------
# Archive layout
# --------------------------------------------------------------------------


def test_archive_members_prefers_step_files_and_keeps_job_order() -> None:
    members = archive_members(
        ["1_lint.txt", "build/2_Run tests.txt", "0_build.txt", "build/1_Set up job.txt", "build/"]
    )
    assert [(m.file_name, m.job_name, m.step_number, m.step_name) for m in members] == [
        ("build/1_Set up job.txt", "build", 1, "Set up job"),
        ("build/2_Run tests.txt", "build", 2, "Run tests"),
        ("1_lint.txt", "lint", None, None),
    ]


def test_archive_members_handles_unnumbered_and_ten_plus_steps() -> None:
    members = archive_members(["0_j.txt", "j/10_ten.txt", "j/2_two.txt", "j/system.txt"])
    assert [m.step_number for m in members] == [2, 10, None]
    assert members[-1].step_name == "system"


# --------------------------------------------------------------------------
# Table functions against a mock GitHub
# --------------------------------------------------------------------------


@dataclass
class _Params:
    args: Any
    output_schema: pa.Schema
    secrets: Any = None
    attach_opaque_data: bytes | None = None


@dataclass
class _Out:
    batches: list[pa.RecordBatch] = field(default_factory=list)
    parents: list[list[int] | None] = field(default_factory=list)
    more: list[bool] = field(default_factory=list)
    logs: list[tuple[str, str]] = field(default_factory=list)

    def emit(self, batch, parent_rows=None, cache_control=None, more=False) -> None:
        assert cache_control is None, "log results must never be cached"
        self.batches.append(batch)
        self.parents.append(parent_rows)
        self.more.append(more)

    def client_log(self, level, message: str, **extra: str) -> None:
        self.logs.append((level.name, message))


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.url.host == "api.github.com":
        if path == "/repos/o/r/actions/jobs/7/logs":
            return httpx.Response(302, headers={"location": f"{BLOB}/job.log?sig=abc"})
        if path in ("/repos/o/r/actions/runs/5/logs", "/repos/o/r/actions/runs/5/attempts/2/logs"):
            return httpx.Response(302, headers={"location": f"{BLOB}/run.zip?sig=abc"})
        if path == "/repos/o/r/actions/runs/6/logs":
            return httpx.Response(302, headers={"location": f"{BLOB}/broken.zip"})
        if path == "/repos/o/r/actions/jobs/410/logs":
            return httpx.Response(410, json={"message": "Gone"})
        return httpx.Response(404, json={"message": "Not Found"})
    assert "authorization" not in request.headers, "the token must not follow the redirect"
    if path == "/job.log":
        return httpx.Response(200, content=JOB_LOG, headers={"content-type": "text/plain"})
    if path == "/run.zip":
        return httpx.Response(200, content=RUN_ZIP, headers={"content-type": "application/zip"})
    if path == "/broken.zip":
        return httpx.Response(200, content=b"not a zip", headers={"content-type": "application/zip"})
    return httpx.Response(404)


@pytest.fixture
def github(monkeypatch):
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    seen = install(monkeypatch, _handler)
    monkeypatch.setattr(logs.auth, "for_call", lambda *_a, **_k: Credentials("secret"))
    yield seen
    logs.SPOOLS.clear()


def _scan(
    func, args, columns: dict[str, list[Any]], *, roundtrip: bool = False, cold: bool = False
) -> tuple[list[dict[str, Any]], _Out]:
    """Run process() then resume() to the end, as the framework does."""
    params = _Params(args=args, output_schema=func.FIXED_SCHEMA)
    out = _Out()
    state = func.initial_state(params)
    func.process(params, state, pa.record_batch(columns), out)
    while out.more[-1]:
        if roundtrip:
            state = LogScanState.deserialize_from_bytes(state.serialize_to_bytes())
        if cold:
            logs.SPOOLS.clear()  # the next batch lands on another worker process
        func.resume(params, state, out)
        assert len(out.batches) < 1000
    rows: list[dict[str, Any]] = []
    for batch, parents in zip(out.batches, out.parents, strict=True):
        assert parents is not None and len(parents) == batch.num_rows
        for row, parent in zip(batch.to_pylist(), parents, strict=True):
            rows.append({**row, "_parent": parent})
    return rows, out


def test_job_logs_decodes_every_line(github) -> None:
    rows, out = _scan(JobLogsFunction, JobLogsArgs(repo="o/r", job_id=7), {"repo": ["o/r"], "job_id": [7]})
    assert out.more == [False]
    assert [r["line_number"] for r in rows] == list(range(1, 15))
    first = rows[0]
    assert first["timestamp"] == datetime(2026, 7, 21, 12, 0, 0, 123456, tzinfo=UTC)
    assert first["text"] == "Requested labels: ubuntu-latest"
    assert (first["repo"], first["job_id"]) == ("o/r", 7)
    assert rows[5]["text"] == "make test" and "\x1b[36;1m" in rows[5]["raw"]
    assert rows[5]["group_path"] == ["Run make test"]
    error = rows[9]
    assert error["command"] == "error"
    assert dict(error["command_properties"]) == {
        "file": "src/app.py",
        "line": "42",
        "col": "7",
        "title": "Type: error",
    }
    assert error["command_message"] == "Expected int, got str\nsecond line"
    assert [r["command"] for r in rows if r["command"] in ("error", "warning")] == [
        "error",
        "warning",
        "error",
    ]
    continuation = rows[12]
    assert continuation["timestamp"] is None
    assert continuation["text"] == "a continuation line without a timestamp"
    assert all(r["_parent"] == 0 for r in rows)
    # The API request carried the token; the blob request (asserted in the handler) did not.
    assert github[0].headers["authorization"] == "Bearer secret"
    assert len(logs.SPOOLS) == 0, "the spooled log is dropped once read"


def test_run_logs_reads_steps_in_order(github) -> None:
    rows, _ = _scan(RunLogsFunction, RunLogsArgs(repo="o/r", run_id=5), {"repo": ["o/r"], "run_id": [5]})
    files = [r["file_name"] for r in rows]
    assert files == ["build/1_Set up job.txt"] * 4 + ["build/2_Run tests.txt"] * 5 + ["1_lint.txt"] * 5
    assert [r["line_number"] for r in rows[:4]] == [1, 2, 3, 4]
    assert rows[4]["line_number"] == 1, "line numbers restart in each file"
    assert {(r["job_name"], r["step_number"], r["step_name"]) for r in rows} == {
        ("build", 1, "Set up job"),
        ("build", 2, "Run tests"),
        ("lint", None, None),
    }
    assert rows[7]["text"] == "1 failed, 41 passed"
    warning = rows[-2]
    assert (warning["command"], dict(warning["command_properties"])) == (
        "warning",
        {"file": "src/app.py", "line": "3"},
    )
    assert all(r["attempt"] is None and r["run_id"] == 5 for r in rows)


def test_run_logs_attempt_selects_the_attempt_archive(github) -> None:
    rows, _ = _scan(
        RunLogsFunction, RunLogsArgs(repo="o/r", run_id=5, attempt=2), {"repo": ["o/r"], "run_id": [5]}
    )
    assert rows and all(r["attempt"] == 2 for r in rows)
    assert github[0].url.path == "/repos/o/r/actions/runs/5/attempts/2/logs"


def test_missing_expired_and_null_keys_yield_no_rows(github) -> None:
    rows, out = _scan(
        JobLogsFunction,
        JobLogsArgs(repo="o/r", job_id=0),
        {"repo": ["o/r", "o/r", None, "o/r"], "job_id": [404, 410, 7, None]},
    )
    assert rows == [] and out.more == [False]
    assert out.batches[0].schema == JobLogsFunction.FIXED_SCHEMA


def test_a_bad_archive_is_an_error(github) -> None:
    with pytest.raises(api.GitHubError, match="not a valid zip"):
        _scan(RunLogsFunction, RunLogsArgs(repo="o/r", run_id=6), {"repo": ["o/r"], "run_id": [6]})


def test_parents_line_up_across_several_inputs(github) -> None:
    rows, _ = _scan(
        JobLogsFunction,
        JobLogsArgs(repo="o/r", job_id=0),
        {"repo": ["o/r", "o/r", "o/r"], "job_id": [7, 404, 7]},
    )
    assert [r["_parent"] for r in rows] == [0] * 14 + [2] * 14
    # A repeated key reuses the spooled body: one API request, one blob request.
    assert sum(1 for r in github if r.url.path == "/repos/o/r/actions/jobs/7/logs") == 1
    assert sum(1 for r in github if r.url.host == "blob.example.test") == 1


@pytest.mark.parametrize("roundtrip", [False, True])
@pytest.mark.parametrize("cold", [False, True])
def test_small_batches_resume_exactly(github, monkeypatch, roundtrip: bool, cold: bool) -> None:
    whole, _ = _scan(RunLogsFunction, RunLogsArgs(repo="o/r", run_id=5), {"repo": ["o/r"], "run_id": [5]})
    monkeypatch.setattr(logs, "BATCH_LINES", 3)
    rows, out = _scan(
        RunLogsFunction,
        RunLogsArgs(repo="o/r", run_id=5),
        {"repo": ["o/r"], "run_id": [5]},
        roundtrip=roundtrip,
        cold=cold,
    )
    assert rows == whole
    assert len(out.batches) >= 5 and out.more[-1] is False and all(out.more[:-1])
    assert all(b.num_rows <= 3 for b in out.batches)
    assert len(logs.SPOOLS) == 0, "spooled logs are dropped once read"


def test_cancel_drops_spooled_bodies(github, monkeypatch) -> None:
    monkeypatch.setattr(logs, "BATCH_LINES", 2)
    params = _Params(args=JobLogsArgs(repo="o/r", job_id=7), output_schema=JobLogsFunction.FIXED_SCHEMA)
    state = JobLogsFunction.initial_state(params)
    out = _Out()
    JobLogsFunction.process(params, state, pa.record_batch({"repo": ["o/r"], "job_id": [7]}), out)
    assert out.more == [True] and len(logs.SPOOLS) == 1
    JobLogsFunction.on_cancel(params, state)
    assert len(logs.SPOOLS) == 0


def test_spools_are_anonymous_files() -> None:
    """A spooled log has no name to leak, so even a killed worker leaves nothing behind."""
    spool = logs.Spool()
    spool.file.write(b"line 1\nline 2\n")
    spool.file.flush()
    spool.size = spool.file.tell()
    if os.name == "posix":
        assert os.fstat(spool.file.fileno()).st_nlink == 0
    first, second = spool.open(), spool.open()
    assert first.readline() == b"line 1\n"
    assert second.readline() == b"line 1\n", "readers keep independent positions"
    second.seek(7)
    assert second.read() == b"line 2\n" and first.read() == b"line 2\n"


def test_download_streams_and_retries(monkeypatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(502)
        return httpx.Response(200, content=b"x" * 3_000_000)

    install(monkeypatch, handler)
    sink = io.BytesIO()
    assert api.download("/repos/o/r/actions/jobs/1/logs", sink)
    assert len(sink.getvalue()) == 3_000_000
    with pytest.raises(api.GitHubError, match="download limit"):
        api.download("/repos/o/r/actions/jobs/1/logs", io.BytesIO(), max_bytes=10)
    with pytest.raises(api.GitHubInputError):
        api.download("https://evil.example/x", io.BytesIO())


def test_fixture_archive_is_a_real_zip() -> None:
    names = zipfile.ZipFile(FIXTURES / "run_logs.zip").namelist()
    assert "0_build.txt" in names and "build/2_Run tests.txt" in names


# --------------------------------------------------------------------------
# Scalars
# --------------------------------------------------------------------------


def test_log_ts_scalar() -> None:
    result = LogTsFunction.compute(pa.array(["2026-07-21T12:00:00.5Z x", "nope", None]))
    assert result.to_pylist() == [datetime(2026, 7, 21, 12, 0, 0, 500000, tzinfo=UTC), None, None]


def test_log_text_scalar() -> None:
    line = "2026-07-21T12:00:00.1234567Z \x1b[31mred\x1b[0m"
    result = LogTextFunction.compute(pa.array([line, line, None, line]), pa.array([True, False, True, None]))
    assert result.to_pylist() == ["red", "\x1b[31mred\x1b[0m", None, None]


def test_workflow_command_scalar() -> None:
    result = WorkflowCommandFunction.compute(
        pa.array(["2026-07-21T12:00:00Z ::error file=a.py,line=1::boom", "plain", None, "##[group]G"])
    )
    values = result.to_pylist()
    assert values[0] == {
        "command": "error",
        "properties": [("file", "a.py"), ("line", "1")],
        "message": "boom",
    }
    assert values[1] is None and values[2] is None
    assert values[3] == {"command": "group", "properties": [], "message": "G"}


def test_an_empty_archive_yields_no_rows(github, monkeypatch) -> None:
    monkeypatch.setattr(logs, "_members_of", lambda path, archive: [])
    rows, out = _scan(RunLogsFunction, RunLogsArgs(repo="o/r", run_id=5), {"repo": ["o/r"], "run_id": [5]})
    assert rows == [] and out.more == [False]


def test_eviction_does_not_break_a_reader_in_use(github, monkeypatch) -> None:
    monkeypatch.setattr(logs, "BATCH_LINES", 5)
    params = _Params(args=JobLogsArgs(repo="o/r", job_id=7), output_schema=JobLogsFunction.FIXED_SCHEMA)
    state = JobLogsFunction.initial_state(params)
    out = _Out()
    JobLogsFunction.process(params, state, pa.record_batch({"repo": ["o/r"], "job_id": [7]}), out)
    reader = next(iter(logs.SPOOLS._readers.values()))
    logs.SPOOLS.clear()  # evicted under a concurrent scan's pressure
    assert reader.stream.closed
    while out.more[-1]:
        JobLogsFunction.resume(params, state, out)
    assert sum(b.num_rows for b in out.batches) == 14
    assert sum(1 for r in github if r.url.host == "blob.example.test") == 2
