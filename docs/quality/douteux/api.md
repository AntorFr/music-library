# Comportements douteux — tâche api

| Test | Constat | Origine |
|---|---|---|
| `test_api_tags.py::test_delete_category_that_still_has_tags_fails_with_500` | `DELETE /api/v1/tags/categories/{slug}` sur une catégorie qui porte encore des tags répond 500 (`IntegrityError: tags.category NOT NULL`). La docstring annonce « cascades to tags », mais la relation `TagCategoryModel.tags` n'a pas de cascade ORM : l'ORM met `tags.category` à NULL. | `app/services/tag_service.py::delete_tag_category`, `app/models/media.py::TagCategoryModel.tags` |
| `test_api_tags.py::test_create_category_answers_201_then_409_on_duplicate` | La couleur envoyée en `#FF8800` est relue en `#ff8800` (passée en minuscules). | `app/services/tag_service.py::create_tag_category` |
| `test_api_ma.py::test_search_ma_failure_is_not_caught` | `GET /api/v1/ma/search` n'a aucun mappage d'erreur : une panne MA donne un 500 nu, alors que `/item` répond 400, `/now_playing` 503 et les commandes 500 avec message. | `app/api/music_assistant.py::ma_search` |
| `test_api_quick.py::test_thumb_download_failure_falls_back_to_the_default_cover` | `settings.default_cover` est un chemin relatif au répertoire courant (`static/img/default_cover.jpg`) : il ne se résout que si le processus tourne depuis `app/` (image Docker : `WORKDIR /app`). Depuis la racine du dépôt, la route de repli échoue en `RuntimeError`. Le test pointe le réglage vers le fichier réel. | `app/config.py::default_cover`, `app/api/quick.py::quick_thumb` |
| `test_api_permissions.py::test_child_delete_of_others_media_is_404_even_when_hard` | Un enfant qui tente `?hard=true` sur le média d'un autre reçoit 404 (et non 403) : la portée est testée avant le droit « parent ». Voulu (pas de sondage), noté pour mémoire. | `app/api/media.py::delete_media` |
