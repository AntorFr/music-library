# Comportements douteux — pages, /health, couvertures

| Test | Constat | Origine |
|---|---|---|
| `tests/test_covers_api.py::test_missing_cover_with_a_relative_default_path_is_a_500` | `GET /covers/{id}.jpg` sans couverture locale ni `cover_url` sert `settings.default_cover` = `static/img/default_cover.jpg`, chemin relatif au répertoire courant alors que le fichier est dans `app/static/img/` : depuis la racine du dépôt ou `/app` (image Docker), `FileResponse` échoue et la route répond 500 au lieu de l'image par défaut. | `app/config.py` (`default_cover`), `app/api/covers.py::get_cover` |
| `tests/test_pages_views.py::test_media_list_with_an_unknown_media_type_is_a_500` | `GET /media?media_type=bogus` : `MediaType(media_type)` lève `ValueError`, non convertie en 4xx → 500. | `app/api/views.py::media_list` |
| `tests/test_pages_views.py::test_browse_library_unknown_type_with_ma_down_is_a_200` | `GET /browse/library/{type}` : le type n'est validé (400 « Type inconnu ») qu'une fois MA joint ; MA injoignable, tout type donne 200 avec un fragment vide. | `app/api/views.py::browse_library` |
| `tests/test_pages_views.py::test_browse_search_with_ma_down_reports_the_error_inline` | `GET /browse/search` renvoie 200 avec le texte brut de l'exception MA dans le HTML (non échappé : `f'<p>Erreur Music Assistant: {e}</p>'`). | `app/api/views.py::browse_search` |
| `tests/test_health.py::test_health_has_no_unprefixed_alias` | `/health` et `/health/ma` n'existent que sous `/api/v1` ; `/health/ma` n'est pas exempté d'authentification (401 sans session), seul `/api/v1/health` l'est — une sonde externe sur `/health/ma` doit porter le jeton. | `app/api/system.py`, `app/services/auth_service.py::_EXEMPT_PATHS` |
