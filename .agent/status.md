# Status — Music Library

> MàJ : 2026-09-16

**État :** v0.21.0 — corrigé la résolution MA côté web : `views.py` appariait
`provider` (spotify/audible) avec l'id *library*, d'où `shows/88 not found` sur
les podcasts et `ASIN 29 not present` sur les 11 livres audio. Le resolver vit
maintenant une seule fois (`services/music_assistant.resolve_ma_provider_and_id`),
partagé par `views.py` et `quick.py`, avec tests de non-régression sur les deux
partiels HTMX. Icônes PNG ajoutées (`scripts/make_icons.py`) pour que « Ajouter à
l'écran d'accueil » iOS affiche la vraie icône. 60 tests verts.

**Prochaines étapes :**
- [ ] MA : provider « Spotify Laurine » (`spotify--yPK3Sfsf`) en `Configuration is invalid`
      mais toujours activé → premier mapping de Wyktaur/Pokémon/Les Odyssées, qui
      renvoient donc 0 épisode même avec le bon appel. Ré-authentifier ou désactiver.
- [ ] Déployer v0.21.0 (bump fait) puis vérifier l'écran d'accueil iOS
- [ ] HA : ajouter `music_library_token` dans secrets.yaml sur la box + reload
- [ ] Doublons repérés en revue, non traités : 6 méthodes `get_library_*` identiques
      + 6 routes REST `/library/<type>` identiques ; import MA écrit deux fois
      (`api/music_assistant.ma_import_item` vs `views.browse_import`) ; drill-down
      épisodes/chapitres écrit deux fois (quick.py vs views.py)
- [ ] Backlog : voir TODO.md (recherche floue, lanceur mobile…)
