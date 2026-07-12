# Status — Music Library

> MàJ : 2026-07-12

**État :** v0.19.0 — auth OIDC (Authelia) + rôles parents/enfants côté app :
scope owner en SQL (tag username + tags des groupes en lecture, écriture sur
son tag seul), auto-tag à la création, matching accents/casse, UI adaptée,
57 tests verts. Reste le câblage infra (client OIDC, comptes enfants, values
Helm) et le token HA.

**Prochaines étapes :**
- [ ] Déclarer le client OIDC `music-library` dans Authelia + comptes enfants (usernames = valeurs de tags owner)
- [ ] Values Helm : env `ML_OIDC_*`, `ML_SESSION_SECRET`, `ML_API_TOKEN`, retrait du middleware forwardAuth, tag image 0.18.0
- [ ] HA : header bearer sur les appels `music_manager.yaml`
- [ ] Vérif de bout en bout (login parent/enfant, HA, port ESP)
- [ ] Backlog : voir TODO.md (recherche floue, lanceur mobile…)
