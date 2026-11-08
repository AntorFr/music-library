# Status — Music Library

> MàJ : 2026-11-08

**Version courante :** 0.27.1 (`pyproject.toml`, `app/config.py`). Historique des versions : tags git et notes de release.

**Lancer** (Python ≥ 3.12, dans un venv : `python3 -m venv .venv && . .venv/bin/activate`) :
`pip install -e '.[dev]' && pytest` ; l'app sans MA :
`ML_DATABASE_URL=sqlite+aiosqlite:///data/library.db python -m app.server`
(ports 8000 app, 8001 API ESP), puis `curl localhost:8000/api/v1/health`.
`ruff check .` doit rester propre (CI sur chaque PR vers `main`).

**Pièges connus :**
- Aucune migration Alembic : le schéma évolue dans `init_db`.
- `default_cover` est un chemin relatif ; la route de couverture par défaut ne résout que depuis `app/` : depuis la racine du dépôt comme dans l'image Docker (`WORKDIR /app`, fichier dans `/app/app/static/`), elle répond 500 sans `ML_DEFAULT_COVER=app/static/img/default_cover.jpg` (R-17).
- Couper un module sans ré-exporter ses anciens chemins d'import casse les `monkeypatch` des tests ; `get_ma_client` reste défini dans `app/services/music_assistant.py`.
- Jamais `ruff --unsafe-fixes`.
- Aucun test ne fige le numéro de version : ils lisent `pyproject.toml`, donc le bump d'une release n'en casse aucun. La suite ne dépend d'aucune branche d'epic ; seul l'historique git des commits cités par les recommandations lui est nécessaire.

**Vérifications encore ouvertes (en production) :**
- [ ] Vérifier sur l'instance MA réelle que le dernier épisode d'un podcast arrive en tête (ordre déduit du code de MA, pas observé)
- [ ] Vérifier dans le navigateur : la barre de lecture (sondage, seek, volume) et la persistance profil/enceinte après un aller-retour par le menu
- [ ] Vérifier une vraie lecture sur enceinte d'un média épinglé sur un compte Spotify (liste d'épisodes vérifiée en réel, lecture pas encore)
- [ ] MA : le compte Spotify `spotify--yPK3Sfsf` est désactivé (login en échec) ; repasser les médias des adultes encore en `library://` par le bloc « Compte Spotify »
- [ ] HA : ajouter `music_library_token` dans `secrets.yaml` sur la box, puis reload

**Reste :** les 42 recommandations (R-1…R-42) de `docs/quality/recommendations.md` attendent l'arbitrage de Monsieur ; aucune n'est appliquée hors les 4 correctifs `applied`. Le backlog d'évolutions y est versé (R-41, R-42).
