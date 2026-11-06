"""Pin the page routes after the split of views.py into the app/api/views package.

The (method, path) set below was taken from the application before the split
(commit acad31e): the split must neither add, drop nor rename a route, and the
static media routes must keep resolving before ``/media/{media_id}``.
"""

from pathlib import Path

import app.api.views as views_pkg
from app.main import app

EXPECTED_ROUTES = [
    ("DELETE", "/api/v1/media/{media_id}"),
    ("DELETE", "/api/v1/tags/categories/{slug}"),
    ("DELETE", "/api/v1/tags/{tag_id}"),
    ("DELETE", "/media/{media_id}/tags/{tag_id}"),
    ("DELETE", "/tags/categories/{slug}"),
    ("GET", "/"),
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/ma"),
    ("GET", "/api/v1/ma/item"),
    ("GET", "/api/v1/ma/library/{kind}"),
    ("GET", "/api/v1/ma/now_playing"),
    ("GET", "/api/v1/ma/players"),
    ("GET", "/api/v1/ma/search"),
    ("GET", "/api/v1/media"),
    ("GET", "/api/v1/media/select"),
    ("GET", "/api/v1/media/{media_id}"),
    ("GET", "/api/v1/quick/item/{media_id}/children"),
    ("GET", "/api/v1/quick/thumb"),
    ("GET", "/api/v1/quick/{owner}"),
    ("GET", "/api/v1/rfid"),
    ("GET", "/api/v1/rfid/{uid}/media"),
    ("GET", "/api/v1/tags"),
    ("GET", "/api/v1/tags/categories"),
    ("GET", "/auth/callback"),
    ("GET", "/auth/login"),
    ("GET", "/auth/logout"),
    ("GET", "/browse"),
    ("GET", "/browse/library/{media_type}"),
    ("GET", "/browse/search"),
    ("GET", "/covers/{media_id}.jpg"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/manifest.webmanifest"),
    ("GET", "/media"),
    ("GET", "/media/{media_id}"),
    ("GET", "/media/{media_id}/chapters"),
    ("GET", "/media/{media_id}/edit"),
    ("GET", "/media/{media_id}/episodes"),
    ("GET", "/media/{media_id}/spotify-account"),
    ("GET", "/openapi.json"),
    ("GET", "/quick"),
    ("GET", "/redoc"),
    ("GET", "/rfid"),
    ("GET", "/settings"),
    ("GET", "/tags"),
    ("HEAD", "/docs"),
    ("HEAD", "/docs/oauth2-redirect"),
    ("HEAD", "/redoc"),
    ("POST", "/api/v1/ma/import"),
    ("POST", "/api/v1/ma/mute"),
    ("POST", "/api/v1/ma/next"),
    ("POST", "/api/v1/ma/pause"),
    ("POST", "/api/v1/ma/play"),
    ("POST", "/api/v1/ma/play_pause"),
    ("POST", "/api/v1/ma/power"),
    ("POST", "/api/v1/ma/previous"),
    ("POST", "/api/v1/ma/repeat"),
    ("POST", "/api/v1/ma/resume"),
    ("POST", "/api/v1/ma/seek"),
    ("POST", "/api/v1/ma/shuffle"),
    ("POST", "/api/v1/ma/stop"),
    ("POST", "/api/v1/ma/volume"),
    ("POST", "/api/v1/ma/volume_step"),
    ("POST", "/api/v1/media"),
    ("POST", "/api/v1/media/select/query"),
    ("POST", "/api/v1/media/{media_id}/cover"),
    ("POST", "/api/v1/tags"),
    ("POST", "/api/v1/tags/categories"),
    ("POST", "/browse/import"),
    ("POST", "/media/new"),
    ("POST", "/media/{media_id}/edit"),
    ("POST", "/media/{media_id}/rfid"),
    ("POST", "/media/{media_id}/rfid/{uid}/remove"),
    ("POST", "/media/{media_id}/spotify-account"),
    ("POST", "/media/{media_id}/tags"),
    ("POST", "/rfid"),
    ("POST", "/tags"),
    ("POST", "/tags/categories"),
    ("PUT", "/api/v1/media/{media_id}"),
    ("PUT", "/api/v1/rfid/{uid}"),
]


def _walk(routes, prefix=""):
    for r in routes:
        if hasattr(r, "original_router"):
            inc_prefix = getattr(r.include_context, "prefix", "") or ""
            yield from _walk(r.original_router.routes, prefix + inc_prefix)
        elif hasattr(r, "path"):
            yield [m for m in sorted(getattr(r, "methods", None) or [])], prefix + r.path


def _ordered_routes():
    out = []
    for methods, path in _walk(app.routes):
        for m in methods:
            out.append((m, path))
    return out


def test_application_exposes_exactly_the_routes_of_the_monolithic_views():
    got = {r for r in _ordered_routes() if r != ("HEAD", "/openapi.json")}
    assert got == set(EXPECTED_ROUTES)


def test_no_route_is_registered_twice():
    routes = _ordered_routes()
    assert len(routes) == len(set(routes))


def test_static_media_routes_resolve_before_the_media_id_route():
    routes = _ordered_routes()
    checked = 0
    for method, path in routes:
        parts = path.split("/")
        if len(parts) == 3 and parts[1] == "media" and not parts[2].startswith("{"):
            checked += 1
            dyn = (method, "/media/{media_id}")
            if dyn in routes:
                assert routes.index((method, path)) < routes.index(dyn)
    assert checked >= 1  # POST /media/new at least
    assert ("POST", "/media/new") in routes


def test_package_keeps_its_public_names_and_stays_split():
    assert views_pkg.router is not None
    assert views_pkg.OWNER_COOKIE
    assert views_pkg.templates is not None
    for f in Path(views_pkg.__file__).parent.glob("*.py"):
        assert len(f.read_text().splitlines()) <= 594, f.name
