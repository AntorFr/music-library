# Status — Music Library

> MàJ : 2026-07-12

**État :** v0.20.0 — auth OIDC (Authelia) + rôles parents/enfants côté app :
scope owner en SQL (tag username + tags des groupes, lecture ET édition ;
tags owner gérés par les parents), auto-tag à la création, accents/casse, UI,
57 tests verts. Infra déployée (client OIDC Authelia, comptes enfants,
values Helm 0.19.0) et vérifiée de bout en bout en prod.

**Prochaines étapes :**
- [ ] HA : ajouter `music_library_token` dans secrets.yaml sur la box + reload (le rest_command est déjà poussé)
- [ ] Tester un login enfant complet dans le navigateur (flow OIDC vérifié par API)
- [ ] Backlog : voir TODO.md (recherche floue, lanceur mobile…)
