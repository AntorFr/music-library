# Status — Music Library

> MàJ : 2026-09-16

**État :** v0.21.0 — corrigé la résolution MA côté web : `views.py` appariait
`provider` (spotify/audible) avec l'id *library*, d'où `shows/88 not found` sur
les podcasts et `ASIN 29 not present` sur les 11 livres audio. Le resolver vit
maintenant une seule fois (`services/music_assistant.resolve_ma_provider_and_id`),
partagé par `views.py` et `quick.py`, avec tests de non-régression sur les deux
partiels HTMX. Dans la foulée, les deux autres comportements écrits en double ont
été mutualisés : l'import MA (`services/ma_import.py`) et le drill-down
épisodes/chapitres (`fetch_podcast_episodes` / `fetch_audiobook` /
`normalize_chapters`). Icônes PNG ajoutées (`scripts/make_icons.py`) pour que « Ajouter à
l'écran d'accueil » iOS affiche la vraie icône. 64 tests verts.

**Prochaines étapes :**
- [ ] MA : provider « Spotify Laurine » (`spotify--yPK3Sfsf`) en `Configuration is invalid`
      mais toujours activé → premier mapping de Wyktaur/Pokémon/Les Odyssées, qui
      renvoient donc 0 épisode même avec le bon appel. Ré-authentifier ou désactiver.
- [ ] Déployer v0.21.0 (bump fait) puis vérifier l'écran d'accueil iOS
- [ ] HA : ajouter `music_library_token` dans secrets.yaml sur la box + reload
- [ ] Doublons restants, jugés inoffensifs (du texte, pas du comportement) :
      6 méthodes `get_library_*` identiques + 6 routes REST `/library/<type>`
      identiques ; `logo.svg` et `favicon.svg` = le même dessin
- [ ] Backlog : voir TODO.md (recherche floue, lanceur mobile…)
