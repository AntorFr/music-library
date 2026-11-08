# Music Library

A family media library manager for Home Assistant and Music Assistant. It is meant for a household that plays music, podcasts and audiobooks on embedded players (ESP devices), with parents managing the catalogue and children seeing only what is tagged for them.

It is a FastAPI application: server-rendered pages, a REST API (port 8000) and a trimmed ESP API (port 8001). Architecture: [ARCHITECTURE.md](ARCHITECTURE.md). Current state and pitfalls: [.agent/status.md](.agent/status.md).

## Install and run

### Local

Python ≥ 3.12. Music Assistant is optional: its absence does not prevent startup.

```
python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
mkdir -p data && ML_DATABASE_URL=sqlite+aiosqlite:///data/library.db python -m app.server
curl localhost:8000/api/v1/health
```

Run `pip install` before the first start: it fails once `data/` (git-ignored) exists next to `app/`. Run from the repository root (the `data/` paths are relative); the default cover (`ML_DEFAULT_COVER`, relative to the working directory) is then missing, so set `ML_DEFAULT_COVER=app/static/img/default_cover.jpg` or `GET /covers/<id>.jpg` for a media without cover answers 500. Copy [.env.example](.env.example) to `.env` to set `ML_*` values locally (it lists only the basic settings; the table below is complete).

### Docker

```
docker build -t music-library .
docker run -p 8000:8000 -p 8001:8001 music-library
```

Ports: 8000 (full API and web frontend), 8001 (dedicated ESP API). A published image is available at `ghcr.io/antorfr/music-library`; see [docker-compose.yml](docker-compose.yml) for a ready-made service definition (mount `./data` on `/app/data`). Without that mount, data is lost when the container is removed.

## Configuration

All settings are environment variables prefixed `ML_` (also read from a `.env` file). None is required: every one has a default suited to local development.

| Variable | Meaning | Default | Required |
|---|---|---|---|
| `ML_APP_NAME` | Application name | `Music Library` | no |
| `ML_APP_VERSION` | Version reported by `/health`; kept equal to the git tag (see Versioning) | `0.27.0` | no |
| `ML_DEBUG` | Debug mode | `false` | no |
| `ML_DATABASE_URL` | SQLAlchemy database URL | `sqlite+aiosqlite:///data/library.db` | no |
| `ML_COVERS_DIR` | Directory of stored covers | `data/covers` | no |
| `ML_COVER_MAX_SIZE` | Side of the square cover, in px | `300` | no |
| `ML_DEFAULT_COVER` | Cover used when none exists | `static/img/default_cover.jpg` | no |
| `ML_THUMB_SIGNING_KEY` | Secret signing thumbnail URLs (HMAC); empty uses a random per-process key | empty | no (set in production) |
| `ML_THUMBS_DIR` | Thumbnail cache directory (deliberately outside the data volume) | `/tmp/ml-thumbs` | no |
| `ML_THUMB_CACHE_MAX_BYTES` | Size cap of the thumbnail cache; `0` disables the cap | `1073741824` (1 GiB) | no |
| `ML_OIDC_ISSUER` | OIDC issuer URL | empty | no |
| `ML_OIDC_CLIENT_ID` | OIDC client id | empty | no |
| `ML_OIDC_CLIENT_SECRET` | OIDC client secret | empty | no |
| `ML_OIDC_REDIRECT_URI` | OIDC redirect URI | empty | no |
| `ML_OIDC_ADMIN_GROUP` | OIDC group whose members are parents (full access) | `parents` | no |
| `ML_SESSION_SECRET` | Secret signing the session cookie; empty uses a random per-process key (sessions reset on restart) | empty | no (set in production) |
| `ML_API_TOKEN` | Static bearer token for machine calls (parent-level access); empty disables it | empty | no |
| `ML_MUSIC_ASSISTANT_URL` | Music Assistant server URL | `http://localhost:8095` | no |
| `ML_MUSIC_ASSISTANT_TOKEN` | Music Assistant token | empty | no |
| `ML_HOME_ASSISTANT_URL` | Home Assistant URL | `http://localhost:8123` | no |
| `ML_HOME_ASSISTANT_TOKEN` | Home Assistant token | empty | no |
| `ML_HOST` | Bind address | `0.0.0.0` | no |
| `ML_PORT` | Port of the application | `8000` | no |
| `ML_ESP_PORT` | Port of the dedicated ESP API | `8001` | no |

The four `ML_OIDC_ISSUER`, `ML_OIDC_CLIENT_ID`, `ML_OIDC_CLIENT_SECRET` and `ML_OIDC_REDIRECT_URI` go together: if any is missing, the app runs in open dev mode (no login, every request acts as a parent). See [docs/AUTH.md](docs/AUTH.md).

## Lint and test

The CI ([ci.yml](.github/workflows/ci.yml)) runs, in this order:

```
pip install -e '.[dev]'
ruff check .
pytest
```

## Versioning

On each release (tag `vX.Y.Z[-suffix]`), `version` in [pyproject.toml](pyproject.toml) and `app_version` in [app/config.py](app/config.py) must equal the tag, and the bump goes in the commit that is tagged. The full rule is in [CLAUDE.md](CLAUDE.md).

## Further reading

- [ARCHITECTURE.md](ARCHITECTURE.md): organs and durable decisions.
- [docs/adr/](docs/adr/): architecture decision records.
- [docs/AUTH.md](docs/AUTH.md): authentication and roles.
- [docs/quality/](docs/quality/): coverage, security review and recommendations (to be arbitrated) of the quality pass.
