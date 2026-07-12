# Status — Music Library

> MàJ : 2026-07-12

**État :** v0.19.0 — auth OIDC (Authelia) + rôles parents/enfants côté app :
scope owner en SQL (tag username + tags des groupes en lecture, écriture sur
son tag seul), auto-tag à la création, matching accents/casse, UI adaptée,
57 tests verts. Infra déployée (client OIDC Authelia, comptes enfants,
values Helm 0.19.0) et vérifiée de bout en bout en prod.

**Prochaines étapes :**
- [ ] HA : ajouter `music_library_token` dans secrets.yaml sur la box + reload (le rest_command est déjà poussé)
- [ ] Tester un login enfant complet dans le navigateur (flow OIDC vérifié par API)
- [ ] Décider : purge de l'historique public v0.18.1 (prénom dans une fixture de test, anonymisée depuis)
- [ ] Backlog : voir TODO.md (recherche floue, lanceur mobile…)
