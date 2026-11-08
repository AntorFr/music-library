# ADR-0007 — Identical Music Assistant calls are shared, and slow answers are kept alive

## Context

A Spotify-backed podcast can take about 45 s to list its episodes on a cold MA
cache. The dashboard gives up after 5 s without data and retries, and each retry
used to stack another identical MA command.

## Decision

Concurrent fetches of the same podcast's episodes share one MA call
(`_single_flight_episodes` in `app/services/ma_helpers.py`): the first caller
starts a task keyed by (provider, item id), the others join it, and callers wait
through `asyncio.shield` so a disconnecting client does not cancel the others'
fetch. The entry is removed as soon as MA answers: this is coalescing, not a
cache. For the dashboard, `/api/v1/quick/.../children?keepalive=1`
(`app/api/quick.py`) answers normally if the page is ready within a second, else
streams a whitespace byte every 2 s, then the JSON; a failure after the 200 is
sent comes back as `{"detail": ...}`.

## Rejected

- A cache of episode lists: resume positions would go stale.
- A longer client timeout: the ESP's HTTP inactivity timeout is fixed at 5 s.

## Consequences

- Leading whitespace is valid JSON, so clients need no change, but they cannot
  rely on the HTTP status for failures after the stream starts.
- Only the episode fetch is coalesced; other MA calls are not.
- The two delays must stay under the 5 s device timeout.
