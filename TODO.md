# TODO — Music Library

Backlog des évolutions à venir. Cocher ou retirer les entrées une fois livrées.

## En attente

### 1. API de recherche floue en langage naturel

Endpoint qui prend une entrée libre ("propose-moi une liste sport", "lance Harry Potter 3", "un truc calme pour les enfants") et renvoie 1+ items du catalogue local correspondant.

- Recherche full-text + matching sémantique sur titre, description, tags (owner/mood/context/genre/age_group).
- Retourne une liste classée (1 résultat si match précis, plusieurs si ambiguïté).
- À utiliser depuis Home Assistant et l'interface mobile (cf. point 2).
- Réfléchir : LLM local (Ollama) ou simple ranking sur embeddings / tags ? Démarrer par du tag-matching + fuzzy sur le titre, escalader si insuffisant.

### 2. Interface mobile « lanceur rapide » (iPad / iPhone)

Page dédiée à mettre en raccourci sur écran d'accueil iOS pour lancer rapidement une playlist, un épisode de podcast ou un chapitre d'audiobook.

- Filtre persistant par **propriétaire** (gardé en mémoire localStorage).
- **Enceinte par défaut** mémorisée (idem).
- UI tactile, gros boutons, peu de niveaux.
- Affiche uniquement les médias du propriétaire choisi.
- Liens directs vers la liste d'épisodes / chapitres pour les podcasts et audiobooks.
- Manifeste PWA minimal pour le mode "ajouter à l'écran d'accueil" + icône.

## Livré
