# Music Library

Gestionnaire de médiathèque familiale (Home Assistant + Music Assistant) : FastAPI, pages serveur, API REST et API ESP. Architecture : `ARCHITECTURE.md` ; état et pièges : `.agent/status.md`.

## Lancer

Python ≥ 3.12, sans Music Assistant (son absence n'empêche pas le démarrage) :

```
python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
mkdir -p data && ML_DATABASE_URL=sqlite+aiosqlite:///data/library.db python -m app.server
curl localhost:8000/api/v1/health
```

Ports : 8000 (application), 8001 (API ESP). Image : `docker build -t music-library .` puis `docker run -p 8000:8000 -p 8001:8001 music-library`. Réglages `ML_*` : `.env.example`.

## Tester

`pytest` puis `ruff check .` (la CI lance les deux). Lancer depuis la racine du dépôt (chemins `data/` relatifs). Publier une version : règle de `CLAUDE.md` (`version` et `app_version` égales au tag).
