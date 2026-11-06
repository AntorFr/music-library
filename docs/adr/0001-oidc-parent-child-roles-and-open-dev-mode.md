# ADR-0001 — OIDC login, parent/child roles by owner tag, open dev mode

## Context

The library is shared by a family. Parents manage everything; children must only
see and edit their own media. There is no user table: identity must come from an
external identity provider and not require a second account store.

## Decision

Authentication is an OIDC client (`app/services/auth_service.py`, routes in
`app/api/auth.py`). Members of the group `oidc_admin_group` are *parents* (full
access); any other authenticated user is a *child*, scoped to the media that
carry the owner tag whose value matches their username (case-insensitive,
`normalize_owner`). Identity lives in the signed session cookie and is re-derived
from the claims; nothing is stored in the database. Access checks are
centralised in `app/services/permissions.py` (`ensure_media_access`,
`ensure_media_edit`, `ensure_parent`). When the four `oidc_*` settings are not
all set, `oidc_enabled()` is false and the app runs in open *dev mode*: every
request acts as the parent `DEV_USER`.

## Rejected

- A local users table with passwords: a second account store to secure and keep.
- Per-media ACLs: heavier than the family needs; the owner tag already exists as
  a tag and is editable in the UI.
- Failing to start without OIDC: it would make local development and tests need
  an identity provider.

## Consequences

- Dev mode is a deployment hazard: an instance with incomplete `oidc_*` values
  is open. The production configuration must set all four.
- The role of a user changes with the IdP group, not with any app data.
- Every route that touches media must call `permissions.py`; a new route that
  forgets it bypasses the child scoping.
