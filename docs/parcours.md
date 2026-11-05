# Quality pass — who it serves, needs, journeys

> Epic `music-library-qualite`. A quality pass: Music Library (`app/`: API,
> Music Assistant services, RFID, Spotify accounts, auth and permissions, web
> UI, `esp_app`) is brought to the standard of the SDLC chain **without any
> functional change**, then a list of recommendations is written for the owner
> to arbitrate. This file is the epic's frame; it replaces no product document.

## For whom

- **A pod of the chain** that must take a feature on Music Library reading the
  repository alone (README, `ARCHITECTURE.md`, ADRs, tests, CI).
- **The owner (Monsieur)**, who arbitrates the recommendations and keeps the
  deployment: production runs the pinned tag `0.26.0` in `k8s-home-lab`;
  bumping it stays manual.
- **The family using the house instance** (parents, children, tablets, ESP
  readers), for whom nothing may change.

## Needs

| Id | Need | Proof |
|---|---|---|
| B-1 | Observable behaviour is unchanged: web pages, REST API, `/health`, the Music Assistant integration, the ESP/RFID API, auth and permissions, stored data and migrations, configuration and environment. | Characterization tests (B-2) green before and after every refactoring. |
| B-2 | A characterization net exists **before** any refactoring, at the observable edges (HTTP pages and API, MA client boundary with a stub, permissions by owner tag, Spotify account pinning, RFID/ESP, cover handling, startup/migrations). The 14 existing test files are run, kept, and their gaps measured. | Coverage is measured and published per module in `docs/quality/coverage.md` (AD-8); each area listed has a test that fails if its behaviour changes. |
| B-3 | The documentation is right and short: a `README.md` (none exists today), a root `ARCHITECTURE.md` with numbered decisions, ADRs for the decisions that still govern the code, `.agent/status.md` reduced to a current status, and `docs/PLAN.md`, `REQUIREMENTS.md`, `AUTH.md`, `AGENTS.md` and `.github/copilot-instructions.md` confronted with the code (corrected, marked historical, or removed when duplicated). | Every link resolves; a reader finds roles, boundaries, how to build, test and release in the README and `ARCHITECTURE.md` alone; no statement in the docs contradicts the code. |
| B-4 | A threat-first security review of: accounts and permissions by owner tag (OIDC claims, groups, accent/case normalisation), Spotify accounts (pinning, credentials), the ESP/RFID API and machine-caller token, HTTP inputs (uploads, covers, HTML templates), outbound calls to Music Assistant, logs. | A written report by threat, `docs/quality/security-review.md` (AD-8); each finding is classified: fixed without behaviour change, recommendation (B-7), or critical (AD-6). |
| B-5 | Refactoring and reuse where the code costs to live with: the largest modules (`app/api/views.py` 1179 lines, `app/services/music_assistant.py` 990, `app/services/media_service.py` 578), the duplicated `get_library_*` methods and `/library/<type>` routes, dead branches in templates noted in `.agent/status.md`. | Each change is covered by B-2 tests; the suite is green before and after. |
| B-6 | CI validates what the repo claims: lint (`ruff`) and the test suite on every PR, in addition to the image build, which stays as is. | A deliberately broken PR is red. |
| B-7 | The recommendations are written in `docs/quality/recommendations.md` (AD-8): every improvement that changes behaviour, found along the way (the open items of `TODO.md` are moved there once, and `TODO.md` is then emptied of them), with options and a recommendation. | One document, ordered, ready for the owner. |
| B-8 | The release rule of `CLAUDE.md` (version in `pyproject.toml` and `app/config.py` equal to the tag, bumped in the tagged commit) is kept and stated in the README. | The README links it; no slice changes the version without the rule. |

## Journeys

- **P-1 — A pod takes a feature.** It reads the README, then `ARCHITECTURE.md`,
  finds the modules and boundaries, installs and tests, adds its change, and CI
  tells it if it broke something. Serves B-2, B-3, B-6, B-8.
- **P-2 — The owner arbitrates.** He opens `docs/quality/recommendations.md`,
  decides each (do, later, never) in the discussion of the epic's last slice, where the chain turns the accepted ones into new epics or features; nothing in them was applied, except a
  critical fix he accepted under AD-6, which the document then records as
  applied. Serves B-4, B-7.
- **P-3 — The house instance goes on.** Production stays on the pinned tag; a
  merge produces the `:main` image only, not deployed. Serves B-1.
- **P-4 — A refactoring lands.** A change in `views.py`, `music_assistant.py` or
  `media_service.py` is made under the characterization tests, then merged by
  the chain. Serves B-1, B-2, B-5.

No journey involves a new screen: the pages keep their look and behaviour (no
`E-n`, no maquette, no `docs/donnees.md`; the schema and the data are
untouched).

## Out of scope

- Any functional change: it goes to the recommendations (B-7).
- Deployment: no bump of the tag pinned in `k8s-home-lab`
  (`clusters/homenode/home/music`), no change to the chart
  `smart-home-charts/charts/music-library`.
- New features (fuzzy search, etc., from `TODO.md`): recommendations only.
