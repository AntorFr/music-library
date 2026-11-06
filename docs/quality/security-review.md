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
for media outside their tags.
Proposed fix (to be accepted by the owner): in both routes inject `get_current_user`; in the list, drop the
entries whose media the user cannot view (`can_view_media`) — unassigned tags stay listed; in resolve,
answer exactly the 404 of an unknown UID — same status and same body, so a hidden card cannot be told
apart from a non-existent one (`can_view_media`, no `ensure_media_access`). Parents, the bearer token and dev mode
(`view_owner_keys is None`) keep exactly today's answers, so the Home Assistant / ESP readers are
unchanged. Behaviour changes only for a child, who stops seeing media they could not open anywhere else.
Test that must fail without it: a child session listing/resolving a tag assigned to a media tagged for
another owner (expects the tag filtered / 404); a parent and the bearer token still get 200 and the
full list. The existing test above pins an untagged media read by a child and will then need the
tester's decision.
**Owner's answer:** Decision of the owner (2026-11-05), option (a): fix ACCEPTED. `GET /api/v1/rfid` filters by `can_view_media` and `GET /api/v1/rfid/<uid>/media` answers 404 for media outside the signed-in child's scope; parents, bearer token and dev mode unchanged. Applied under a test that fails without it. S-9 (ESP port 8001 without auth): no answer, stays a recommendation.
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

## 4. Row — Spotify accounts (surfaces pass)

**Read:** `app/services/spotify_accounts.py`, the pin routes of `app/api/views.py`
(`/media/<media_id>/spotify-account`, GET and POST), `components/spotify_account.html`, the Spotify
parts of `app/services/media_service.py`.
**Coverage of the modules read** (`docs/quality/coverage.md`): `spotify_accounts.py` 89 %,
`media_service.py` 51 %, `app/api/views.py` 43 % (the pin fragment is among the pinned pages).

**Verified without finding:**
- The application stores no Spotify login, password or token: accounts live in Music Assistant. What the
  app holds is the MA *instance id* (`spotify--<id>`), written into `source_uri` — an identifier of an
  account slot, not a credential. `list_accounts` copies only `instance_id`, `name`, `status`,
  `last_error`; nothing else of the provider config (which may hold secrets) is read.
- Both pin routes call `ensure_parent`; a child gets 403 on GET and POST. The posted `account` must be
  one of the instance ids MA lists, usable, and must return content before anything is written, so a
  caller cannot pin a media to an arbitrary scheme or URI.
- Instance ids and account names reach the page through Jinja autoescape (`<option value>`, text);
  no `|safe` anywhere in `app/templates`.
- `source_uri` and `metadata_extra` returned by `/api/v1/media` carry the instance id only.

**S-13 below (critical) also touches this row** through `source_uri`.

### Findings

**S-14 — recommendation — MA `last_error` text is relayed to the parent's pages.** `list_accounts` shows MA's `last_error` message and `_ma_status` lists
`broken_providers[].error` verbatim; `str(exc)` of any MA failure is shown to the parent
(`Music Assistant : <exc>`). MA error texts may name hosts or accounts. Both views are parent-only, so
no leak across roles; filtering them would change what the parent sees → recommendation.

## 5. Row — HTTP inputs: uploads, covers, templates (surfaces pass)

**Read:** `app/api/covers.py`, `app/services/cover_service.py`, `app/api/quick.py` (`/thumb`),
`app/schemas/media.py` (field bounds), every Jinja template for `|safe`, inline handlers and script
blocks, the path/query parameters of `app/api/*.py`.
**Coverage of the modules read:** `covers.py` 62 %, `cover_service.py` 65 %, `quick.py` 85 %,
`schemas/media.py` 96 %, `views.py` 43 % (templates are exercised only through pinned pages).

**Verified without finding:**
- Cover files are named `<media_id>.jpg` inside `covers_dir`; `media_id` is a single path segment
  (`/covers/..%2F..%2Fetc%2Fpasswd.jpg` answers 404, no traversal) and an embedded NUL byte answers
  the default cover, not an error. Uploaded bytes are never written as received: Pillow decodes,
  converts to RGB, resizes to a square and re-encodes as JPEG, so a non-image or a polyglot file is
  refused (500 "Erreur lors du traitement", pinned) and nothing executable is stored.
- The upload route needs a media the user may edit (`ensure_media_edit`), the media must exist.
- `size` is bounded 16–512 and `fmt` is `jpg|bmp` by pattern, so the resized-variant cache is
  bounded; the thumbnail cache has an LRU cap (`_enforce_thumb_cache_limit`).
- `/api/v1/quick/thumb` fetches only URLs carrying an HMAC issued by the server (SSRF guarded), key
  random per process if `thumb_signing_key` is empty; comparison is constant time (but see S-12).
- Jinja autoescape is on for every `.html` template; no `|safe`, no `Markup`. `tojson` is used for JSON
  blocks and for `hx-vals`; inline handlers that read titles use `data-*` attributes.
- Decompression bombs: Pillow's `MAX_IMAGE_PIXELS` raises past ~179 Mpx and the error is caught.

### Findings

**S-12 — fixed — a non-ASCII `sig` on `/api/v1/quick/thumb` gave an unauthenticated 500.**
`verify_thumb` passed `str` to `hmac.compare_digest`, which raises `TypeError` on non-ASCII text.
The route is reachable with no session on the ESP port (and with any session on the main port). No
bypass: the exception ends the request. Fix: compare UTF-8 bytes (`app/services/cover_service.py`).
Every signature accepted before is accepted now; the crafted one answers 403 like any wrong signature.
Test to add (tester): `sig=é` answers 403, and 500 without the fix.
**Applied:** yes.

**S-13 — critical — a child's media title or source URI runs script in a parent's browser.**
Threat: a child session (author of a media title / `source_uri`, both free text) against a parent who
browses or plays it — the parent's session then acts with parent rights (AD-6: a child writes another
owner's media, and escalates to parent routes: tags, settings, hard delete, RFID, Spotify pin).
Evidence (two sinks, same cause — author text reaches a JavaScript context that Jinja autoescape does
not protect):
1. `app/templates/base.html` `showToast` assigns `toast.innerHTML = '…' + message`; callers pass
   media text: `listen/index.html` `playQuickMedia` (`Lecture lancée : ${title}`, title is the media
   title read from `data-title`), `ma/browse.html` (`data.title`), and server error text
   (`err.detail`). A title such as an `<img onerror=…>` element executes when a parent presses play.
2. `onclick="playChapter('{{ audiobook_uri }}', …)"` (`components/audiobook_chapters.html`),
   `playEpisode('{{ ep.uri }}')` (`podcast_episodes.html`), `importItem('{{ item.uri }}')`
   (`ma_items.html`, `ma_search_results.html`): the browser decodes the attribute before running it,
   and Jinja writes a quote as `&#39;`, so a value containing a quote ends the JS string. Rendering
   `audiobook_chapters.html` with `audiobook_uri = a');alert(1);//` gives
   `onclick="playChapter('a&#39;);alert(1);//', 0, true)"` — script. `audiobook_uri` falls back to the
   media's `source_uri` (`views.py`, audiobook chapters) when MA does not answer; `source_uri` is
   free text up to 512 characters that a child sets on their own media. `ep.uri` and `item.uri` come
   from MA/provider content (third-party text).
3. Not exploitable but same family: `media/detail.html` `const uri = '{{ item.source_uri }}'` — a quote
   becomes `&#39;` and stays inert inside a script, so it breaks the page, not the session.
No exposure without a session (child accounts exist only with OIDC on); in dev mode everyone is a parent.
Proposed fix (to be accepted by the owner): (a) `showToast` builds the icon and sets the message with
`textContent` (HTML in a toast is never intended: every caller passes plain text); (b) the four inline
handlers read their argument from a `data-uri` attribute (`this.dataset.uri`), as `listen/index.html`
already does for titles; (c) `detail.html` uses `{{ item.source_uri | tojson }}`. Legitimate values
render and behave exactly as today; only values with quotes or markup, which were broken or hostile,
change. No input is rejected.
Test that must fail without it: render the audiobook-chapters fragment for a media whose `source_uri`
holds a quote and markup, with the MA stub failing, and assert no `playChapter('…&#39;` string
break in the response (the value is in a `data-uri` attribute); assert `base.html` sets toast text with
`textContent` rather than `innerHTML`.
**Owner's answer:** accepted (Monsieur, 2026-11-06).
**Applied:** Applied — (a) `showToast` builds the icon element and a text node; (b) `data-uri` + `this.dataset.uri` in `audiobook_chapters.html` (2 buttons), `podcast_episodes.html`, `ma_items.html`, `ma_search_results.html`; (c) `detail.html` uses `source_uri | tojson`.

**S-15 — recommendation — a media's `cover_url` makes the server fetch any URL.**
`download_and_save_cover` fetches `cover_url` (up to 1024 characters, set by any user who can create or
edit a media) with `follow_redirects=True`, no scheme or host filter, from `POST/PUT /api/v1/media`
and the self-healing path of `GET /covers/<media_id>.jpg` (no session). A child can make the server
request an internal address (blind SSRF: the response is kept only if it decodes as an image, and
errors are logged, not returned). Restricting schemes or private ranges rejects URLs accepted today
→ recommendation.

**S-16 — recommendation — no size limit on uploads or downloaded covers.**
`upload_cover` reads the whole file into memory (`await file.read()`) and `httpx` reads the whole
cover response. A signed-in user can exhaust memory; a limit would reject uploads accepted today.

**S-17 — recommendation — thumbnails of remote images are resized by a third party.**
`MusicAssistantClient.get_image_url` builds `https://images.weserv.nl/?url=<image url>` for resized
remote images and the page hands that URL to browsers (outside the signed proxy used for the ESP): the
image URL is disclosed to that service. Changing it alters rendered covers → recommendation.

## 6. Row — Outbound calls to Music Assistant (surfaces pass)

**Read:** `app/services/music_assistant.py` (connection, auth handshake, command timeouts, image URLs,
image download), `app/api/music_assistant.py`, `app/api/quick.py` error paths, `app/api/system.py`.
**Coverage of the modules read:** `music_assistant.py` 51 % (network internals stubbed in every test,
see `docs/quality/coverage.md`), `api/music_assistant.py` 99 %, `api/quick.py` 85 %, `api/system.py` 100 %.

**Verified without finding:**
- The target is only `settings.music_assistant_url` (operator-set); no caller-supplied host reaches the
  websocket. Callers steer a MA *URI* or id, which is sent as a command argument, not as a URL.
- The token (`settings.music_assistant_token`) is sent once, in the `auth` command after the
  handshake, never in the URL, never returned by an API (`/health/ma` shows the URL, schema and
  version only) and never logged.
- Timeouts exist: 10 s for the auth reply, 60 s per command, 15 s for image downloads, and the
  websocket open uses the library's default open timeout.
- A failed authentication raises a constant message ("Music Assistant authentication failed").
- `GET /api/v1/health/ma` needs a session (only `/api/v1/health` is exempt).

### Findings

**S-18 — recommendation — MA exception text is relayed to callers.**
`/api/v1/ma/*` answers `HTTPException(400/500/503, detail=f"… {exc}")` (and `quick.py` 502 and its stream
error) with the raw exception text, shown by the front end in toasts (see S-13, which neutralises the
markup). It can contain the MA host or internal error wording; it never contains the token (the token is
only in the sent message). Trimming the messages changes what clients display → recommendation.

**S-19 — recommendation — plaintext transport when the URL is `http://`.**
The websocket is `ws://` for an `http://` URL, so the token travels in clear on the network between the
app and MA. That is the documented deployment (internal network); a `wss://` requirement would reject
the configuration accepted today.

## 7. Row — Logs (surfaces pass)

**Read:** every `logging` call under `app/` (about 40: `main`, `auth`, `views`, `cover_service`,
`music_assistant`, `api/music_assistant`), `logging.basicConfig` in `app/main.py`.
**Coverage of the modules read:** `main.py` 98 %, `api/auth.py` 100 %, `cover_service.py` 65 %,
`music_assistant.py` 51 %, `views.py` 43 %.

**Verified without finding:**
- No log call receives a Spotify credential, the MA token, `api_token`, `session_secret`,
  `oidc_client_secret` or the thumbnail signing key (all checked by name, none appear as arguments).
- The OIDC callback logs claim *names* and the error code, and `OIDC login: <username> (role)` — the
  username only; no token, no claim values.
- Media events log the media id, not the title or the URI. `DEBUG` (setting `debug`) only lowers the
  level; no payload dump was added.
- Error bodies: no stack trace is returned (FastAPI default 500 body is a constant string).

### Findings

**S-20 — recommendation — URLs are logged on image failures and at MA connect.**
`cover_service` logs `cover_url` / thumbnail `src_url` on failure and `music_assistant` logs
`ws_url` ("Connecting to Music Assistant at …") and the image URL on failed download. A configured MA
URL with credentials in it (`http://user:pass@host`) or a provider image URL with a signed query would be
written to the log. The repository's own documentation uses a plain host; redacting the userinfo and
query changes log content only → recommendation.

**S-21 — recommendation — the username is logged at each login.**
`OIDC login: <username>` is intended for operations; noted for operators who treat logs as shared.
