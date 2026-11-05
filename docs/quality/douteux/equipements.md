# Comportements douteux — tâche equipements

| Test | Constat | Origine |
|---|---|---|
| `test_rfid_api.py::test_put_with_a_malformed_uid_answers_500_and_stores_nothing` | `PUT /api/v1/rfid/{uid}` n'a aucune validation de l'UID en entrée : le motif n'est vérifié que sur le modèle de réponse, d'où un 500 (et rien de commité) pour un UID mal formé, au lieu d'un 422. | `app/api/rfid.py::upsert_rfid`, `app/schemas/rfid.py::RFIDTagRead` |
| `test_rfid_api.py::test_a_child_can_still_read_and_resolve` | La liste et la résolution RFID n'ont aucun contrôle de rôle ni de portée : un enfant lit tous les tags et les médias associés, y compris hors de son périmètre `owner`. | `app/api/rfid.py::list_rfid`, `resolve_media` |
| `test_esp_boundary.py::test_a_media_path_ending_in_cover_is_guarded_whatever_its_middle` | Le garde de l'application ESP teste préfixe + suffixe, pas la route : `POST /api/v1/media/cover` (qui n'existe pas) répond aussi le 404 du garde. Sans effet, mais le garde est plus large que ce qu'il protège. | `app/esp_app.py::_is_blocked_admin_write` |
| `test_spotify_pin_api.py::test_fragment_for_a_non_spotify_media_still_renders` | `GET /media/{id}/spotify-account` ne vérifie pas `is_switchable` : la carte est servie pour n'importe quel média (seule la page de détail ne la propose pas). | `app/api/views.py::media_spotify_account` |
| `test_startup.py::test_no_alembic_version_table_is_ever_created` | Aucune migration Alembic dans le dépôt (AD-filet-2) : `alembic` est une dépendance, le schéma évolue par `create_all` et une seule étape manuelle (`tag_categories.color`) dans `init_db`. Toute autre évolution de colonne est perdue sur une base existante. | `app/database.py::init_db` |
