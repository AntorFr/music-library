# Recommendations — Music Library

## How to read

Written last, from the finished reports of the quality pass (`docs/quality/coverage.md`, `docs/quality/security-review.md`, the banners of `docs/PLAN.md` and `docs/REQUIREMENTS.md`, and the Actions/mypy points of AD-4). It decides nothing: each entry describes, lists options and proposes one; the owner arbitrates. Entries are grouped by theme (security, behaviour kept as found, tooling and CI, documentation gaps, new functions), the one to look at first coming first. `open` means awaiting the owner's choice; `applied` carries the commit of the fix. A recommendation of a new function is never in scope. Sources: the "Modules conservés" section of `coverage.md` is "Aucun", so it gives no entry; both banners list gaps, all entered below. The open entries of `TODO.md` are entered in "New functions" (R-41, R-42) and `TODO.md` no longer lists them.

## Summary

| Id | Title | Origin | Recommendation | Status |
|---|---|---|---|---|
| R-1 | The ESP port has no authentication | `docs/quality/security-review.md`, S-9 | Option 2 with the note of option 3 | open |
| R-2 | A media `cover_url` makes the server fetch any URL | `docs/quality/security-review.md`, S-15 | Option 2 | open |
| R-3 | Role and groups live in the session cookie for 30 days | `docs/quality/security-review.md`, S-3 | Option 2 | open |
| R-4 | OIDC is all-or-nothing and fails open | `docs/quality/security-review.md`, S-4 | Option 2 | open |
| R-5 | The machine token is one static, all-powerful secret | `docs/quality/security-review.md`, S-10 | Option 2 | open |
| R-6 | `/covers/<media_id>.jpg` is served without a session | `docs/quality/security-review.md`, S-7 | Option 1 | open |
| R-7 | A child can drive every player and browse the whole MA library | `docs/quality/security-review.md`, S-8 | Option 1 | open |
| R-8 | No size limit on uploads or downloaded covers | `docs/quality/security-review.md`, S-16 | Option 2 with a generous bound (several MB) | open |
| R-9 | Music Assistant error text is relayed to callers and pages | `docs/quality/security-review.md`, S-18 | Option 2 | open |
| R-10 | MA `last_error` text is shown on the parent's pages | `docs/quality/security-review.md`, S-14 | Option 1 | open |
| R-11 | Plaintext transport to Music Assistant over `http://` | `docs/quality/security-review.md`, S-19 | Option 2 | open |
| R-12 | URLs are logged on image failures and at MA connect | `docs/quality/security-review.md`, S-20 | Option 2 | open |
| R-13 | The username is logged at each login | `docs/quality/security-review.md`, S-21 | Option 1 | open |
| R-14 | Identity keys are loose | `docs/quality/security-review.md`, S-5 | Option 2 | open |
| R-15 | `GET /auth/logout` is a GET | `docs/quality/security-review.md`, S-6 | Option 1 | open |
| R-16 | Remote thumbnails are resized by a third-party service | `docs/quality/security-review.md`, S-17 | Option 3 | open |
| R-17 | The default cover path is relative to the working directory | `docs/quality/coverage.md`, `tests/test_covers_api.py::test_missing_cover_with_a_relative_default_path_is_a_500` | Option 2 | open |
| R-18 | An unknown `media_type` on `/media` is a 500 | `docs/quality/coverage.md`, `tests/test_pages_views.py::test_media_list_with_an_unknown_media_type_is_a_500` | Option 2 (422) | open |
| R-19 | `/browse/library/{type}` validates the type only once MA answers | `docs/quality/coverage.md`, `tests/test_pages_views.py::test_browse_library_unknown_type_with_ma_down_is_a_200` | Option 2. | open |
| R-20 | `/health/ma` is not exempt from authentication | `docs/quality/coverage.md`, `tests/test_health.py::test_health_has_no_unprefixed_alias` | Option 2 | open |
| R-21 | Deleting a category that still has tags is a 500 | `docs/quality/coverage.md`, `tests/test_api_tags.py::test_delete_category_that_still_has_tags_fails_with_500` | Option 3 | open |
| R-22 | A category colour is stored in lower case | `docs/quality/coverage.md`, `tests/test_api_tags.py::test_create_category_answers_201_then_409_on_duplicate` | Option 1 | open |
| R-23 | `GET /api/v1/ma/search` has no error mapping | `docs/quality/coverage.md`, `tests/test_api_ma.py::test_search_ma_failure_is_not_caught` | Option 2 (see R-9 for the message text). | open |
| R-24 | A child's hard delete of another's media answers 404 | `docs/quality/coverage.md`, `tests/test_api_permissions.py::test_child_delete_of_others_media_is_404_even_when_hard` | Option 1. | open |
| R-25 | A malformed RFID UID on write gives a 500 | `docs/quality/coverage.md`, `tests/test_rfid_api.py::test_put_with_a_malformed_uid_answers_500_and_stores_nothing` | Option 2. | open |
| R-26 | The ESP guard is wider than what it protects | `docs/quality/coverage.md`, `tests/test_esp_boundary.py::test_a_media_path_ending_in_cover_is_guarded_whatever_its_middle` | Option 1 | open |
| R-27 | The Spotify account fragment is served for any media | `docs/quality/coverage.md`, `tests/test_spotify_pin_api.py::test_fragment_for_a_non_spotify_media_still_renders` | Option 2. | open |
| R-28 | No Alembic migration: the schema evolves in `init_db` | `docs/quality/coverage.md`, `tests/test_startup.py::test_no_alembic_version_table_is_ever_created` | Option 2 before the next schema change; none is needed until then. | open |
| R-29 | Pin the GitHub Actions by commit SHA | AD-4 and the lint/CI slice (`ARCHITECTURE.md`) | Option 3 | open |
| R-30 | Add a type checker (mypy) | AD-4 and the lint/CI slice (`ARCHITECTURE.md`) | Option 2 | open |
| R-31 | Historical documents: aucune migration Alembic ni `alembic.ini` | `docs/PLAN.md` and `docs/REQUIREMENTS.md`, banner gap: aucune migration Alembic ni `alembic.ini` : le schéma évolue dans `init_db` (`app/database.py`) | Option 1 | open |
| R-32 | Historical documents: l'authentification existe | `docs/PLAN.md` and `docs/REQUIREMENTS.md`, banner gap: l'authentification existe : client OIDC depuis v0.18.0, rôles parent / enfant (voir `docs/AUTH.md`) | Option 1 | open |
| R-33 | Historical documents: le serveur sert aussi une API ESP dédiée sur le port 8001 | `docs/PLAN.md` and `docs/REQUIREMENTS.md`, banner gap: le serveur sert aussi une API ESP dédiée sur le port 8001 (`app/esp_app.py`) | Option 1 | open |
| R-34 | Historical documents: `app/api/views.py` est devenu le paquet `app/api/views/` | `docs/PLAN.md` and `docs/REQUIREMENTS.md`, banner gap: `app/api/views.py` est devenu le paquet `app/api/views/` | Option 1 | open |
| R-35 | Historical documents: « pas d'auth » and « multi-utilisateurs hors périmètre » are outdated | `docs/REQUIREMENTS.md`, banner gap: « pas d'auth » et « multi-utilisateurs hors périmètre » (§2, §8, hors périmètre) sont dépassés par l'authentification OIDC | Option 1. | open |
| R-36 | Historical documents: the §7 tree no longer matches the repository | `docs/REQUIREMENTS.md`, banner gap: l'arborescence du §7 (dossier `migrations/`, `ha_integration.md`, noms des fichiers de tests) ne correspond plus au dépôt | Option 1. | open |
| R-41 | Natural-language fuzzy search API (new function) | `TODO.md`, 1. API de recherche floue en langage naturel | Option 2 | open |
| R-42 | Mobile quick launcher for iPad / iPhone (new function) | `TODO.md`, 2. Interface mobile « lanceur rapide » (iPad / iPhone) | Option 2 | open |
| R-37 | A child read other owners' media through the RFID read routes | `docs/quality/security-review.md`, S-1 (critical) | done | applied |
| R-38 | A child's title or source URI ran script in a parent's browser | `docs/quality/security-review.md`, S-13 (critical) | done | applied |
| R-39 | A non-ASCII bearer value gave an unauthenticated 500 | `docs/quality/security-review.md`, S-2 (fixed) | done | applied |
| R-40 | A non-ASCII `sig` on `/api/v1/quick/thumb` gave an unauthenticated 500 | `docs/quality/security-review.md`, S-12 (fixed) | done | applied |

## Security

### R-1 — The ESP port has no authentication

- **Origin**: `docs/quality/security-review.md`, S-9
- **Today**: Anyone reaching port 8001 acts as a parent: reads each owner's favourites, covers and episode lists, and drives every player.
- **Options**: (1) Leave as is (network placement, documented in `docs/AUTH.md`). (2) Add an optional `ML_ESP_TOKEN` (empty = today's behaviour). (3) Keep 8001 off public routes by a deployment note only.
- **Recommendation**: Option 2 with the note of option 3: it closes the exposure without changing calls while the setting is empty.
- **Status**: open

### R-2 — A media `cover_url` makes the server fetch any URL

- **Origin**: `docs/quality/security-review.md`, S-15
- **Today**: A user who can create or edit a media sets a `cover_url` the server fetches with redirects and no scheme or host filter (blind SSRF, also on the session-less cover route).
- **Options**: (1) Leave as is. (2) Restrict schemes to http/https and refuse private ranges. (3) Restrict by an operator allow-list of hosts.
- **Recommendation**: Option 2: the common case (public cover hosts) is unchanged; it rejects only internal addresses.
- **Status**: open

### R-3 — Role and groups live in the session cookie for 30 days

- **Origin**: `docs/quality/security-review.md`, S-3
- **Today**: A demoted parent keeps parent rights until the next login, up to 30 days.
- **Options**: (1) Leave as is. (2) Shorten `max_age`. (3) Re-derive the role from the IdP on a server-side check.
- **Recommendation**: Option 2: smallest change; option 3 only if demotions must be immediate.
- **Status**: open

### R-4 — OIDC is all-or-nothing and fails open

- **Origin**: `docs/quality/security-review.md`, S-4
- **Today**: With one of the four `oidc_*` settings missing the app runs in dev mode: no login, everyone parent, bearer token ignored.
- **Options**: (1) Leave as is. (2) Log a warning at startup for a partial configuration. (3) Refuse to start on a partial configuration.
- **Recommendation**: Option 2: no start is refused; the misconfiguration becomes visible.
- **Status**: open

### R-5 — The machine token is one static, all-powerful secret

- **Origin**: `docs/quality/security-review.md`, S-10
- **Today**: One bearer value gives parent rights on the whole main app, never expires, and is not logged with its caller.
- **Options**: (1) Leave as is (rotation is a redeploy). (2) Document rotation and keep it as is. (3) Scoped tokens (would be a new function, outside the pass).
- **Recommendation**: Option 2: documentation only; scoped tokens are not proposed as scope.
- **Status**: open

### R-6 — `/covers/<media_id>.jpg` is served without a session

- **Origin**: `docs/quality/security-review.md`, S-7
- **Today**: Any holder of a media id reads that cover, and the first request for a missing file triggers a download and resized variants (bounded).
- **Options**: (1) Leave as is (ESP and Home Assistant clients need it). (2) Require a session except on the ESP port. (3) Sign cover URLs like the thumbnail proxy.
- **Recommendation**: Option 1: the harm is low and the clients depend on it; revisit with R-1.
- **Status**: open

### R-7 — A child can drive every player and browse the whole MA library

- **Origin**: `docs/quality/security-review.md`, S-8
- **Today**: `/api/v1/ma/*` has no per-media check; imports are stamped with the child's owner tag.
- **Options**: (1) Leave as is (controlling the speaker is the purpose). (2) Scope the browse and search results to the child's tags. (3) Restrict players per profile.
- **Recommendation**: Option 1: scoping changes accepted calls and the product purpose.
- **Status**: open

### R-8 — No size limit on uploads or downloaded covers

- **Origin**: `docs/quality/security-review.md`, S-16
- **Today**: `upload_cover` and the cover download read the whole body in memory.
- **Options**: (1) Leave as is. (2) Cap upload and download sizes (reject above a bound). (3) Cap through the reverse proxy only.
- **Recommendation**: Option 2 with a generous bound (several MB): realistic covers are unaffected.
- **Status**: open

### R-9 — Music Assistant error text is relayed to callers and pages

- **Origin**: `docs/quality/security-review.md`, S-18; `tests/test_pages_views.py::test_browse_search_with_ma_down_reports_the_error_inline`
- **Today**: `/api/v1/ma/*` answers with the raw exception text; `GET /browse/search` writes it unescaped into HTML (answer 200). Markup in toasts is neutralised by the S-13 fix.
- **Options**: (1) Leave as is. (2) Answer a constant message and log the detail. (3) Keep the text but escape it in `browse_search`.
- **Recommendation**: Option 2: no secret leaks today, but wording and hosts need not reach clients.
- **Status**: open

### R-10 — MA `last_error` text is shown on the parent's pages

- **Origin**: `docs/quality/security-review.md`, S-14
- **Today**: `list_accounts` and `_ma_status` show MA error text verbatim to the parent.
- **Options**: (1) Leave as is (parent-only, useful to diagnose). (2) Truncate or filter host names.
- **Recommendation**: Option 1: no cross-role leak; filtering loses diagnostic value.
- **Status**: open

### R-11 — Plaintext transport to Music Assistant over `http://`

- **Origin**: `docs/quality/security-review.md`, S-19
- **Today**: With an `http://` URL the websocket is `ws://` and the MA token travels in clear on the internal network.
- **Options**: (1) Leave as is (documented deployment). (2) Log a warning when the URL is not `https://`. (3) Require `wss://`.
- **Recommendation**: Option 2: it informs without rejecting the accepted configuration.
- **Status**: open

### R-12 — URLs are logged on image failures and at MA connect

- **Origin**: `docs/quality/security-review.md`, S-20
- **Today**: `cover_url`, thumbnail source and the MA websocket URL are logged as they are; userinfo or a signed query would reach the log.
- **Options**: (1) Leave as is. (2) Redact userinfo and query before logging.
- **Recommendation**: Option 2: it changes log content only.
- **Status**: open

### R-13 — The username is logged at each login

- **Origin**: `docs/quality/security-review.md`, S-21
- **Today**: `OIDC login: <username>` is written at each login for operations.
- **Options**: (1) Leave as is. (2) Log a hashed or shortened identifier. (3) Make it a debug-level log.
- **Recommendation**: Option 1: intended for operations.
- **Status**: open

### R-14 — Identity keys are loose

- **Origin**: `docs/quality/security-review.md`, S-5
- **Today**: `zoe` and `zoé` share one owner key; a user named like a group tag writes the shared tag; `sub` is used when `preferred_username` is absent.
- **Options**: (1) Leave as is (single trusted IdP). (2) Document the constraint on IdP user names in `docs/AUTH.md`.
- **Recommendation**: Option 2: no code change.
- **Status**: open

### R-15 — `GET /auth/logout` is a GET

- **Origin**: `docs/quality/security-review.md`, S-6
- **Today**: A third-party page can log a user out (image tag); nuisance only.
- **Options**: (1) Leave as is. (2) Switch to POST (breaks existing links).
- **Recommendation**: Option 1: harm is a nuisance and a POST breaks links.
- **Status**: open

### R-16 — Remote thumbnails are resized by a third-party service

- **Origin**: `docs/quality/security-review.md`, S-17
- **Today**: `get_image_url` builds an `images.weserv.nl` URL for remote images, disclosing the image URL to that service.
- **Options**: (1) Leave as is. (2) Route through the app's signed thumbnail proxy. (3) Make the resizer configurable (empty = none).
- **Recommendation**: Option 3: the default can stay, the owner chooses.
- **Status**: open

## Behaviour kept as found

### R-17 — The default cover path is relative to the working directory

- **Origin**: `docs/quality/coverage.md`, `tests/test_covers_api.py::test_missing_cover_with_a_relative_default_path_is_a_500`; `tests/test_api_quick.py::test_thumb_download_failure_falls_back_to_the_default_cover`
- **Today**: `settings.default_cover` = `static/img/default_cover.jpg` resolves only from `app/`; from the repository root or `/app` (Docker) `GET /covers/{id}.jpg` without a cover answers 500 and the thumbnail fallback raises.
- **Options**: (1) Leave as is. (2) Resolve the path against the `app` package directory. (3) Document the working directory required.
- **Recommendation**: Option 2: the image shown is the one intended; no accepted input is rejected.
- **Status**: open

### R-18 — An unknown `media_type` on `/media` is a 500

- **Origin**: `docs/quality/coverage.md`, `tests/test_pages_views.py::test_media_list_with_an_unknown_media_type_is_a_500`
- **Today**: `GET /media?media_type=bogus` raises `ValueError` and answers 500.
- **Options**: (1) Leave as is. (2) Answer 422 or ignore the filter.
- **Recommendation**: Option 2 (422): a client error is not a server error.
- **Status**: open

### R-19 — `/browse/library/{type}` validates the type only once MA answers

- **Origin**: `docs/quality/coverage.md`, `tests/test_pages_views.py::test_browse_library_unknown_type_with_ma_down_is_a_200`
- **Today**: With MA down any type gives 200 and an empty fragment; the 400 comes only when MA is reached.
- **Options**: (1) Leave as is. (2) Validate the type before calling MA.
- **Recommendation**: Option 2.
- **Status**: open

### R-20 — `/health/ma` is not exempt from authentication

- **Origin**: `docs/quality/coverage.md`, `tests/test_health.py::test_health_has_no_unprefixed_alias`
- **Today**: Health routes exist only under `/api/v1`; only `/api/v1/health` is exempt, so a probe of `/health/ma` needs the token.
- **Options**: (1) Leave as is (the route shows the MA URL). (2) Document it for probe authors.
- **Recommendation**: Option 2: no behaviour change.
- **Status**: open

### R-21 — Deleting a category that still has tags is a 500

- **Origin**: `docs/quality/coverage.md`, `tests/test_api_tags.py::test_delete_category_that_still_has_tags_fails_with_500`
- **Today**: `DELETE /api/v1/tags/categories/{slug}` raises `IntegrityError`; the docstring promises a cascade the ORM relation does not have.
- **Options**: (1) Leave as is and fix the docstring. (2) Cascade the deletion to the tags. (3) Answer 409 while tags remain.
- **Recommendation**: Option 3: nothing is deleted by surprise.
- **Status**: open

### R-22 — A category colour is stored in lower case

- **Origin**: `docs/quality/coverage.md`, `tests/test_api_tags.py::test_create_category_answers_201_then_409_on_duplicate`
- **Today**: `#FF8800` is read back as `#ff8800`.
- **Options**: (1) Leave as is. (2) Store as sent.
- **Recommendation**: Option 1: harmless, pinned by the test.
- **Status**: open

### R-23 — `GET /api/v1/ma/search` has no error mapping

- **Origin**: `docs/quality/coverage.md`, `tests/test_api_ma.py::test_search_ma_failure_is_not_caught`
- **Today**: An MA failure gives a bare 500 while `/item` answers 400, `/now_playing` 503 and the commands 500 with a message.
- **Options**: (1) Leave as is. (2) Map the failure like its sibling routes.
- **Recommendation**: Option 2 (see R-9 for the message text).
- **Status**: open

### R-24 — A child's hard delete of another's media answers 404

- **Origin**: `docs/quality/coverage.md`, `tests/test_api_permissions.py::test_child_delete_of_others_media_is_404_even_when_hard`
- **Today**: Scope is tested before the parent right, so the answer is 404, not 403. Intended: no probing.
- **Options**: (1) Leave as is (intended). (2) Answer 403 once scope passes.
- **Recommendation**: Option 1.
- **Status**: open

### R-25 — A malformed RFID UID on write gives a 500

- **Origin**: `docs/quality/coverage.md`, `tests/test_rfid_api.py::test_put_with_a_malformed_uid_answers_500_and_stores_nothing`; `docs/quality/security-review.md`, S-11
- **Today**: The pattern is checked only on the response model: `PUT /api/v1/rfid/{uid}` stores nothing and answers 500. Not a security exposure.
- **Options**: (1) Leave as is. (2) Validate the UID on input and answer 422.
- **Recommendation**: Option 2.
- **Status**: open

### R-26 — The ESP guard is wider than what it protects

- **Origin**: `docs/quality/coverage.md`, `tests/test_esp_boundary.py::test_a_media_path_ending_in_cover_is_guarded_whatever_its_middle`
- **Today**: The guard tests prefix and suffix, so `POST /api/v1/media/cover` (no such route) also answers the guard's 404. No effect.
- **Options**: (1) Leave as is. (2) Match the exact route.
- **Recommendation**: Option 1: no effect today.
- **Status**: open

### R-27 — The Spotify account fragment is served for any media

- **Origin**: `docs/quality/coverage.md`, `tests/test_spotify_pin_api.py::test_fragment_for_a_non_spotify_media_still_renders`
- **Today**: `GET /media/{id}/spotify-account` does not check `is_switchable`; only the detail page hides the card.
- **Options**: (1) Leave as is (parent-only). (2) Check `is_switchable` and answer 404.
- **Recommendation**: Option 2.
- **Status**: open

### R-28 — No Alembic migration: the schema evolves in `init_db`

- **Origin**: `docs/quality/coverage.md`, `tests/test_startup.py::test_no_alembic_version_table_is_ever_created`
- **Today**: `alembic` is a dependency but no migration exists; `create_all` plus one manual step (`tag_categories.color`) is the whole evolution. Another column change is lost on an existing database.
- **Options**: (1) Leave as is. (2) Add Alembic migrations from the current schema. (3) Extend the manual steps in `init_db`.
- **Recommendation**: Option 2 before the next schema change; none is needed until then.
- **Status**: open

## Tooling and CI

### R-29 — Pin the GitHub Actions by commit SHA

- **Origin**: AD-4 and the lint/CI slice (`ARCHITECTURE.md`); `.github/workflows/ci.yml`, `docker-publish.yml`
- **Today**: Actions are referenced by tag (`actions/checkout@v4`, `docker/build-push-action@v5`...); a moved tag changes what runs.
- **Options**: (1) Leave as is. (2) Pin each action by SHA with the tag in a comment. (3) Pin by SHA and let Dependabot update them.
- **Recommendation**: Option 3: pinning without updates goes stale.
- **Status**: open

### R-30 — Add a type checker (mypy)

- **Origin**: AD-4 and the lint/CI slice (`ARCHITECTURE.md`)
- **Today**: No type checker runs in CI; only `ruff check .` and `pytest`.
- **Options**: (1) Leave as is. (2) Add mypy, non-blocking at first. (3) Add mypy as a blocking CI step after fixing its findings.
- **Recommendation**: Option 2: the baseline is unknown, so it should not block yet.
- **Status**: open

## Documentation gaps

### R-31 — Historical documents: aucune migration Alembic ni `alembic.ini`

- **Origin**: `docs/PLAN.md` and `docs/REQUIREMENTS.md`, banner gap: aucune migration Alembic ni `alembic.ini` : le schéma évolue dans `init_db` (`app/database.py`)
- **Today**: Both historical documents describe Alembic migrations (and an `alembic.ini`) that do not exist (see R-28).
- **Options**: (1) Leave as is (the banner already warns). (2) Correct the sentences in the document. (3) Archive the document under `docs/history/`.
- **Recommendation**: Option 1: the banner states the gap and the code is the reference.
- **Status**: open

### R-32 — Historical documents: l'authentification existe

- **Origin**: `docs/PLAN.md` and `docs/REQUIREMENTS.md`, banner gap: l'authentification existe : client OIDC depuis v0.18.0, rôles parent / enfant (voir `docs/AUTH.md`)
- **Today**: The historical documents describe no authentication.
- **Options**: (1) Leave as is (the banner already warns). (2) Correct the sentences in the document. (3) Archive the document under `docs/history/`.
- **Recommendation**: Option 1: the banner states the gap and the code is the reference.
- **Status**: open

### R-33 — Historical documents: le serveur sert aussi une API ESP dédiée sur le port 8001

- **Origin**: `docs/PLAN.md` and `docs/REQUIREMENTS.md`, banner gap: le serveur sert aussi une API ESP dédiée sur le port 8001 (`app/esp_app.py`)
- **Today**: The ESP API on port 8001 is not in the historical documents.
- **Options**: (1) Leave as is (the banner already warns). (2) Correct the sentences in the document. (3) Archive the document under `docs/history/`.
- **Recommendation**: Option 1: the banner states the gap and the code is the reference.
- **Status**: open

### R-34 — Historical documents: `app/api/views.py` est devenu le paquet `app/api/views/`

- **Origin**: `docs/PLAN.md` and `docs/REQUIREMENTS.md`, banner gap: `app/api/views.py` est devenu le paquet `app/api/views/`
- **Today**: The historical documents name `app/api/views.py`, now a package.
- **Options**: (1) Leave as is (the banner already warns). (2) Correct the sentences in the document. (3) Archive the document under `docs/history/`.
- **Recommendation**: Option 1: the banner states the gap and the code is the reference.
- **Status**: open

### R-35 — Historical documents: « pas d'auth » and « multi-utilisateurs hors périmètre » are outdated

- **Origin**: `docs/REQUIREMENTS.md`, banner gap: « pas d'auth » et « multi-utilisateurs hors périmètre » (§2, §8, hors périmètre) sont dépassés par l'authentification OIDC
- **Today**: The requirements still rule out authentication and several users.
- **Options**: (1) Leave as is (banner). (2) Correct §2 and §8.
- **Recommendation**: Option 1.
- **Status**: open

### R-36 — Historical documents: the §7 tree no longer matches the repository

- **Origin**: `docs/REQUIREMENTS.md`, banner gap: l'arborescence du §7 (dossier `migrations/`, `ha_integration.md`, noms des fichiers de tests) ne correspond plus au dépôt
- **Today**: The §7 tree lists a `migrations/` folder, `ha_integration.md` and test names that do not exist.
- **Options**: (1) Leave as is (banner). (2) Replace §7 with a pointer to the README.
- **Recommendation**: Option 1.
- **Status**: open

## New functions

Both come from the open entries of `TODO.md`, moved here once. They are recommendations: nothing here is in scope until the owner chooses.

### R-41 — Natural-language fuzzy search API (new function)

- **Origin**: `TODO.md`, 1. API de recherche floue en langage naturel
- **Today**: No such endpoint. The catalogue is searched by filters and titles only. Wanted: an endpoint taking free input ("propose-moi une liste sport", "lance Harry Potter 3", "un truc calme pour les enfants") and returning one or more matching items of the local catalogue.
  - Full-text search plus semantic matching on title, description and tags (owner, mood, context, genre, age group).
  - A ranked list: one result for a precise match, several when ambiguous.
  - To be used from Home Assistant and the mobile interface (see R-42).
  - Open question: a local LLM (Ollama), or plain ranking on embeddings / tags? Start with tag matching plus fuzzy matching on the title, escalate if not enough.
- **Options**: (1) Leave as is (no natural-language search). (2) Tag matching plus fuzzy title matching, ranked, no model: small, offline, predictable. (3) Embeddings-based ranking, heavier, better on vague requests. (4) A local LLM (Ollama): most flexible, adds a service to run and slower answers.
- **Recommendation**: Option 2 first, as the entry itself suggests; move to option 3 or 4 only if real requests show it is not enough. Developing it is the owner's call.
- **Status**: open

### R-42 — Mobile quick launcher for iPad / iPhone (new function)

- **Origin**: `TODO.md`, 2. Interface mobile « lanceur rapide » (iPad / iPhone)
- **Today**: No dedicated page. Wanted: a page to pin on the iOS home screen to start a playlist, a podcast episode or an audiobook chapter quickly.
  - Persistent filter by **owner** (kept in localStorage).
  - **Default speaker** remembered (same way).
  - Touch UI, big buttons, few levels.
  - Shows only the chosen owner's media.
  - Direct links to the episode / chapter list for podcasts and audiobooks.
  - Minimal PWA manifest for "add to home screen" mode, with an icon.
- **Options**: (1) Leave as is (use the existing pages on mobile). (2) The page as described, server-rendered like the rest, with a minimal manifest. (3) The same plus offline caching through a service worker. (4) Wait for R-41 and build the launcher around its search.
- **Recommendation**: Option 2: it covers the listed need without new moving parts; the owner filter must go through the existing permission checks (see R-7 for what a child can reach today).
- **Status**: open

## Applied

Fixes accepted under AD-6 (S-1, S-13) and the two non-critical fixes made in passing (S-2, S-12).

### R-37 — A child read other owners' media through the RFID read routes

- **Origin**: `docs/quality/security-review.md`, S-1 (critical)
- **Today**: Fixed: both `GET /api/v1/rfid` routes now scope to the signed-in child's media; a hidden card answers like an unknown one. Owner's decision 2026-11-05.
- **Options**: (1) Leave as is (rejected by the owner) (2) Scope the routes (done)
- **Recommendation**: Done as accepted.
- **Status**: applied — `249c9a6`, refined by `755ce28`

### R-38 — A child's title or source URI ran script in a parent's browser

- **Origin**: `docs/quality/security-review.md`, S-13 (critical)
- **Today**: Fixed: `showToast` sets text, inline handlers read `data-uri`, `detail.html` uses `tojson`. Accepted by the owner 2026-11-06.
- **Options**: (1) Leave as is (rejected) (2) Fix the sinks (done)
- **Recommendation**: Done as accepted.
- **Status**: applied — `8393905`

### R-39 — A non-ASCII bearer value gave an unauthenticated 500

- **Origin**: `docs/quality/security-review.md`, S-2 (fixed)
- **Today**: Fixed: the token is compared as UTF-8 bytes; the crafted header answers 401.
- **Options**: (1) Leave as is (2) Compare bytes (done)
- **Recommendation**: Done.
- **Status**: applied — `1323859`

### R-40 — A non-ASCII `sig` on `/api/v1/quick/thumb` gave an unauthenticated 500

- **Origin**: `docs/quality/security-review.md`, S-12 (fixed)
- **Today**: Fixed: the signature is compared as UTF-8 bytes; the crafted one answers 403.
- **Options**: (1) Leave as is (2) Compare bytes (done)
- **Recommendation**: Done.
- **Status**: applied — `b1d9c90`
