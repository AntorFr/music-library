# Status — Music Library

> MàJ : 2026-11-06

**Filet de tests (passe qualité, tranche `music-library-qualite-filet`) :** 485 tests verts à la fin de cette tranche ; 545 après la revue de sécurité
(122 existants intacts + 344 de caractérisation + 19 de la tranche lint/CI : pages, `/health`, couvertures, API REST,
permissions par tag, MA derrière un stub, comptes Spotify, RFID, ESP, démarrage/`init_db`).
Couverture 67 % (`pytest --cov=app`), par module dans `docs/quality/coverage.md`, avec les
zones sans test et 15 comportements douteux épinglés tels quels (aucun code de `app/` modifié).
Il n'existe aucune migration Alembic : le schéma évolue dans `init_db` (AD-filet-2).
Lancer (Python ≥ 3.12, dans un venv : `python3 -m venv .venv && . .venv/bin/activate`) : `pip install -e '.[dev]' && pytest` ; l'app sans MA : `ML_DATABASE_URL=sqlite+aiosqlite:///data/library.db python -m app.server`
(crée `data/` au besoin ; ports 8000 app, 8001 API ESP) puis `curl localhost:8000/api/v1/health` (pas `/health`) (MA injoignable n'empêche pas le démarrage).
Piège : `default_cover` est un chemin relatif ; hors `app/` ou `/app`, la route de couverture par défaut répond 500.

**Revue de sécurité (tranche `music-library-qualite-securite`) :** `docs/quality/security-review.md` — table des menaces (6 familles) et 21 constats `S-n` classés. Deux critiques, acceptés par Monsieur et appliqués sous test : S-1 (un enfant lisait, par `GET /api/v1/rfid` et `/rfid/<uid>/media`, les médias des autres : ces routes filtrent désormais sur `can_view_media`) et S-13 (XSS stocké par titre / `source_uri` : toast en `textContent`, gestionnaires `data-*`, `tojson`). Corrigés sans changement de comportement : S-2 (bearer non ASCII → 500) et S-12 (signature `thumb` non ASCII → 500). Les 17 autres sont des recommandations (B-7), non appliquées, que la tranche recommandations reprend (dont S-9 : port ESP 8001 sans authentification). 545 tests verts, `ruff check .` propre ; `version` / `app_version` inchangés.

**Refactoring (tranche `music-library-qualite-refactoring`) :** sans changement de comportement, 600 tests verts, `ruff check .` propre. `app/api/views.py` est le paquet `app/api/views/` (même `router`, même ordre de routes) ; `music_assistant.py` (990 → 729 lignes) a perdu `ma_models.py` et `ma_helpers.py`, `media_service.py` (578 → 331) `media_tags.py` et `media_selection.py` — anciens chemins d'import ré-exportés, `get_ma_client` toujours défini dans `music_assistant.py` (cible des `monkeypatch`). Une seule implémentation `get_library_*` et un seul gestionnaire `GET /library/{kind}` (404 pour un type inconnu, comme avant). Branches mortes de `media/form.html` retirées. Piège : couper un module sans ré-exporter casse les patchs des tests (AD-refactoring-1).

**Lint et CI (tranche `music-library-qualite-lint-ci`) :** `ruff check .` ne rend rien (jeu `E, F, I, UP, B, SIM`,
`line-length = 100` inchangés ; 169 constats au départ sur ruff 0.17.3, contre 148 comptés à v0.26.0 : le filet a ajouté des fichiers). Ignores, chacun motivé dans `pyproject.toml` ou en `# noqa` :
E501 sous `tests/**`, B008 pour les appels FastAPI (`Depends`, `Query`, `Form`, `Body`), `UP042`/`UP047` en ligne.
`.github/workflows/ci.yml` lance `ruff check .` puis `pytest` (Python 3.12) sur chaque PR vers `main`, sans contournement ;
485 tests verts. Jamais `--unsafe-fixes` (AD-lint-ci-1). Pas de `ruff format`, pas de mypy.

**État produit :** v0.27.0 (release du filet, sans changement fonctionnel) ; dernier changement fonctionnel, v0.26.0 — la fiche d'un podcast / playlist / album Spotify a un bloc
« Compte Spotify » (parents) : il épingle le média sur un compte MA en réécrivant
`source_uri` en URI d'instance, après avoir vérifié que ce compte renvoie du contenu.
Motif : en `library://`, MA tire un compte au hasard, compte mort compris → 0 épisode.
Avant : v0.25.0 — `/children?keepalive=1` — un podcast Spotify lent (43 s à froid
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
embarqués mais que l'interface web n'appelait jamais. (À l'époque : 108 tests ; aujourd'hui 545.)

**Prochaines étapes :**
- [ ] Vérifier sur l'instance MA réelle que le dernier épisode arrive bien en
      tête (ordre déduit du code source de MA, pas observé)
- [ ] Vérifier dans le navigateur : la barre de lecture (sondage, seek, volume)
      et la persistance profil/enceinte après un aller-retour par le menu
- [ ] Vérifier une vraie lecture sur enceinte d'un média épinglé sur un compte
      (liste d'épisodes vérifiée en réel, lecture pas encore)
- [ ] MA : compte Spotify `spotify--yPK3Sfsf` désactivé (login en échec) ; les
      médias des enfants sont épinglés sur Maison. Reste à repasser ceux des
      adultes encore en `library://` via le nouveau bloc « Compte Spotify ».
- [ ] HA : ajouter `music_library_token` dans secrets.yaml sur la box + reload
- [ ] Doublon restant jugé inoffensif : `logo.svg` = `favicon.svg`
- [ ] Backlog : voir TODO.md (recherche floue…)
