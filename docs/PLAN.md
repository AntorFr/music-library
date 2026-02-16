# Music Library Manager — Plan de marche

## Vue d'ensemble

6 phases séquentielles. Chaque phase produit un livrable fonctionnel testable.

---

## Phase 1 : Fondations ⏱️ ~2 sessions

**Objectif** : Squelette fonctionnel avec CRUD basique.

### Tâches
1. **Setup projet**
   - `pyproject.toml` avec dépendances (fastapi, uvicorn, sqlalchemy, jinja2, pillow, httpx)
   - Dockerfile + docker-compose.yml
   - Structure de dossiers

2. **Base de données**
   - Modèles SQLAlchemy : `Media`, `Tag`, `MediaTag`
   - Configuration SQLite
   - Alembic init + première migration

3. **API CRUD Media**
   - `POST /api/v1/media` — Créer
   - `GET /api/v1/media` — Lister (avec pagination)
   - `GET /api/v1/media/{id}` — Détail
   - `PUT /api/v1/media/{id}` — Modifier
   - `DELETE /api/v1/media/{id}` — Supprimer (soft delete)
   - Schémas Pydantic pour validation

4. **Interface de base**
   - Template `base.html` avec Bootstrap 5
   - Page liste des médias (tableau simple)
   - Formulaire ajout/édition

5. **Health check**
   - `GET /api/v1/health`

### Livrable
> Application web fonctionnelle permettant d'ajouter, lister, modifier et
> supprimer des médias via l'interface ou l'API.

---

## Phase 2 : Tags & Sélection intelligente ⏱️ ~2 sessions

**Objectif** : Système de tags complet + endpoint de sélection pour HA.

### Tâches
1. **API Tags**
   - CRUD tags
   - Association média ↔ tags
   - Liste des catégories avec valeurs

2. **Interface Tags**
   - Gestion des tags (page dédiée)
   - Ajout de tags dans le formulaire média (auto-complétion)
   - Badges de tags sur les cartes/lignes

3. **Sélection intelligente**
   - `GET /api/v1/media/select?owner=X&mood=Y&...`
   - Logique AND entre catégories, OR au sein d'une catégorie
   - Mode aléatoire / premier résultat
   - Tests unitaires du sélecteur

4. **Filtres dans l'interface**
   - Filtres HTMX par type, provider, tags
   - Recherche textuelle

5. **Données de seed**
   - Tags prédéfinis (owner: papa/maman/kids, mood: calm/energetic/focus, etc.)

### Livrable
> On peut taguer les médias et obtenir une sélection intelligente via API.
> L'interface permet de filtrer par tags.

---

## Phase 3 : Jaquettes ⏱️ ~1 session

**Objectif** : Jaquettes stables servies en statique.

### Tâches
1. **Download & stockage**
   - Service de téléchargement d'image depuis URL
   - Redimensionnement (300×300 px, JPEG optimisé)
   - Stockage dans `/data/covers/{media_id}.jpg`

2. **Endpoints**
   - `GET /covers/{media_id}.jpg` — Statique avec cache headers
   - `POST /api/v1/media/{id}/cover` — Upload manuel
   - Image par défaut si pas de jaquette

3. **Interface**
   - Aperçu de la jaquette dans le formulaire
   - Champ URL source + bouton "Télécharger"
   - Upload d'image locale

4. **Grille visuelle**
   - Vue grille (cartes avec jaquettes) en plus de la vue tableau
   - Toggle vue grille / tableau

### Livrable
> Chaque média peut avoir une jaquette, servie via une URL stable
> `http://host:8000/covers/{id}.jpg` directement utilisable par ESPHome.

---

## Phase 4 : Intégration Home Assistant ⏱️ ~1 session

**Objectif** : Médias jouables depuis HA via Music Assistant.

### Tâches
1. **Endpoint de lecture**
   - `POST /api/v1/ha/play` — Retourne l'URI + metadata pour MA
   - Accepte les mêmes filtres que `/select`
   - Format de réponse compatible avec HA REST commands

2. **Documentation HA**
   - Exemples de `rest_command` dans `configuration.yaml`
   - Exemples d'automations (matin kids, soirée calm, etc.)
   - Script pour sélection dynamique

3. **Endpoint ESPHome**
   - Metadata simplifié pour affichage écran
   - Documentation ESPHome (composant `online_image`)

4. **Tests d'intégration**
   - Simulation d'appels depuis HA
   - Vérification des formats de réponse

### Livrable
> HA peut appeler l'API pour sélectionner et lancer un média sur Music
> Assistant. Les écrans ESPHome affichent les jaquettes.

---

## Phase 5 : Import / Export ⏱️ ~1 session

**Objectif** : Alimenter le catalogue par lot.

### Tâches
1. **Format YAML**
   - Définir le schéma YAML d'import
   - Parser + validation
   - Import avec gestion des doublons (upsert)

2. **Format CSV**
   - Template CSV téléchargeable
   - Import avec mapping de colonnes

3. **Export**
   - Export YAML / JSON du catalogue complet
   - Endpoint + bouton dans l'interface

4. **Backup**
   - Script de sauvegarde de la DB + covers
   - Documentation restauration

### Livrable
> On peut importer un fichier YAML/CSV pour alimenter le catalogue en lot,
> et exporter pour backup.

---

## Phase 6 : Polish & Production ⏱️ ~1 session

**Objectif** : Finitions pour usage quotidien.

### Tâches
1. **UX**
   - Thème sombre / clair
   - Toasts de confirmation
   - Icônes par type de média
   - Favicon

2. **Performance**
   - Index DB sur les champs de recherche
   - Cache des requêtes fréquentes
   - Optimisation des images

3. **Robustesse**
   - Gestion d'erreurs complète
   - Validation des entrées
   - Logs structurés

4. **Documentation**
   - README complet
   - Guide de déploiement K8s
   - Changelog

5. **CI/CD**
   - Dockerfile multi-stage optimisé
   - Manifests K8s (Deployment, Service, PVC)

### Livrable
> Application prête pour un usage quotidien en production sur K8s.

---

## Dépendances Python (pyproject.toml)

```
fastapi >= 0.115
uvicorn[standard] >= 0.34
sqlalchemy >= 2.0
alembic >= 1.14
jinja2 >= 3.1
python-multipart >= 0.0.18
pillow >= 11.0
httpx >= 0.28
pyyaml >= 6.0
pydantic >= 2.10
aiofiles >= 24.1
```

---

## Résumé du calendrier

| Phase | Contenu                     | Effort estimé |
| ----- | --------------------------- | ------------- |
| 1     | Fondations + CRUD           | ~2 sessions   |
| 2     | Tags + Sélection            | ~2 sessions   |
| 3     | Jaquettes                   | ~1 session    |
| 4     | Intégration HA              | ~1 session    |
| 5     | Import / Export             | ~1 session    |
| 6     | Polish                      | ~1 session    |
| **Total** |                         | **~8 sessions** |

> Une "session" = une session de travail avec Copilot (~1-2h de travail effectif)
