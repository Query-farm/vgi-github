# GitHub semantic model development

Read `DEVELOPMENT.md#semantic-model-contributions` before changing the generated
semantic profile. Model domains live in `generation/domains/`; their entrypoint
is `generation/pilot.json`. Edit those sources, not generated package files.
Keep source grain, actor roles and relationships explicit. Existing Crossfield
schemas and native compilation own expression and policy validation.

The Crossfield checkout's `./dev` command owns EC2 sync, generation and test
commands; its `.dev.env` records the current host. Use `./dev --help` and
Crossfield's `docs/TESTING.md` rather than reconstructing commands from chat.
Edit locally; build and test on EC2. Keep one owner for final sync and integration.

Executable researcher SQL lives in `generation/examples/research/*.sql`.
Generation includes it in the runnable SQL, guide and standard SQLLogicTests.
Maintain independent expected answers in the `.test.in` template. Preserve
DuckDB's normal runner and comparison behavior. Reuse passing checks for
unchanged code; document the affected contract without creating a new report.
