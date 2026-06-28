# Compatibilité Music Assistant

Ce document sert de contexte rapide pour vérifier les nouvelles versions de
Music Assistant sans relire toute l'intégration.

## État au 27 juin 2026

Versions upstream vérifiées :

| Canal | Version | Date upstream | Résultat |
| --- | --- | --- | --- |
| Stable | `2.9.4` | 25 juin 2026 | Compatible |
| Beta | `2.10.0b1` | 22 juin 2026 | Pas de rupture détectée sur notre surface |
| Nightly | `2.10.0.dev2026062706` | 27 juin 2026 | Pas de rupture détectée sur notre surface |

Sources :

- Release stable : https://github.com/music-assistant/server/releases/tag/2.9.4
- Release beta : https://github.com/music-assistant/server/releases/tag/2.10.0b1
- Releases GitHub API : https://api.github.com/repos/music-assistant/server/releases
- Code upstream : https://github.com/music-assistant/server

Constat important : `2.9.4` annonce `API_SCHEMA_VERSION = 31` et
`MIN_SCHEMA_VERSION = 28`; la branche `dev` du 27 juin 2026 annonce
`API_SCHEMA_VERSION = 34` et `MIN_SCHEMA_VERSION = 28`. Le client actuel
s'authentifie avec la commande WebSocket `auth` quand le schéma serveur est
`>= 28`, ce qui reste aligné.

Correction faite pendant cette passe : le client WebSocket accumule maintenant
les réponses partielles `partial=True`, nécessaires pour les commandes Music
Assistant qui retournent un async generator, par exemple de très longues listes
d'épisodes de podcast.

## Surface d'intégration dans ce projet

Fichiers principaux :

- `app/services/music_assistant.py` : client WebSocket, parsing des objets,
  URLs d'images, commandes haut niveau.
- `app/api/music_assistant.py` : API JSON `/api/v1/ma/*`.
- `app/api/views.py` : browse/import MA, lecture depuis les pages média,
  épisodes de podcast, chapitres de livres audio, liste des players.
- `app/api/system.py` : `/api/v1/health/ma`.
- `tests/test_music_assistant_client.py` : test de non-régression sur les
  réponses partielles WebSocket.

Commandes WebSocket utilisées :

| Usage | Commande MA | Arguments envoyés |
| --- | --- | --- |
| Auth | `auth` | `token` |
| Recherche | `music/search` | `search_query`, `media_types`, `limit`, `library_only` |
| Item par URI | `music/item_by_uri` | `uri` |
| Item par type/id | `music/item` | `media_type`, `item_id`, `provider_instance_id_or_domain` |
| Bibliothèque | `music/{playlists,albums,tracks,radios,audiobooks,podcasts}/library_items` | `search`, `limit` |
| Épisodes podcast | `music/podcasts/podcast_episodes` | `item_id`, `provider_instance_id_or_domain` |
| Players | `players/all` | aucun |
| Queues | `player_queues/all` | aucun |
| Lecture | `player_queues/play_media` | `queue_id`, `media`, `option`, `radio_mode` |
| Seek | `player_queues/seek` | `queue_id`, `position` |
| Images | HTTP `/imageproxy` | `path`, `provider`, `size` |

## Procédure pour une prochaine version

1. Identifier la vraie dernière version.
   Ne pas se fier uniquement à `/releases/latest` : en juin 2026 il pouvait
   pointer sur une version différente de la dernière stable listée.

   ```bash
   curl -s 'https://api.github.com/repos/music-assistant/server/releases?per_page=20'
   ```

2. Noter la dernière stable, beta et nightly pertinentes, puis lire leurs notes.
   Chercher en priorité : `API_SCHEMA_VERSION`, `MIN_SCHEMA_VERSION`, `auth`,
   `websocket`, `music/search`, `play_media`, `player_queues`, `podcast`,
   `imageproxy`, `MediaItem`, `PlayerState`.

3. Vérifier les constantes de schéma.

   ```bash
   curl -s -o /private/tmp/ma-constants.py \
     https://raw.githubusercontent.com/music-assistant/server/<TAG>/music_assistant/constants.py
   rg -n 'API_SCHEMA_VERSION|MIN_SCHEMA_VERSION' /private/tmp/ma-constants.py
   ```

4. Vérifier les signatures des commandes utilisées.

   Pour `2.9.x` stable, les chemins utiles sont généralement :

   ```bash
   music_assistant/controllers/music.py
   music_assistant/controllers/media/base.py
   music_assistant/controllers/media/podcasts.py
   music_assistant/controllers/player_queues.py
   music_assistant/controllers/players/controller.py
   music_assistant/controllers/webserver/websocket_client.py
   ```

   Pour `2.10.x`, plusieurs fichiers ont été déplacés :

   ```bash
   music_assistant/controllers/music/controller.py
   music_assistant/controllers/music/media/base.py
   music_assistant/controllers/music/media/podcasts.py
   music_assistant/controllers/player_queues/controller.py
   music_assistant/controllers/players/controller.py
   music_assistant/controllers/webserver/websocket_client.py
   ```

5. Contrôler que toutes les commandes du tableau "Surface d'intégration" existent
   encore et que les arguments que nous envoyons n'ont pas changé de nom ou de
   type obligatoire. Les nouveaux arguments optionnels sont normalement non
   bloquants.

6. Points d'attention particuliers :

   - Si `MIN_SCHEMA_VERSION` devient supérieur à `28`, relire le handshake
     WebSocket et l'authentification.
   - Si `SuccessResultMessage` ou la gestion de `partial=True` change, relire
     `_reader_loop` dans `app/services/music_assistant.py`.
   - Si `player_queues/play_media` change, tester la lecture de playlist,
     album, radio, podcast et livre audio.
   - Si les champs `metadata.images`, `provider_mappings`, `resume_position_ms`,
     `fully_played` ou `chapters` changent, vérifier l'import, les jaquettes,
     les épisodes de podcast et les chapitres de livres audio.
   - Si `/imageproxy` change, vérifier `get_image_url`.

## Vérification locale

Tests à lancer quand l'environnement de dev est disponible :

```bash
pytest
```

À défaut, faire au minimum :

```bash
python3 -m py_compile app/services/music_assistant.py tests/test_music_assistant_client.py
```

Smoke tests avec un serveur Music Assistant réel :

```bash
curl -s http://localhost:8000/api/v1/health/ma
curl -s 'http://localhost:8000/api/v1/ma/players'
curl -s 'http://localhost:8000/api/v1/ma/search?q=test&limit=3'
```

Depuis l'UI, vérifier :

- `/browse` : recherche + import d'un média.
- `/players` : liste des players.
- Une fiche média : bouton lecture.
- Un podcast : chargement des épisodes.
- Un livre audio : chargement des chapitres et seek.

## Résultat attendu d'une passe

Documenter dans ce fichier :

- versions MA vérifiées ;
- `API_SCHEMA_VERSION` et `MIN_SCHEMA_VERSION` ;
- commandes changées ou confirmées ;
- correction éventuelle côté projet ;
- tests lancés et limites éventuelles.
