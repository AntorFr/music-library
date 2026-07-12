"""Authentication & identity service.

The app is an OIDC client of the homelab IdP (Authelia): no local user/password
database. Identity lives in the signed session cookie and is re-derived from the
IdP claims at every login — the IdP stays the single source of truth.

Role model (see also ``app/config.py``):

* **parent** — member of ``settings.oidc_admin_group``: full access (today's behaviour).
* **child**  — any other authenticated user: scoped to the media carrying the owner tag
  whose value matches their username (case-insensitive). They can add media (their owner
  tag is applied automatically) and edit/delete their own, but cannot remove their own
  owner tag nor touch anyone else's media.

Machine-to-machine callers (Home Assistant) authenticate with a static bearer token
(``settings.api_token``) and get parent-level access.

When the ``oidc_*`` settings are not configured the app runs in open *dev mode*:
every request acts as a parent and no login is required.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Literal

from starlette.requests import Request

from app.config import settings

Role = Literal["parent", "child"]

#: Key under which the identity dict is stored in the session cookie.
SESSION_USER_KEY = "user"

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurrentUser:
    username: str
    display_name: str
    role: Role

    @property
    def is_parent(self) -> bool:
        return self.role == "parent"

    @property
    def owner_value(self) -> str | None:
        """Owner-tag value a child is scoped to (``None`` = unrestricted)."""
        return None if self.is_parent else self.username.casefold()


#: Identity used when OIDC is not configured (local development).
DEV_USER = CurrentUser(username="dev", display_name="Dev mode", role="parent")

#: Identity assumed by machine callers presenting the static API token.
MACHINE_USER = CurrentUser(username="api-token", display_name="API token", role="parent")


def oidc_enabled() -> bool:
    """True when the four OIDC settings are configured (they go together)."""
    return bool(
        settings.oidc_issuer
        and settings.oidc_client_id
        and settings.oidc_client_secret
        and settings.oidc_redirect_uri
    )


def user_from_claims(claims: dict) -> CurrentUser:
    """Derive the application identity from OIDC claims (userinfo)."""
    username = str(claims.get("preferred_username") or claims.get("sub") or "").strip()
    display_name = str(claims.get("name") or username)
    groups = claims.get("groups") or []
    role: Role = "parent" if settings.oidc_admin_group in groups else "child"
    return CurrentUser(username=username, display_name=display_name, role=role)


def user_to_session(user: CurrentUser) -> dict:
    return {"username": user.username, "display_name": user.display_name, "role": user.role}


def user_from_session(data: object) -> CurrentUser | None:
    if not isinstance(data, dict):
        return None
    username = data.get("username")
    role = data.get("role")
    if not username or role not in ("parent", "child"):
        return None
    return CurrentUser(
        username=str(username),
        display_name=str(data.get("display_name") or username),
        role=role,
    )


# ---------------------------------------------------------------------------
# OIDC client (authlib) — lazy so the app starts even when the IdP is down
# ---------------------------------------------------------------------------

_oauth = None


def get_oidc_client():
    """Return the registered authlib client (discovery is fetched on first use)."""
    global _oauth
    if _oauth is None:
        from authlib.integrations.starlette_client import OAuth

        oauth = OAuth()
        oauth.register(
            name="idp",
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            server_metadata_url=(
                settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
            ),
            client_kwargs={
                "scope": "openid profile email groups",
                # Authelia rejects client_secret_post at the token endpoint.
                "token_endpoint_auth_method": "client_secret_basic",
                "code_challenge_method": "S256",
            },
        )
        _oauth = oauth
    return _oauth.idp


# ---------------------------------------------------------------------------
# Request authentication (middleware helper)
# ---------------------------------------------------------------------------

#: Paths reachable without authentication on the main app. The ESP app (port 8001)
#: has no auth at all — it lives on the internal network and never carries sessions.
_EXEMPT_PREFIXES = ("/auth/", "/static/", "/covers/")
_EXEMPT_PATHS = frozenset({"/manifest.webmanifest", "/api/v1/health", "/favicon.ico"})


def is_exempt_path(path: str) -> bool:
    return path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES)


def _bearer_user(request: Request) -> CurrentUser | None:
    if not settings.api_token:
        return None
    auth = request.headers.get("Authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    if secrets.compare_digest(token.strip(), settings.api_token):
        return MACHINE_USER
    return None


def resolve_request_user(request: Request) -> CurrentUser | None:
    """Identity for this request: dev mode > bearer token > session cookie."""
    if not oidc_enabled():
        return DEV_USER
    user = _bearer_user(request)
    if user:
        return user
    return user_from_session(request.session.get(SESSION_USER_KEY))


def get_current_user(request: Request) -> CurrentUser:
    """Identity attached by the auth middleware (always set on the main app)."""
    return getattr(request.state, "user", DEV_USER)
