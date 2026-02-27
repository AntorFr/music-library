# Music Library Manager — Requirements

## 1. Vision

Système centralisé de gestion de catalogue multimédia familial, intégré à
Home Assistant et Music Assistant. Permet de référencer, taguer et sélectionner
intelligemment des médias (playlists, livres audio, radios, podcasts…) avec des
jaquettes stables exploitables par ESPHome.

---

## 2. Contexte technique

| Élément           | Détail                                           |
| ----------------- | ------------------------------------------------ |
| Serveur           | Kubernetes (Docker)                              |
| Home Assistant    | Déjà en place, accessible via API REST           |
| Music Assistant   | Installé, gère les providers (Spotify, YTM, …)   |
| Affichage         | Écrans ESPHome (jaquettes) + tablettes (UI)      |
| Utilisateurs      | Famille (pas d'auth complexe nécessaire)         |
| Langue interface  | Français                                         |
| Langue code       | Anglais                                          |

---

## 3. Stack technique retenue

| Couche         | Technologie                          | Justification                         |
| -------------- | ------------------------------------ | ------------------------------------- |
| Backend / API  | FastAPI (Python 3.12+)               | Async, auto-doc, écosystème riche     |
| Base de données| SQLite + SQLAlchemy + Alembic        | Fichier unique, zéro config           |
| Frontend       | Jinja2 + Bootstrap 5 + HTMX         | Tout en Python/HTML, pas de JS build  |
| Jaquettes      | Dossier statique servi par FastAPI   | URLs stables pour ESPHome             |
| Déploiement    | Docker (image unique)                | Déployable sur K8s                    |

---

## 4. Modèle de données

### 4.1 Media

| Champ            | Type         | Description                                    |
| ---------------- | ------------ | ---------------------------------------------- |
| `id`             | UUID (PK)    | Identifiant unique                             |
| `title`          | String       | Nom affiché                                    |
| `media_type`     | Enum         | `playlist`, `audiobook`, `radio`, `podcast`, `album`, `track` |
| `source_uri`     | String       | URI Music Assistant ou URL directe             |
| `provider`       | String       | `spotify`, `ytmusic`, `tunein`, `local`, `url` |
| `cover_url`      | String (opt) | URL source de la jaquette                      |
| `cover_local`    | String (opt) | Chemin local `/covers/{id}.jpg`                |
| `duration_min`   | Integer (opt)| Durée en minutes                               |
| `description`    | Text (opt)   | Notes / description libre                      |
| `metadata`       | JSON (opt)   | Données extensibles (artiste, épisodes, …)     |
| `is_active`      | Boolean      | Média actif / archivé                          |
| `created_at`     | DateTime     | Date de création                               |
| `updated_at`     | DateTime     | Dernière modification                          |

### 4.2 Tag

| Champ      | Type        | Description                                     |
| ---------- | ----------- | ----------------------------------------------- |
| `id`       | Integer (PK)| Identifiant                                     |
| `category` | String      | Catégorie : `owner`, `mood`, `context`, `genre`, `time_of_day`, `age_group`, `custom` |
| `value`    | String      | Valeur : `papa`, `calm`, `cooking`, `morning`…  |

Contrainte : UNIQUE(`category`, `value`)

### 4.3 MediaTag (table de liaison)

| Champ      | Type | Description                |
| ---------- | ---- | -------------------------- |
| `media_id` | UUID | FK → Media                 |
| `tag_id`   | Int  | FK → Tag                   |

---

## 5. Fonctionnalités

### 5.1 Catalogue (CRUD) — Phase 1

- [ ] Lister tous les médias (grille avec jaquettes + vue tableau)
- [ ] Ajouter un média (formulaire avec champs + tags)
- [ ] Modifier un média existant
- [ ] Supprimer un média (soft delete via `is_active`)
- [ ] Recherche textuelle (titre, description)
- [ ] Filtrage par type, provider, tags
- [ ] Tri par date, titre, type
- [ ] Pagination

### 5.2 Système de tags — Phase 2

- [ ] Créer / modifier / supprimer des tags
- [ ] Associer N tags à un média
- [ ] Interface de gestion des tags par catégorie
- [ ] Auto-complétion des tags existants dans les formulaires
- [ ] Tags prédéfinis à l'installation (mood, context, owner de base)

### 5.3 Sélection intelligente (API) — Phase 2

Endpoint principal :
```
GET /api/v1/media/select
  ?owner=papa
  &mood=calm
  &context=evening
  &media_type=playlist
  &random=true
  &limit=1
```

Extensions (compat HA) :
```
GET /api/v1/media/select
  ?tag_style=rock,pop
  &not_tag_style=metal
  &exclude_ids=<uuid1>,<uuid2>
  &fallback=soft
  &media_type=track
  &provider=spotify
  &limit=3
```

Comportement :
- Filtrage par tags : AND entre catégories
- OR au sein d'une même catégorie via valeurs CSV (ex: `tag_style=rock,pop`)
- Exclusions strictes via `not_<category>=...` et `not_tag_<slug>=...` (jamais relâchées)
- Filtres stricts non relâchés : `media_type`, `provider`, `exclude_ids`
- Fallback appliqué uniquement si 0 résultat strict :
  - `fallback=none` (défaut) : retourne `[]`
  - `fallback=aggressive` : retire des catégories (dans l'ordre inverse de déclaration) jusqu'à obtenir ≥1 résultat
  - `fallback=soft` : sélectionne les titres matchant au moins 1 tag, puis les classe par nb de tags matchés, puis par ordre des filtres fournis
- Retour 200 avec une liste (éventuellement vide)
- Ajoute `cover_url_resolved` (URL stable `/covers/{id}.jpg`) pour simplifier HA/ESPHome

Endpoint complexe (requêtes structurées ET/OU/NOT) :
```
POST /api/v1/media/select/query
Content-Type: application/json

{
  "query": {
    "all_of": [
      {"category": "owner", "values": ["papa"]},
      {"category": "mood", "values": ["calm", "focus"]}
    ],
    "none_of": [
      {"category": "genre", "values": ["metal"]}
    ],
    "any_of": []
  },
  "options": {
    "limit": 1,
    "random": false,
    "fallback": "soft",
    "exclude_ids": ["<uuid>"] ,
    "media_type": "track",
    "provider": "spotify"
  }
}
```

### 5.4 Jaquettes stables — Phase 3

- [ ] À l'ajout d'un média, option d'upload ou download depuis URL
- [ ] Stockage local dans `/data/covers/{media_id}.jpg`
- [ ] Redimensionnement automatique (300×300 px pour ESPHome)
- [ ] Endpoint statique : `GET /covers/{media_id}.jpg`
- [ ] Fallback vers image par défaut si pas de jaquette
- [ ] Cache headers pour performance

### 5.5 Intégration Home Assistant — Phase 4

- [ ] Documentation des REST commands pour HA
- [ ] Endpoint `/api/v1/ha/play` qui retourne le format attendu par MA
- [ ] Exemples d'automations YAML
- [ ] Endpoint de santé `/api/v1/health` pour monitoring

Exemple `rest_command` (GET simple) :
```yaml
rest_command:
  music_library_select:
    url: "http://music-library:8000/api/v1/media/select?owner={{ owner }}&mood={{ mood }}&fallback=soft&limit=1&media_type=track"
    method: GET
    content_type: "application/json"
```

Exemple `rest_command` (POST structuré) :
```yaml
rest_command:
  music_library_select_query:
    url: "http://music-library:8000/api/v1/media/select/query"
    method: POST
    content_type: "application/json"
    payload: >
      {
        "query": {
          "all_of": [
            {"category": "owner", "values": ["papa"]},
            {"category": "mood", "values": ["calm","focus"]}
          ],
          "none_of": [
            {"category": "genre", "values": ["metal"]}
          ],
          "any_of": []
        },
        "options": {
          "limit": 1,
          "fallback": "soft",
          "media_type": "track"
        }
      }
```

Exemple d'automation HA :
```yaml
automation:
  - alias: "Musique du matin enfants"
    trigger:
      - platform: time
        at: "07:00:00"
    condition:
      - condition: state
        entity_id: binary_sensor.kids_room_presence
        state: "on"
    action:
      - service: rest_command.music_library_play
        data:
          owner: "kids"
          mood: "wake_up"
          context: "morning"
          target_player: "media_player.kids_room"
```

### 5.6 Import / Export — Phase 5

- [ ] Import depuis fichier YAML (format défini)
- [ ] Import depuis fichier CSV
- [ ] Export du catalogue complet (YAML / JSON)
- [ ] Sauvegarde / restauration de la base

### 5.7 Interface graphique — Transverse

- [ ] Dashboard principal avec grille de jaquettes
- [ ] Formulaire d'ajout/édition avec preview jaquette
- [ ] Page de gestion des tags
- [ ] Filtres dynamiques (HTMX, sans rechargement)
- [ ] Responsive (tablette + mobile)
- [ ] Thème sombre / clair
- [ ] Feedback utilisateur (toasts, confirmations)
- [ ] Liens rapides : copier l'URI, ouvrir dans Music Assistant

---

## 6. API REST — Endpoints prévus

### Médias
| Méthode | Endpoint                    | Description                |
| ------- | --------------------------- | -------------------------- |
| GET     | `/api/v1/media`             | Liste (filtres, pagination)|
| GET     | `/api/v1/media/{id}`        | Détail d'un média          |
| POST    | `/api/v1/media`             | Créer un média             |
| PUT     | `/api/v1/media/{id}`        | Modifier un média          |
| DELETE  | `/api/v1/media/{id}`        | Supprimer (soft)           |
| GET     | `/api/v1/media/select`      | Sélection intelligente     |
| POST    | `/api/v1/media/select/query`| Sélection avancée (ET/OU/NOT) |

### Tags
| Méthode | Endpoint                    | Description                |
| ------- | --------------------------- | -------------------------- |
| GET     | `/api/v1/tags`              | Liste des tags             |
| POST    | `/api/v1/tags`              | Créer un tag               |
| DELETE  | `/api/v1/tags/{id}`         | Supprimer un tag           |
| GET     | `/api/v1/tags/categories`   | Liste des catégories       |

### Jaquettes
| Méthode | Endpoint                    | Description                |
| ------- | --------------------------- | -------------------------- |
| GET     | `/covers/{media_id}.jpg`    | Jaquette statique          |
| POST    | `/api/v1/media/{id}/cover`  | Upload de jaquette         |

### Système
| Méthode | Endpoint                    | Description                |
| ------- | --------------------------- | -------------------------- |
| GET     | `/api/v1/health`            | Statut de santé            |
| POST    | `/api/v1/import`            | Import YAML/CSV            |
| GET     | `/api/v1/export`            | Export catalogue           |

---

## 7. Structure du projet

```
music_library/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Point d'entrée FastAPI
│   ├── config.py               # Configuration (env vars)
│   ├── database.py             # Setup SQLAlchemy
│   ├── models/                 # Modèles SQLAlchemy
│   │   ├── __init__.py
│   │   ├── media.py
│   │   └── tag.py
│   ├── schemas/                # Schémas Pydantic
│   │   ├── __init__.py
│   │   ├── media.py
│   │   └── tag.py
│   ├── api/                    # Routes API REST
│   │   ├── __init__.py
│   │   ├── media.py
│   │   ├── tags.py
│   │   ├── covers.py
│   │   └── system.py
│   ├── services/               # Logique métier
│   │   ├── __init__.py
│   │   ├── media_service.py
│   │   ├── tag_service.py
│   │   ├── cover_service.py
│   │   └── selector.py         # Sélection intelligente
│   ├── templates/              # Templates Jinja2
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── media/
│   │   │   ├── list.html
│   │   │   ├── form.html
│   │   │   └── detail.html
│   │   ├── tags/
│   │   │   └── manage.html
│   │   └── components/         # Fragments HTMX
│   │       ├── media_card.html
│   │       ├── media_table_row.html
│   │       └── tag_badge.html
│   └── static/                 # CSS, icônes
│       ├── css/
│       │   └── app.css
│       └── img/
│           └── default_cover.jpg
├── data/                       # Données persistantes (volume Docker)
│   ├── library.db              # Base SQLite
│   └── covers/                 # Jaquettes téléchargées
├── migrations/                 # Alembic
│   └── ...
├── tests/
│   ├── test_api_media.py
│   ├── test_api_tags.py
│   └── test_selector.py
├── docs/
│   ├── REQUIREMENTS.md         # Ce fichier
│   ├── PLAN.md                 # Plan de marche détaillé
│   └── ha_integration.md       # Guide intégration HA
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
└── README.md
```

---

## 8. Contraintes non-fonctionnelles

| Contrainte       | Cible                                          |
| ---------------- | ---------------------------------------------- |
| Performance      | < 200ms par requête API                        |
| Disponibilité    | Redémarrage auto via K8s                       |
| Stockage         | SQLite < 10 MB, covers < 500 MB               |
| Sécurité         | Réseau local uniquement (pas d'auth v1)        |
| Compatibilité    | Python 3.12+, Docker multi-arch (amd64/arm64)  |
| Maintenabilité   | Code simple, bien documenté, typé              |

---

## 9. Hors scope (v1)

- Authentification multi-utilisateurs
- Streaming audio direct
- Synchronisation automatique avec les playlists Spotify/YTM
- Application mobile native
- Gestion de droits parentaux
