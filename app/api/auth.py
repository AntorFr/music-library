"""Authentication routes — OIDC login/callback/logout (see ``services/auth_service``)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import settings
from app.services.auth_service import (
    SESSION_USER_KEY,
    get_oidc_client,
    oidc_enabled,
    user_from_claims,
    user_to_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request):
    """Redirect to the IdP authorization endpoint (Authorization Code + PKCE)."""
    if not oidc_enabled():
        return RedirectResponse("/", status_code=303)
    client = get_oidc_client()
    return await client.authorize_redirect(request, settings.oidc_redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    """Exchange the authorization code, resolve claims, open the app session."""
    if not oidc_enabled():
        return RedirectResponse("/", status_code=303)

    from authlib.integrations.base_client.errors import OAuthError

    client = get_oidc_client()
    try:
        token = await client.authorize_access_token(request)
    except OAuthError as exc:
        # The precise OAuth error lands in the logs — read it before guessing.
        logger.warning("OIDC callback failed: %s — %s", exc.error, exc.description)
        raise HTTPException(401, detail=f"Authentication failed: {exc.error}") from exc

    # The groups claim is delivered by the userinfo endpoint, not the id_token.
    claims = dict(token.get("userinfo") or {})
    if "groups" not in claims:
        claims = dict(await client.userinfo(token=token))

    user = user_from_claims(claims)
    if not user.username:
        logger.error("OIDC callback returned no usable username claim: %s", list(claims))
        raise HTTPException(401, detail="Authentication failed: no username claim")

    request.session[SESSION_USER_KEY] = user_to_session(user)
    logger.info("OIDC login: %s (role=%s)", user.username, user.role)
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    """Drop the app session (the IdP session itself is untouched)."""
    request.session.pop(SESSION_USER_KEY, None)
    return RedirectResponse("/", status_code=303)
