# ADR-0002 — A static bearer token for machine callers

## Context

Home Assistant automations call the API without a browser, so they cannot go
through the OIDC login and its session cookie.

## Decision

`settings.api_token` (`ML_API_TOKEN`) is a static secret. A request carrying
`Authorization: Bearer <token>` is resolved to `MACHINE_USER`, a parent, by
`_bearer_user` in `app/services/auth_service.py`; the comparison uses
`secrets.compare_digest`. An empty token disables the mechanism. The order of
resolution in `resolve_request_user` is: dev mode, then bearer token, then
session cookie. The bearer check is only reached when OIDC is configured; in dev
mode everyone is already a parent.

## Rejected

- OIDC client-credentials or per-caller tokens: more moving parts for a single
  known caller on a home network.
- Letting machines reuse a user session: sessions expire and are tied to a person.

## Consequences

- One shared secret with parent rights: it must be rotated by hand and kept out
  of the repository (the repository is public).
- Calls made with the token are not attributable to a person, only to
  `api-token`.
