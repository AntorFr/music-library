# ADR-0003 — Music Assistant is the source of playback; Spotify lists are pinned by `source_uri`

## Context

Music Library stores no audio. Playback, queues and provider catalogues
(Spotify, local library, podcasts) belong to Home Assistant's Music Assistant
(MA). With several Spotify accounts, a `library://` URI lets MA choose the
account itself, and it can pick a disabled or dead one: a podcast then lists
zero episodes.

## Decision

Every playback and catalogue call goes through the MA WebSocket client
(`app/services/music_assistant.py`; `get_ma_client` stays defined there). A local
row only keeps the MA address of its content, `source_uri`, and callers resolve
it with `resolve_ma_provider_and_id` (`app/services/ma_helpers.py`), preferring
the `source_uri` over provider + item id. A Spotify list (podcast, playlist,
album) can be pinned to one account by rewriting its `source_uri` to the
instance URI, after a probe that the account sees the list
(`app/services/spotify_accounts.py`).

## Rejected

- Playing through Home Assistant media-player services directly: loses MA's
  queues and provider resolution.
- Letting MA choose the account (`library://` URIs): the choice is unordered and
  unchecked.
- Storing the account in a separate column: the instance URI is already what the
  page and the dashboard API address, so one field serves both.

## Consequences

- The app depends on MA being reachable; its failures surface as 502 on the
  routes that need it.
- Tests patch `app.services.music_assistant.get_ma_client`, so that name must
  stay where it is.
- A pinned row stops working if the account is removed from MA; it is re-pinned
  by hand.
