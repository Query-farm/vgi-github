# vgi-github — common tasks.
#
#   make test-unit    # offline pytest suite (live tests excluded)
#   make test-sql     # SQL sqllogictest (test/sql) over stdio, launch and http
#   make test-sql TRANSPORTS=launch   # ...over the listed transports only
#   make test         # unit + SQL
#   make lint         # ruff

# SQL tests run test/sql/*.test through the published haybarn-unittest with the
# signed community vgi extension (ci/run-integration.sh; no local DuckDB/vgi
# builds). test/sql/mock_api.test runs against test/mock_api/server.py.
HAYBARN_VERSION ?= 2.0.1rc3
WORKER          := $(CURDIR)/.venv/bin/vgi-github
TOOLS           := $(CURDIR)/.tools
HAYBARN_UNITTEST := $(TOOLS)/bin/haybarn-unittest
TRANSPORTS      ?= stdio launch http

.PHONY: build tools lint test test-unit test-sql check

build:
	uv sync --all-extras

tools:
	@test -x $(HAYBARN_UNITTEST) || { uv venv -q $(TOOLS) && uv pip install -q -p $(TOOLS) haybarn-unittest==$(HAYBARN_VERSION); }

lint: build
	uv run ruff check .
	uv run ruff format --check .

test-unit: build
	uv run pytest -q

test-sql: build tools
	@for t in $(TRANSPORTS); do \
		WORKER=$(WORKER) HAYBARN_UNITTEST=$(HAYBARN_UNITTEST) TRANSPORT=$$t PYTHON=$(CURDIR)/.venv/bin/python \
			ci/run-integration.sh || exit 1; \
	done

test: test-unit test-sql

check: lint test
