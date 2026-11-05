# Security review — Music Library v0.27.0

Threat-first review (B-4, AD-6, AD-securite-1). The repository is public: this report names
no real secret, token, user or UID — only routes, files and placeholders (`<uid>`, `<media_id>`).

Classes: **fixed** (corrected without behaviour change: no input accepted yesterday is rejected),
**recommendation** (B-7; a hardening that rejects an accepted input is one), **critical**
(AD-6: no session/token needed, a child reads or writes another owner's media, or a Spotify
credential leaks — escalated by `pilote arbitrer` as soon as found).

This file is written in two passes: the *identity* task (threat table, rows 1 and 3) and the
*surfaces* task (rows 2, 4, 5, 6).

## 1. Threat table

| # | Family | Who attacks | Through which entry point | What is at stake | Pass |
|---|---|---|---|---|---|
| 1 | Owner-tag accounts and permissions | an unauthenticated visitor; a child session; a user whose IdP claims are odd (accents/case, groups) | any `/api/v1/*` and HTML route; `get_current_user`; OIDC claims `preferred_username`/`sub`/`groups`; the session cookie; the exempt paths (`/auth/`, `/static/`, `/covers/`, health, manifest) | reading or writing another owner's media; gaining parent rights; keeping access after losing it | identity |
| 2 | Spotify accounts | a child or anonymous caller; a log/error reader | pin routes (`/media/<media_id>/spotify-account`), account stores, error bodies | leak of a Spotify credential; pinning someone else's media to an account | surfaces |
| 3 | ESP/RFID API and machine-caller token | any host on the plaintext ESP port; a child session on the main app; a holder of a crafted `Authorization` header | `app/esp_app.py` (port 8001, no auth); `/api/v1/rfid*`; bearer token (`settings.api_token`) | reading the library or an RFID→media mapping; driving the players; machine token = parent rights | identity |
| 4 | HTTP inputs (uploads, covers, templates) | any caller of the cover/upload routes; an author of a media title/description | multipart upload, `/covers/<media_id>.jpg?size&fmt`, Jinja templates, path/query params | file-write/parse abuse, XSS, resource exhaustion | surfaces |
| 5 | Outbound calls to Music Assistant | a network position between app and MA; a caller steering a URI | `app/services/music_assistant.py`: URL, token, timeouts, relayed errors | token exposure, SSRF, internal error text relayed to callers | surfaces |
| 6 | Logs | anyone who reads logs (public repo, shared cluster) | `logging` calls across `app/` | secret or identifier written to a log | surfaces |

## 2. Row — Owner-tag accounts and permissions (identity pass)

**Read:** `app/api/auth.py`, `app/services/auth_service.py`, `app/services/permissions.py`,
`app/services/tag_service.py`, `app/main.py` (middleware), the `get_current_user`/`ensure_*`
dependencies of every route in `app/api/*.py` (`media`, `tags`, `covers`, `quick`,
`music_assistant`, `rfid`, `views`).
**Coverage of the modules read** (`docs/quality/coverage.md`): `auth.py` 100 %,
`auth_service.py` 93 %, `permissions.py` 100 %, `tag_service.py` 65 %, `app/main.py` 98 %,
`app/api/media.py` 62 %, `app/api/tags.py` 63 %, `app/api/covers.py` 62 %, `app/api/quick.py` 85 %,
`app/api/views.py` 43 %.

**Route-by-route (who can call it without a session, or as a child):**

- Without a session (OIDC on): only `/auth/*`, `/static/*`, `/covers/*`, `/api/v1/health`,
  `/manifest.webmanifest`, `/favicon.ico`. Everything else answers 401 (`/api/*`) or 302 to login.
- Child session, media routes (`GET/PUT/DELETE /api/v1/media/<media_id>`, `/select`, list, cover upload,
  `/quick/<owner>`, `/quick/item/<media_id>/children`, HTML `/media/*`, tag add/remove): every one goes
  through `ensure_media_access`/`ensure_media_edit` or the SQL `owner_scope`; hidden and missing media both
  answer 404. Hard delete, tags/categories CRUD, RFID write, Spotify pin, settings: `ensure_parent`.
- Owner tags a child cannot change: `preserve_owner_tags` on update, `is_protected_owner_tag` on the tag UI.

**Verified without finding:** forged/unsigned session role (`user_from_session` + signed cookie); a
non-owner tag carrying the child's name does not grant access (category check); accents and case fold
both ways (`normalize_owner`); a `groups` claim sent as a string fails closed (no parent); `/static/..` and
`/covers/..` prefixes do not reach other routes (routing is on the literal path); login redirect is a
constant `/` (no open redirect); the OIDC `state`/PKCE are handled by authlib; the callback logs claim
*names*, not values; the session cookie is `https_only` when OIDC is on and `same_site=lax`.

### Findings

**S-1 — critical — a child reads other owners' media through the RFID read routes.**
Threat: row 1/3, "child facing another's media" (AD-6).
Evidence: `app/api/rfid.py`: `GET /api/v1/rfid` and `GET /api/v1/rfid/<uid>/media` take no
`get_current_user` and call no `ensure_media_access`/`can_view_media`. Any logged-in child gets, for
every RFID tag, the `media_id` and `media_title`, and for a known UID the media `title`, `source_uri`,
`provider` and cover URL — whoever owns the media. Every other media route answers 404 to a child
for media outside their tags. Pinned today (as doubtful) by `tests/test_rfid_api.py::test_a_child_can_still_read_and_resolve`.
Proposed fix (to be accepted by the owner): in both routes inject `get_current_user`; in the list, drop the
entries whose media the user cannot view (`can_view_media`) — unassigned tags stay listed; in resolve,
answer the same 404 as an unknown UID (`ensure_media_access`). Parents, the bearer token and dev mode
(`view_owner_keys is None`) keep exactly today's answers, so the Home Assistant / ESP readers are
unchanged. Behaviour changes only for a child, who stops seeing media they could not open anywhere else.
Test that must fail without it: a child session listing/resolving a tag assigned to a media tagged for
another owner (expects the tag filtered / 404); a parent and the bearer token still get 200 and the
full list. The existing test above pins an untagged media read by a child and will then need the
tester's decision.
**Owner's answer:** Decision of the owner (2026-11-05), option (a): fix ACCEPTED. `GET /api/v1/rfid` filters by `can_view_media` and `GET /api/v1/rfid/<uid>/media` answers 404 for media outside the signed-in child's scope; parents, bearer token and dev mode unchanged. Applied under a test that fails without it; `test_a_child_can_still_read_and_resolve` to be revisited accordingly. S-9 (ESP port 8001 without auth): no answer, stays a recommendation.
**Applied:** yes — `app/api/rfid.py` (both routes inject `get_current_user`). The tester adds the failing-without-fix test.

**S-2 — fixed — a non-ASCII `Authorization: Bearer` value gave an unauthenticated 500.**
Threat: row 3, machine-caller token.
Evidence: `auth_service._bearer_user` passed `str` to `secrets.compare_digest`, which raises `TypeError`
for non-ASCII text, so a crafted header on any route answered 500 instead of 401 (only when OIDC and
`api_token` are set). No bypass: the exception ends the request. Fix: compare the UTF-8 bytes. Every header
accepted before is accepted now; the crafted one is now rejected as any wrong token (401). Test to
add (tester): a non-ASCII bearer on `/api/v1/media` answers 401, and 500 without the fix.
**Applied:** yes (`app/services/auth_service.py`).

**S-3 — recommendation — role and groups live in the session cookie for 30 days.**
`SessionMiddleware(max_age=30 days)`; the role is derived at login only, so removing a user from the
admin group, or demoting a parent, takes effect at the next login (up to 30 days). A server-side check
or a shorter `max_age` changes who is let in today → recommendation.

**S-4 — recommendation — OIDC is all-or-nothing and fails open.**
`oidc_enabled()` needs the four `oidc_*` settings; if one is missing or misspelled the app runs in dev
mode: no login, everyone is a parent, and the API token is ignored (the bearer is read only when OIDC
is on). A startup refusal for a partial configuration rejects a start accepted today → recommendation
(log a warning at least).

**S-5 — recommendation — identity keys are loose.**
`normalize_owner` folds case and accents, so IdP users `zoe` and `zoé` share one owner key; a user whose
name equals a group tag (`famille`, `enfants`) writes the shared tag; a user's `sub` is used if
`preferred_username` is absent. These are IdP-administration matters (single trusted IdP), listed for B-7.

**S-6 — recommendation — `GET /auth/logout` is a GET and `/auth/*` is exempt.**
A third-party page can log a user out (image tag). Harm is nuisance only; a POST would break links.

**S-7 — recommendation — `/covers/<media_id>.jpg` is served without a session.**
Intentional (embedded clients, `<img>` tags), but any holder of a media id reads that cover, including
a child's, and the first request for a missing file triggers a download of the stored `cover_url` and
resized variants (bounded: `size` 16–512, two formats). Requiring a session would break the ESP and HA
clients → recommendation. Input aspects (file handling) belong to the surfaces pass.

**S-8 — recommendation — a child can drive every player and browse the whole MA library.**
`/api/v1/ma/*` (play, volume, power, search, library, `item`) has no per-media check: a child can
play any MA URI and see MA content outside their tags. Controlling the speaker is the product's purpose;
scoping it would change accepted calls. `POST /api/v1/ma/import` and `/browse/import` stamp the child's
owner tag (`owner_value`), so imports are not unscoped.

## 3. Row — ESP/RFID API and machine-caller token (identity pass)

**Read:** `app/esp_app.py`, `app/api/rfid.py`, `app/services/rfid_service.py`, the bearer path of
`auth_service.py`, `docs/AUTH.md`, `docker-compose.yml`/`Dockerfile` (port 8001).
**Coverage:** `esp_app.py` 96 %, `app/api/rfid.py` 68 %, `rfid_service.py` 86 %, `auth_service.py` 93 %.

**Verified without finding:** the ESP app mounts only `system`, `covers`, `music_assistant`, `quick`
(no RFID router, no media CRUD, no HTML); the two library-mutating writes of the shared routers
(`POST /api/v1/ma/import`, `POST /api/v1/media/<media_id>/cover`) are blocked by the guard, which matches the
decoded path (a trailing slash redirects to the blocked path; a double slash does not route); RFID writes
(`PUT /api/v1/rfid/<uid>`, assign/unassign in HTML) need `ensure_parent`; the bearer token is compared in
constant time (see S-2) and an empty `api_token` disables it; the machine identity has parent rights by
design, documented in `docs/AUTH.md`; the RFID `uid` is only a lookup key (parametrised SQL).

### Findings

**S-9 — recommendation — the ESP port has no authentication at all.**
Evidence: `esp_app.py` has no auth middleware, so `get_current_user` falls back to `DEV_USER`
(a parent): anyone reaching port 8001 reads each owner's favourites (`/api/v1/quick/<owner>`, any owner
name), episode/chapter lists, covers, and drives every player (`/api/v1/ma/play`, `volume`, `power`,
`search`, `library/*`); `/api/v1/health/ma` also shows the MA URL. This is documented (`docs/AUTH.md`:
internal network, embedded clients that cannot follow a login redirect) and `docker-compose.yml` publishes
the port. It is classed *recommendation* because the exposure rests on network placement, which the
repository does not control, and any fix (shared secret on the port) changes calls accepted today. If the
owner reads it as AD-6 (no session needed), he can say so in his answer to S-1. Proposed hardening for B-7:
an optional `ML_ESP_TOKEN` (empty = today's behaviour) and a deployment note to keep 8001 off public
routes.

**S-10 — recommendation — the machine token is one static, all-powerful secret.**
One bearer value gives parent rights on the whole main app, never expires, is not scoped to the routes
Home Assistant needs, and is not logged with the caller. Rotation is a redeploy. Scoped tokens would be
a new feature → recommendation.

**S-11 — recommendation — malformed RFID UID accepted on write, then 500 on response.**
`PUT /api/v1/rfid/<uid>` validates the UID pattern only on the response model; nothing is stored, but the
caller (a parent) gets a 500. Already pinned as doubtful in `docs/quality/coverage.md`/`tests/test_rfid_api.py`.
Not a security exposure; listed because it rejects an input in a way that changes if fixed.

(S-1 also belongs to this row: the RFID read routes are where the child scope is missing.)

## 4. Rows for the surfaces pass

Rows 2, 4, 5 and 6 are completed by the next task (`music-library-qualite-securite-surfaces`).
