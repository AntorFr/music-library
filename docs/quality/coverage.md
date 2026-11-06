# Couverture des tests — Music Library v0.26.0

Mesure : `pytest --cov=app` (extra `dev`, `pytest-cov`), 466 tests verts (122 existants + tests du filet). Pourcentage de lignes (instructions) par module ; total **67 %** (2774 instructions, 907 non couvertes).

## Couverture par module

| Module | Instr. | Manquées | Couverture |
|---|---:|---:|---:|
| `app/__init__.py` | 0 | 0 | 100 % |
| `app/api/__init__.py` | 0 | 0 | 100 % |
| `app/api/auth.py` | 39 | 0 | 100 % |
| `app/api/covers.py` | 39 | 15 | 62 % |
| `app/api/media.py` | 88 | 33 | 62 % |
| `app/api/music_assistant.py` | 142 | 2 | 99 % |
| `app/api/quick.py` | 78 | 12 | 85 % |
| `app/api/rfid.py` | 28 | 9 | 68 % |
| `app/api/system.py` | 13 | 0 | 100 % |
| `app/api/tags.py` | 49 | 18 | 63 % |
| `app/api/views.py` | 466 | 266 | 43 % |
| `app/config.py` | 29 | 0 | 100 % |
| `app/database.py` | 25 | 3 | 88 % |
| `app/esp_app.py` | 24 | 1 | 96 % |
| `app/main.py` | 54 | 1 | 98 % |
| `app/models/__init__.py` | 0 | 0 | 100 % |
| `app/models/media.py` | 60 | 3 | 95 % |
| `app/models/rfid.py` | 11 | 0 | 100 % |
| `app/schemas/__init__.py` | 0 | 0 | 100 % |
| `app/schemas/media.py` | 182 | 7 | 96 % |
| `app/schemas/rfid.py` | 17 | 0 | 100 % |
| `app/server.py` | 23 | 23 | 0 % |
| `app/services/__init__.py` | 0 | 0 | 100 % |
| `app/services/auth_service.py` | 81 | 6 | 93 % |
| `app/services/cover_service.py` | 171 | 60 | 65 % |
| `app/services/ma_import.py` | 24 | 6 | 75 % |
| `app/services/media_service.py` | 258 | 127 | 51 % |
| `app/services/music_assistant.py` | 423 | 208 | 51 % |
| `app/services/permissions.py` | 19 | 0 | 100 % |
| `app/services/rfid_service.py` | 63 | 9 | 86 % |
| `app/services/select_engine.py` | 187 | 54 | 71 % |
| `app/services/spotify_accounts.py` | 81 | 9 | 89 % |
| `app/services/tag_service.py` | 100 | 35 | 65 % |
| **Total** | **2774** | **907** | **67 %** |

## Zones laissées sans test, et pourquoi

Le filet épingle le comportement observable par l'API et les pages (AD-filet-1) : aucun interne de service n'est testé directement, et Music Assistant reste toujours derrière un stub.

- `app/server.py` (0 %) : point d'entrée qui lance uvicorn sur les deux applications (principale et ESP) ; il démarre des serveurs réels, hors d'un test unitaire. Le démarrage de l'application est épinglé via le lifespan (`app/main.py`).
- `app/api/views.py` (43 %) : pages HTML. Sont épinglés le statut, la redirection et un contenu marqueur de chaque page principale, plus le fragment du compte Spotify. Restent non joués les branches de rendu internes, les fragments de navigation/parcours de Music Assistant (`/browse/*`, import, contrôles) et les chemins d'écriture de formulaires, dont l'intérieur est du détail de gabarit hors tranche.
- `app/services/music_assistant.py` (51 %) : client réseau MA (websocket, reconnexion, mappage de réponses). Il est remplacé par un stub dans tous les tests ; ses internes réseau ne sont pas atteignables sans MA.
- `app/services/media_service.py` (51 %) : branches de synchronisation et d'import avec MA (stubbé), recherche/filtrage avancés atteints seulement par les pages non épinglées.
- `app/services/cover_service.py` (65 %) : téléchargement distant de couvertures et repli de format ; le réseau n'est pas joué.
- `app/services/tag_service.py` (65 %), `app/api/tags.py` (63 %), `app/api/media.py` (62 %), `app/api/covers.py` (62 %), `app/api/rfid.py` (68 %) : chemins d'erreur secondaires et routes d'administration rares ; les formes de réponse principales et les permissions sont épinglées.
- `app/services/select_engine.py` (71 %) : tirage/sélection avec lecture MA (lignes 229-278), non joué sans lecteur.

Les autres modules dépassent 75 %. Aucun test existant n'a été modifié ni supprimé ; seul `pyproject.toml` gagne la ligne `pytest-cov`.

## Comportements douteux conservés

Chaque test épingle ce que fait le code à v0.26.0, même quand cela surprend (AD-filet-1). Ce sont des constats pour la tranche des recommandations ; rien n'est corrigé ici.

| Test | Constat | Origine |
|---|---|---|
| `tests/test_covers_api.py::test_missing_cover_with_a_relative_default_path_is_a_500` | `GET /covers/{id}.jpg` sans couverture locale ni `cover_url` sert `settings.default_cover` = `static/img/default_cover.jpg`, chemin relatif au répertoire courant alors que le fichier est dans `app/static/img/` : depuis la racine du dépôt ou `/app` (image Docker), `FileResponse` échoue et la route répond 500 au lieu de l'image par défaut. | `app/config.py` (`default_cover`), `app/api/covers.py::get_cover` |
| `tests/test_pages_views.py::test_media_list_with_an_unknown_media_type_is_a_500` | `GET /media?media_type=bogus` : `MediaType(media_type)` lève `ValueError`, non convertie en 4xx → 500. | `app/api/views.py::media_list` |
| `tests/test_pages_views.py::test_browse_library_unknown_type_with_ma_down_is_a_200` | `GET /browse/library/{type}` : le type n'est validé (400 « Type inconnu ») qu'une fois MA joint ; MA injoignable, tout type donne 200 avec un fragment vide. | `app/api/views.py::browse_library` |
| `tests/test_pages_views.py::test_browse_search_with_ma_down_reports_the_error_inline` | `GET /browse/search` renvoie 200 avec le texte brut de l'exception MA dans le HTML (non échappé : `f'<p>Erreur Music Assistant: {e}</p>'`). | `app/api/views.py::browse_search` |
| `tests/test_health.py::test_health_has_no_unprefixed_alias` | `/health` et `/health/ma` n'existent que sous `/api/v1` ; `/health/ma` n'est pas exempté d'authentification (401 sans session), seul `/api/v1/health` l'est — une sonde externe sur `/health/ma` doit porter le jeton. | `app/api/system.py`, `app/services/auth_service.py::_EXEMPT_PATHS` |
| `tests/test_api_tags.py::test_delete_category_that_still_has_tags_fails_with_500` | `DELETE /api/v1/tags/categories/{slug}` sur une catégorie qui porte encore des tags répond 500 (`IntegrityError: tags.category NOT NULL`). La docstring annonce « cascades to tags », mais la relation `TagCategoryModel.tags` n'a pas de cascade ORM : l'ORM met `tags.category` à NULL. | `app/services/tag_service.py::delete_tag_category`, `app/models/media.py::TagCategoryModel.tags` |
| `tests/test_api_tags.py::test_create_category_answers_201_then_409_on_duplicate` | La couleur envoyée en `#FF8800` est relue en `#ff8800` (passée en minuscules). | `app/services/tag_service.py::create_tag_category` |
| `tests/test_api_ma.py::test_search_ma_failure_is_not_caught` | `GET /api/v1/ma/search` n'a aucun mappage d'erreur : une panne MA donne un 500 nu, alors que `/item` répond 400, `/now_playing` 503 et les commandes 500 avec message. | `app/api/music_assistant.py::ma_search` |
| `tests/test_api_quick.py::test_thumb_download_failure_falls_back_to_the_default_cover` | `settings.default_cover` est un chemin relatif au répertoire courant (`static/img/default_cover.jpg`) : il ne se résout que si le processus tourne depuis `app/` (image Docker : `WORKDIR /app`). Depuis la racine du dépôt, la route de repli échoue en `RuntimeError`. Le test pointe le réglage vers le fichier réel. | `app/config.py::default_cover`, `app/api/quick.py::quick_thumb` |
| `tests/test_api_permissions.py::test_child_delete_of_others_media_is_404_even_when_hard` | Un enfant qui tente `?hard=true` sur le média d'un autre reçoit 404 (et non 403) : la portée est testée avant le droit « parent ». Voulu (pas de sondage), noté pour mémoire. | `app/api/media.py::delete_media` |
| `tests/test_rfid_api.py::test_put_with_a_malformed_uid_answers_500_and_stores_nothing` | `PUT /api/v1/rfid/{uid}` n'a aucune validation de l'UID en entrée : le motif n'est vérifié que sur le modèle de réponse, d'où un 500 (et rien de commité) pour un UID mal formé, au lieu d'un 422. | `app/api/rfid.py::upsert_rfid`, `app/schemas/rfid.py::RFIDTagRead` |
| `tests/test_esp_boundary.py::test_a_media_path_ending_in_cover_is_guarded_whatever_its_middle` | Le garde de l'application ESP teste préfixe + suffixe, pas la route : `POST /api/v1/media/cover` (qui n'existe pas) répond aussi le 404 du garde. Sans effet, mais le garde est plus large que ce qu'il protège. | `app/esp_app.py::_is_blocked_admin_write` |
| `tests/test_spotify_pin_api.py::test_fragment_for_a_non_spotify_media_still_renders` | `GET /media/{id}/spotify-account` ne vérifie pas `is_switchable` : la carte est servie pour n'importe quel média (seule la page de détail ne la propose pas). | `app/api/views.py::media_spotify_account` |
| `tests/test_startup.py::test_no_alembic_version_table_is_ever_created` | Aucune migration Alembic dans le dépôt (AD-filet-2) : `alembic` est une dépendance, le schéma évolue par `create_all` et une seule étape manuelle (`tag_categories.color`) dans `init_db`. Toute autre évolution de colonne est perdue sur une base existante. | `app/database.py::init_db` |
