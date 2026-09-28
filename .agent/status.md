# Status — Music Library

> MàJ : 2026-09-27

**État :** v0.25.0 — `/children?keepalive=1` — un podcast Spotify lent (43 s à froid
côté MA, cas Laylo) n'éjecte plus la tablette : espaces envoyés toutes les 2 s puis la page ;
et les demandes identiques en vol partagent une seule commande MA (pas de cache). Avant :
v0.24.0 — les épisodes de podcast sortent du plus récent au plus
ancien — API dashboard et fiche web ; les chapitres de livres gardent l'ordre de
lecture. Avant : v0.23.1 — corrige un bug introduit par la v0.22.1 : un profil
accentué (« Sébastien ») revenait en « n'existe plus » à chaque retour sur
Écouter, le cookie étant relu encodé (`S%C3%A9bastien`). Et nouvelle icône, alignée sur la charte Home Assistant :
même silhouette de maison que HA / Music Assistant / ESPHome (#18BCF2, glyphe
#F2F4F9, aucun dégradé), avec trois barres centrées pour glyphe. La géométrie
est relevée sur les pixels de l'icône officielle — écart mesuré nul. La pochette de remplacement reprend le même glyphe, en sourdine, et sort du même script en SVG et en JPEG. Avant :
v0.22.1, refonte nav et UI (« v2 ») et correctif de persistance du lanceur (profil et enceinte tenaient dans `localStorage` et
étaient perdus à chaque retour par le menu). Le menu passe de **8 entrées à
4** : Écouter (le lanceur, devenu la racine), Catalogue, Ajouter (= la page
Music Assistant, avec la saisie manuelle en modale), Réglages (Tags + RFID +
Système en onglets, parents uniquement). Supprimées : la page de stats qui
servait d'accueil, et la page Lecteurs qui listait les enceintes sans un seul
bouton. Les filtres du catalogue passent du mur de `<select>` à des pastilles
qui sont des liens (chaque état de filtre est une URL). Enfin, la **barre de
lecture** branche l'API de contrôle MA — qui existait depuis les écrans
embarqués mais que l'interface web n'appelait jamais. 108 tests verts.

**Prochaines étapes :**
- [ ] Vérifier sur l'instance MA réelle que le dernier épisode arrive bien en
      tête (ordre déduit du code source de MA, pas observé)
- [ ] Vérifier dans le navigateur : la barre de lecture (sondage, seek, volume)
      et la persistance profil/enceinte après un aller-retour par le menu
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
