# Status — Music Library

> MàJ : 2026-11-06

**Version courante :** 0.27.0 (`pyproject.toml`, `app/config.py`). Historique des versions : tags git et notes de release.

**Lancer** (Python ≥ 3.12, dans un venv : `python3 -m venv .venv && . .venv/bin/activate`) :
`pip install -e '.[dev]' && pytest` ; l'app sans MA :
`ML_DATABASE_URL=sqlite+aiosqlite:///data/library.db python -m app.server`
(ports 8000 app, 8001 API ESP), puis `curl localhost:8000/api/v1/health`.
`ruff check .` doit rester propre (CI sur chaque PR vers `main`).

**Pièges connus :**
- Aucune migration Alembic : le schéma évolue dans `init_db`.
- `default_cover` est un chemin relatif ; hors `app/` ou `/app`, la route de couverture par défaut répond 500.
- Couper un module sans ré-exporter ses anciens chemins d'import casse les `monkeypatch` des tests ; `get_ma_client` reste défini dans `app/services/music_assistant.py`.
- Jamais `ruff --unsafe-fixes`.

**Vérifications encore ouvertes (en production) :**
- [ ] Vérifier sur l'instance MA réelle que le dernier épisode d'un podcast arrive en tête (ordre déduit du code de MA, pas observé)
- [ ] Vérifier dans le navigateur : la barre de lecture (sondage, seek, volume) et la persistance profil/enceinte après un aller-retour par le menu
- [ ] Vérifier une vraie lecture sur enceinte d'un média épinglé sur un compte Spotify (liste d'épisodes vérifiée en réel, lecture pas encore)
- [ ] MA : le compte Spotify `spotify--yPK3Sfsf` est désactivé (login en échec) ; repasser les médias des adultes encore en `library://` par le bloc « Compte Spotify »
- [ ] HA : ajouter `music_library_token` dans `secrets.yaml` sur la box, puis reload

**Renvoi :** recommandations et backlog dans `docs/quality/recommendations.md` (fichier créé par la tranche suivante).
