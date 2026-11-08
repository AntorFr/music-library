# ADR-0004 — Thumbnails go through a signed, cached proxy

## Context

The embedded ESP dashboard cannot fetch large, remote images over TLS. Episode
art comes from any host (Spotify CDN, podcast hosts, MA image proxy). A proxy
that fetches any URL it is given is an open proxy and an SSRF hole.

## Decision

The server hands out proxy URLs `/api/v1/quick/thumb?src=…&size=…&sig=…` built by
`thumb_proxy_url` in `app/services/cover_service.py`. `sig` is an HMAC-SHA256 of
`src|size` under `thumb_signing_key`; `verify_thumb` compares in constant time
and `quick_thumb` (`app/api/quick.py`) answers 403 to anything it did not sign.
The resized image is cached on disk under a hash of the source URL and size. The
output format is not part of the signature.

## Rejected

- A host allow-list: needs maintenance and the hosts vary.
- Letting the device fetch the source directly: slow decode, TLS cost.
- Putting the format in the signature: the device could not choose a cheaper
  format without a new URL.

## Consequences

- Without a configured `thumb_signing_key` a random per-process key is used:
  signed links die with the process, which is acceptable because they are
  regenerated each session.
- The cache is not persisted and may be wiped at any time.
