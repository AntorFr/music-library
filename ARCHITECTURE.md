# Music Library — architecture

Music Library is a FastAPI + SQLite (SQLAlchemy async) family media library
with Jinja2 pages, an OIDC client (parent/child roles by owner tag), an
integration with Home Assistant's Music Assistant (MA), RFID tag assignment and
an ESP reader API. This file is the short map; it is written by the quality
epic (`music-library-qualite`) and decisions below are numbered `AD-n`.

## Organs

| Organ | Where | Holds |
|---|---|---|
| Entry and wiring | `app/main.py`, `app/server.py`, `app/config.py`, `app/database.py` | app factory, settings, `/health`, DB session |
| API and pages | `app/api/` | REST routes, quick/launcher API, server-rendered views (`views.py`) |
| Services | `app/services/` | MA client, import, media, tags, covers, select engine, RFID, auth, permissions, Spotify accounts |
| Models and schemas | `app/models/`, `app/schemas/` | persistence and API shapes |
| ESP | `app/esp_app.py` | embedded-reader API |
| Templates and static | `app/templates/`, `app/static/` | pages and components |

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

`README.md` (to create) and this file are the map. Decisions that still govern
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
is recorded as applied in `docs/quality/recommendations.md`.

### AD-7 — No deployment, release rule kept

The epic ends in `main` (image `:main` only). The production tag pinned in
`k8s-home-lab` is bumped manually by the owner. The version rule of `CLAUDE.md`
applies to any tag cut.

### AD-8 — Where the pass publishes

Three documents under `docs/quality/`: `coverage.md` (per-module coverage,
refreshed by the net slice; also lists the doubtful behaviours kept as they are), `security-review.md` (B-4), `recommendations.md`
(B-7). No other location.

### AD-reco-1 — The recommendations: one entry shape, closed sources, checked by script

`docs/quality/recommendations.md` is written last, from the finished documents,
and decides nothing: the owner arbitrates (P-2). It opens with a "How to read"
paragraph, a summary table (id, title, origin, recommendation, status), then
entries grouped by theme in this order: security, behaviour kept as found,
tooling and CI, documentation gaps, new functions. Within a theme, the entry the
owner should look at first comes first. A final section "Applied" holds the
critical fixes accepted under AD-6.

Each entry is `### R-n — title` with five fields: **Origin** (file and entry it
comes from), **Today** (the observable behaviour), **Options** (at least two,
"leave as is" being one), **Recommendation** (one option and why), **Status**
(`open`, or `applied` with the commit of the fix).

Closed list of sources, each swept in full so nothing is silently dropped:
the two sections "Comportements douteux conservés" and "Modules conservés" of
`docs/quality/coverage.md`; every non-critical finding of
`docs/quality/security-review.md` and every critical fix applied; the open
entries of `TODO.md`; pinning the Actions by SHA and a type checker (mypy),
named by AD-4 and the lint/CI slice; the known gaps between the historical
documents and the code listed by the doc slice. An entry may point to the
source (`see security-review.md, T-4`) instead of restating it, but it still
carries options and a recommendation.
*Rejected:* listing improvements from memory or from reading `app/` anew — the
sources are the record of what the pass saw, and a sweep by script proves none is missing.

### AD-reco-2 — `TODO.md` is emptied once, into the recommendations

The open entries of `TODO.md` (fuzzy search API, mobile quick launcher) become
"new functions" entries of the recommendations, each with its bullet points
kept as the description, never as scope. `TODO.md` then keeps its title, its
intro line and its `## Livré` heading with no `###` entry under `## En attente`
and a one-line pointer to `docs/quality/recommendations.md`.
*Rejected:* leaving them in both places — two backlogs drift apart.

## Known gaps (inputs of the pass)

No README, no ADR directory; no CI runs the tests (the only workflow builds the
image); 14 test files (2514 lines) exist but coverage is unmeasured (122 tests pass on main at v0.26.0, measured by Skippy,
2026-11-05; `ruff check` reports 148 errors then); `views.py` (1179 lines) and `music_assistant.py` (990)
dominate; `docs/PLAN.md` is a six-phase plan from before v0.1; `TODO.md` holds
backlog items to move to the recommendations.
