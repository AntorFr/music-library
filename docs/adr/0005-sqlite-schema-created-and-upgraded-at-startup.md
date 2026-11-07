# ADR-0005 — SQLite, schema created and upgraded in `init_db`

## Context

A single-container, single-family application: one writer, small data, a
volume to back up. The schema needs to evolve without a manual step.

## Decision

The database is SQLite through SQLAlchemy async (`app/database.py`,
`database_url`). At startup the lifespan calls `init_db`, which runs
`Base.metadata.create_all` and then a short hand-written step for each added
column (today `tag_categories.color`, through `ALTER TABLE`), since `create_all`
does not add columns. Models live in `app/models/`.

## Rejected

- A client/server database: operational weight for no gain at this size.
- Alembic migrations: `alembic` is a dependency, but the repository holds no
  migration and none is run. An earlier draft of the decision list named them;
  the code does not show them, so they are not part of this decision.

## Consequences

- Every schema change that is not a new table needs an explicit step in
  `init_db`, written to be idempotent; renames and drops are not supported.
- Startup is the only migration moment; there is no downgrade.
- If Alembic is adopted later, this ADR is superseded by a new one.
