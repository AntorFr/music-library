# Status — Music Library

> MàJ : 2026-09-18

**État :** v0.23.0 — nouvelle icône, alignée sur la charte Home Assistant :
même silhouette de maison que HA / Music Assistant / ESPHome (#18BCF2, glyphe
#F2F4F9, aucun dégradé), avec trois barres centrées pour glyphe. La géométrie
est relevée sur les pixels de l'icône officielle — écart mesuré nul. Avant :
v0.22.1, refonte nav et UI (« v2 ») et correctif de persistance du lanceur (profil et enceinte tenaient dans `localStorage` et
étaient perdus à chaque retour par le menu). Le menu passe de **8 entrées à
4** : Écouter (le lanceur, devenu la racine), Catalogue, Ajouter (= la page
Music Assistant, avec la saisie manuelle en modale), Réglages (Tags + RFID +
Système en onglets, parents uniquement). Supprimées : la page de stats qui
servait d'accueil, et la page Lecteurs qui listait les enceintes sans un seul
bouton. Les filtres du catalogue passent du mur de `<select>` à des pastilles
qui sont des liens (chaque état de filtre est une URL). Enfin, la **barre de
lecture** branche l'API de contrôle MA — qui existait depuis les écrans
embarqués mais que l'interface web n'appelait jamais. 106 tests verts.

**Prochaines étapes :**
- [ ] Vérifier dans le navigateur : la barre de lecture (sondage, seek, volume)
      et la persistance profil/enceinte après un aller-retour par le menu
- [ ] `default_cover.svg` (la pochette de remplacement) est restée sur l'ancien
      style — à reprendre si elle jure avec la nouvelle icône
- [ ] MA : provider « Spotify Laurine » (`spotify--yPK3Sfsf`) en
      `Configuration is invalid` mais toujours activé → premier mapping de
      Wyktaur/Pokémon/Les Odyssées, qui renvoient 0 épisode. L'onglet Système
      le signale désormais ; reste à ré-authentifier ou désactiver.
- [ ] HA : ajouter `music_library_token` dans secrets.yaml sur la box + reload
- [ ] `media/form.html` garde ses branches `{% if item %}` alors qu'il ne sert
      plus que l'édition — nettoyage cosmétique, sans effet visible
- [ ] Doublons restants jugés inoffensifs : 6 méthodes `get_library_*` + 6
      routes REST `/library/<type>` ; `logo.svg` = `favicon.svg`
- [ ] Backlog : voir TODO.md (recherche floue…)
