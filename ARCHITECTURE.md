# Music Library — architecture

Music Library is a FastAPI + SQLite (SQLAlchemy async) family media library
with Jinja2 pages, an OIDC client (parent/child roles by owner tag), an
integration with Home Assistant's Music Assistant (MA), RFID tag assignment and
an ESP reader API. This file is the short map; it is written by the quality
epic (`music-library-qualite`) and decisions below are numbered `AD-n`.

## Organs

| Organ | Where | Holds |
|---|---|---|
| Entry and wiring | `app/__init__.py`, `app/main.py`, `app/server.py`, `app/config.py`, `app/database.py` | app factory, two-port runner, settings, DB session (health: `app/api/system.py`, `/api/v1/health`) |
| API and pages | `app/api/` (`__init__.py`, `auth.py`, `covers.py`, `media.py`, `music_assistant.py`, `quick.py`, `rfid.py`, `system.py`, `tags.py`) | REST routes, quick/launcher API, login routes |
| Views | `app/api/views/` (package: `__init__.py`, `shared.py`, `listen.py`, `media.py`, `media_items.py`, `settings.py`, `browse.py`) | server-rendered pages; `__init__.py` exposes the one `router` |
| Services | `app/services/` (`__init__.py`, `music_assistant.py`, `ma_models.py`, `ma_helpers.py`, `ma_import.py`, `media_service.py`, `media_tags.py`, `media_selection.py`, `tag_service.py`, `cover_service.py`, `select_engine.py`, `rfid_service.py`, `auth_service.py`, `permissions.py`, `spotify_accounts.py`) | MA client (data classes in `ma_models`, pure helpers in `ma_helpers`), import, media (tags in `media_tags`, query selection in `media_selection`), tags, covers, select engine, RFID, auth, permissions, Spotify accounts |
| Models and schemas | `app/models/` (`__init__.py`, `media.py`, `rfid.py`), `app/schemas/` (`__init__.py`, `media.py`, `rfid.py`) | persistence and API shapes |
| ESP | `app/esp_app.py` | embedded-reader API |
| Templates and static | `app/templates/`, `app/static/` | pages and components |

## Durable decisions

Decisions that still govern the code, each restated as an ADR in
[`docs/adr/`](docs/adr/) (numbered independently of `AD-n`).

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-oidc-parent-child-roles-and-open-dev-mode.md) | OIDC login, parent/child roles by owner tag, open dev mode |
| [0002](docs/adr/0002-static-bearer-token-for-machine-calls.md) | A static bearer token for machine callers |
| [0003](docs/adr/0003-music-assistant-plays-and-pins-spotify-accounts.md) | Music Assistant is the source of playback; Spotify lists pinned by `source_uri` |
| [0004](docs/adr/0004-signed-thumbnail-proxy.md) | Thumbnails go through a signed, cached proxy |
| [0005](docs/adr/0005-sqlite-schema-created-and-upgraded-at-startup.md) | SQLite, schema created and upgraded in `init_db` (no Alembic migration exists) |
| [0006](docs/adr/0006-separate-esp-port.md) | The embedded reader API is served on its own port |
| [0007](docs/adr/0007-shared-in-flight-ma-calls-and-keepalive.md) | Identical MA calls are shared; slow answers are kept alive |

## Decisions of the quality pass

### AD-1 — No functional change; deviations become recommendations

The pass preserves observable behaviour. Anything that would change it (a bug
fix users could notice, a hardening that rejects an input accepted today) is
written in the recommendations, not applied.
*Rejected:* fixing as we go — it would void the proof that behaviour is
unchanged. *Exception:* see AD-6.

### AD-2 — Characterization tests at the edges, before refactoring

Tests pin HTTP pages and API, the MA boundary (stubbed), permissions, stored
data and startup, not internal functions, so that refactoring can move code
freely. Slice order follows: net first, then review and refactoring. The 14
existing test files are the base of the net, not a substitute for it.
*Rejected:* unit tests of internals — they freeze the structure we want to change.

### AD-3 — Documentation: one map, ADRs, a short status

`README.md` and this file are the map. Decisions that still govern
the code are restated as ADRs (`docs/adr/NNNN-title.md`, ADR-0001…,
independent of `AD-n`; sections: Context, Decision, Rejected, Consequences).
`docs/PLAN.md` and `REQUIREMENTS.md`, written before the code, are corrected
against it or marked historical; `AGENTS.md` stays the link to `CLAUDE.md`, and
`.github/copilot-instructions.md` becomes a pointer, not a copy.
`.agent/status.md` is cut to a current status. Docs are in English, as the repo.
*Rejected:* rewriting history documents — they are cut or marked, not redone.

### AD-4 — CI extends the existing workflow set

`docker-publish.yml` stays the image build. A new workflow `ci.yml` runs ruff
and pytest on every PR to `main`. Actions stay pinned by major tag (pinning by
SHA goes to the recommendations).
*Rejected:* adding tests to `docker-publish.yml` — it also publishes images, and
a test job there would gate releases and mix concerns.

### AD-5 — Refactoring only under the net, behaviour read from the tests

A module is split or deduplicated only where a B-2 test covers its observable
behaviour first. Public routes, response shapes, template output and DB schema
do not move. Alembic migrations are not rewritten.
*Rejected:* a global rewrite of `views.py` or the MA client.

### AD-6 — A critical exploitable finding is not held for the end

The security review is threat-first. A finding is *critical* when a party with
no valid session or token can exploit it, when a child can read or write
another owner's media, or when a Spotify credential can leak. It is escalated
as soon as found by `pilote arbitrer` on the review slice, with its fix
proposed: the owner decides. A fix he accepts is the one exception to AD-1 and
is recorded as applied in `docs/quality/security-review.md` by the review slice,
and carried into `docs/quality/recommendations.md` by the recommendations slice
(the file's only owner).

### AD-7 — No deployment, release rule kept

The epic ends in `main` (image `:main` only). The production tag pinned in
`k8s-home-lab` is bumped manually by the owner. The version rule of `CLAUDE.md`
applies to any tag cut.

### AD-8 — Where the pass publishes

Three documents under `docs/quality/`: `coverage.md` (per-module coverage,
refreshed by the net slice; also lists the doubtful behaviours kept as they are), `security-review.md` (B-4), `recommendations.md`
(B-7). No other location, with one transient exception: the net slice's test tasks leave
fragments `docs/quality/douteux/<task>.md`, which its coverage task merges into `coverage.md`
and deletes (none remains once the slice is done).

### AD-securite-1 — Security review: threat table first, one classified finding per row

The report `docs/quality/security-review.md` opens with a threat table, written
before reading the code in depth: for each threat family (owner-tag accounts
and permissions; Spotify accounts; ESP/RFID API and machine-caller token; HTTP
inputs — uploads, covers, templates; outbound calls to Music Assistant; logs)
it names who attacks, through which entry point (a route, a header, a claim, a
file), and what is at stake. Each row then points to the code read and ends in
findings. A finding carries: an identifier `S-n`, the threat, the evidence
(file and route, never a real secret or identifier — the repository is
public), and one class: *fixed without behaviour change*, *recommendation*
(B-7, AD-1: a hardening that rejects an input accepted today is one), or
*critical* (AD-6). A critical finding stops the task: it is written in the
report with its proposed fix, escalated by `pilote arbitrer` on this slice, and
the slice stays open until the owner answers; his answer is written in the
report. The task stops after escalating; the pod that resumes it reads the
answer in the slice's discussion and copies it into the report before going on.
The report also cites, for each sensitive module it reads, its measured coverage
in `docs/quality/coverage.md`. An accepted fix is applied under a test that fails without it; a
refusal reclassifies the finding as a recommendation. Where a threat family has
no finding, the row says what was checked. Two tasks, chained because the
report has one owner: identity (accounts, permissions, ESP/RFID) then
surfaces (Spotify, inputs, outbound calls, logs).
*Rejected:* a review by file (it hides what no file owns, e.g. a missing check);
holding criticals to the end (AD-6); fixing non-critical findings in passing
(AD-1).

### AD-refactoring-1 — Cut by responsibility, keep every import path and patch target

A split keeps the old module as the public face: the names callers import
(`from app.services.music_assistant import MusicAssistantClient, get_ma_client,
resolve_ma_provider_and_id`; `from app.services import media_service`; the
`router` of `app.api.views`) still resolve there, by re-export or because they
stay in place. `get_ma_client` and `close_ma_client` stay *defined* in
`app/services/music_assistant.py`: tests patch
`app.services.music_assistant.get_ma_client`. New files only hold what moved.
`app/api/views.py` becomes the package `app/api/views/` (`__init__.py` exposes
the same `router`); route paths, methods and registration order are unchanged.
Before each cut the task records the line count and the net test that covers
the module; a module with no such test is not touched and is listed under
"Modules conservés" in `docs/quality/coverage.md`.
*Rejected:* renaming public functions to fit the new layout (callers and patch
targets move); moving `get_ma_client` with the client class (breaks the
existing monkeypatches).

### AD-doc-1 — The docs are written from the final code, and checked by script

Slice `music-library-qualite-doc` runs after the refactoring: every list in the
docs is read from the code as it is then, never from an older document. Sources:
environment variables = the fields of `Settings` in `app/config.py` (prefix
`ML_`, upper-cased) plus any `os.environ` read in `app/`; CI commands = the
`run:` steps of `.github/workflows/ci.yml`; modules = the files of `app/`.
Each task states in its review the check it ran (variable ↔ README table,
module ↔ `ARCHITECTURE.md`, relative links resolved). A statement the code does
not confirm is dropped, not softened.
*Rejected:* editing the old documents in place from memory — they are the ones
that drifted.

### AD-doc-2 — What survives of the old documents

`ARCHITECTURE.md` gets a section « Durable decisions » listing the decisions
that still govern the final code, and `docs/adr/` holds exactly one ADR per
entry (`NNNN-title.md`, from `0001`; Context, Decision, Rejected,
Consequences). Candidates, each kept only if the code still shows it: OIDC
client with parent/child roles by owner tag and the open dev mode; the static
bearer token for machine calls; Music Assistant as the source of playback and
its Spotify account pinning by `source_uri`; the signed thumbnail proxy; SQLite
schema created and upgraded at startup (no Alembic; ADR 0005); the separate ESP port; shared in-flight
Music Assistant commands and the `keepalive` page. `.agent/status.md` keeps
the current version, the open checks that are still open and the pointer to
`docs/quality/recommendations.md`; the version-by-version history goes (git
holds it). `docs/PLAN.md` and `docs/REQUIREMENTS.md` get a historical banner and
a short list of known divergences from the code, nothing rewritten;
`docs/AUTH.md` is corrected against `app/services/auth_service.py` and
`permissions.py`. `docs/MUSIC_ASSISTANT_COMPATIBILITY.md` is not in the pass.
*Rejected:* rewriting `PLAN.md` — AD-3 says cut or mark.

## Known gaps (inputs of the pass)

State at the start of the pass (the README and `docs/adr/` since exist); the 14 original test files (122 tests) are now completed by the
net slice (67 % line coverage, per module in `docs/quality/coverage.md`); `ruff check` is clean
(lint slice) and `.github/workflows/ci.yml` runs `ruff check .` and `pytest` on every pull
request to `main` ; the refactoring slice cut `views.py` (1188 lines, now a package), `music_assistant.py` (999 → 729) and `media_service.py` (→ 331); `docs/PLAN.md` is a six-phase plan from before v0.1; `TODO.md` holds
backlog items to move to the recommendations.

### AD-lint-ci-1 — Lint fixes: safe fixes only, one ignore per reason, CI last

Applies to the `music-library-qualite-lint-ci` slice (extends AD-4).

- **Count first.** The task re-runs `ruff check` at its start (148 errors at
  v0.26.0; 169 at the start of the task on ruff 0.17.3, the net having added tests) and records the count in its
  commit message.
- **Order.** `ruff check --fix` (safe fixes only, never `--unsafe-fixes`), then the
  rest by hand, file by file. A fix that could change behaviour (changing an
  exception chain with `raise ... from`, merging branches, reordering imports with
  side effects) is made only if a test of the net covers the code; otherwise it is
  ignored with a per-line `# noqa: <code> — <reason>` or, for a file-wide case, a
  `per-file-ignores` entry with a comment. The rule set `E, F, I, UP, B, SIM` and
  `line-length = 100` are never loosened; no rule family is removed.
- **Behaviour check.** The full suite (the 122 existing tests and the net) runs
  green after the autofix and again at the end; no test file is modified except
  for lint fixes in it, and no assertion changes.
- **CI after green.** `ci.yml` is written only once `ruff check` is clean on the
  slice branch, so the first PR that runs it is green. One job, Python 3.12
  (`requires-python >=3.12`; the image's version is the reference), `pip install
  -e '.[dev]'`, then `ruff check .` and `pytest` as separate steps, triggered by
  `pull_request` to `main`. No `continue-on-error`, no `|| true`. Actions pinned by
  major tag (AD-4).
- **Untouched.** `docker-publish.yml`, `version` in `pyproject.toml`, `app_version`
  in `app/config.py` (AD-7).
*Rejected:* `ruff format` (would rewrite every file, outside B-6); adding mypy or
widening the rule set (recommendations); a matrix of Python versions (the image
fixes one).

## Net slice (`music-library-qualite-filet`)

### AD-filet-1 — Test conventions of the net

New tests live in `tests/`, one file per domain, in the style of `tests/test_nav_v2.py`:
a temporary SQLite file engine, `Base.metadata.create_all`, `seed_default_tags`,
`get_db` overridden, `httpx.AsyncClient` on `ASGITransport(app)`. Music Assistant is
always behind a stub (no network); the real `app.main.app` is used, no private
import of a service is tested (AD-2). Existing test files are not edited. A test
pins what the code does at v0.26.0; a doubtful behaviour is pinned as is and
listed in `docs/quality/coverage.md` under « Comportements douteux conservés »
(test, finding, origin). Each test task writes its doubtful findings in its own fragment
`docs/quality/douteux/<task>.md`; the coverage task merges them into `coverage.md` and deletes them.

Startup tests: `init_db` uses the module-global `app.database.engine`, so a startup test
replaces `engine` and `async_session` with ones on the sample database through
`monkeypatch.setattr` on `app.database` only (`app.main` has no module-level `engine`
or `async_session`: it imports `init_db` and, inside the lifespan, `async_session` from
`app.database`, so the patch is seen), and stubs Music Assistant before the lifespan runs.

### AD-filet-2 — The schema evolves in `init_db`, not in Alembic

The repository holds no Alembic migration: `alembic` is a dependency, but the
schema is created by `create_all` and upgraded by the one hand-written step of
`app/database.py::init_db` (`tag_categories.color`). The net's « startup and
migrations » domain therefore pins `init_db` and the app lifespan on a sample
database in the previous schema (a `tag_categories` without `color`), and on an
empty one. The absence of Alembic migrations is listed in « Comportements
douteux conservés » as a finding for the recommendations slice. (AD-5 above says
« Alembic migrations are not rewritten »: there are none; the rule stands for
any that appear.)
