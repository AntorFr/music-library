# ADR-0006 — The embedded reader API is served on its own port

## Context

The ESP dashboard sits on a fast internal network where plaintext HTTP avoids
the TLS handshake cost. The main app also carries the admin CRUD and the web
frontend, which must not be exposed there.

## Decision

`app/server.py` runs two uvicorn servers in one process: the full app
(`app/main.py`) on `settings.port`, behind the public HTTPS proxy, and a trimmed
app (`app/esp_app.py`) on `settings.esp_port` (default 8001). The ESP app mounts
only the quick, covers, Music Assistant and health routers, and a request guard
answers 404 to the few mutating routes that ride on shared routers (MA import,
cover upload). It has no authentication: it is meant for the internal network
only (the auth middleware is installed on `app/main.py` alone; see the note on
`_EXEMPT_PREFIXES` in `app/services/auth_service.py`).

## Rejected

- One port with path filtering at the reverse proxy: the filter would live
  outside the repository.
- A second process: a second engine on the same SQLite file, and two lifecycles.
- Pruning the shared routers per app: FastAPI resolves included routes lazily
  against the shared router objects, which would also prune the main app.

## Consequences

- The ESP port must never be published outside the internal network.
- A new route added to a shared router is reachable on the ESP port unless the
  guard blocks it.
