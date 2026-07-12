# Authentification & permissions

Depuis v0.18.0, l'application est **cliente OIDC** de l'IdP du homelab (Authelia) :
pas de base utilisateurs locale, l'identité vient des claims OIDC à chaque login.

## Modèle de rôles

Le rôle est dérivé du claim `groups` (scopes `openid profile email groups`) :

| Rôle | Condition | Droits |
|---|---|---|
| **parent** | membre du groupe `ML_OIDC_ADMIN_GROUP` (défaut `parents`) | tout voir / tout modifier |
| **enfant** | tout autre utilisateur authentifié | voir uniquement les médias portant son tag `owner`, en ajouter (tag appliqué d'office), modifier/supprimer les siens |

Le lien utilisateur ↔ médias repose sur une convention : le **username** Authelia
de l'enfant correspond (insensible à la casse **et aux accents**) à la **valeur de
son tag `owner`** (ex. user `zoe` ↔ tag `owner:Zoé`).

Garde-fous côté enfant :

- le scope owner est appliqué **en SQL** sur toutes les lectures (liste, détail,
  `/select`, `/select/query`, lanceur rapide) et n'est jamais relâché par le
  fallback de sélection ;
- toute création/import reçoit d'office son tag `owner` ;
- il ne peut pas retirer son propre tag `owner` d'un média ;
- les médias des autres répondent **404** (pas de sondage d'existence) ;
- gestion des tags/catégories, RFID et import MA global : **parents uniquement** (403).

## Variables d'environnement

| Variable | Rôle |
|---|---|
| `ML_OIDC_ISSUER` | Issuer canonique de l'IdP (ex. `https://auth.berard.me`) |
| `ML_OIDC_CLIENT_ID` | `client_id` déclaré dans Authelia |
| `ML_OIDC_CLIENT_SECRET` | Secret client (en clair côté app) |
| `ML_OIDC_REDIRECT_URI` | `https://<host>/auth/callback` |
| `ML_OIDC_ADMIN_GROUP` | Groupe → rôle parent (défaut `parents`) |
| `ML_SESSION_SECRET` | Signature du cookie de session (stable en prod) |
| `ML_API_TOKEN` | Bearer machine (Home Assistant) → accès niveau parent |

⚠️ Les quatre `ML_OIDC_*` vont ensemble : si l'un manque, l'app tourne en
**mode dev** — aucune authentification, chaque requête agit en parent.

## Surfaces

- **App principale (port 8000)** : tout (UI + `/api/v1`) exige une session OIDC
  ou le bearer `ML_API_TOKEN`. Exemptions : `/auth/*`, `/static/*`, `/covers/*`,
  `/manifest.webmanifest`, `/api/v1/health`.
- **App ESP (port 8001)** : aucune auth (réseau interne, clients embarqués —
  une redirection 302 vers l'IdP les casserait).

## Flow OIDC

Authorization Code + PKCE (S256), client confidentiel en
`client_secret_basic` (Authelia refuse `client_secret_post`). La découverte
(`/.well-known/openid-configuration`) est paresseuse : l'app démarre même si
l'IdP est indisponible, et les sessions applicatives survivent à une panne de
l'IdP (il n'est sollicité qu'au login).

Routes : `GET /auth/login` → IdP → `GET /auth/callback` (échange du code,
lecture du userinfo, ouverture de session) → `/`. `GET /auth/logout` purge la
session applicative (la session IdP reste ouverte).

## Côté Authelia (infra)

Client à déclarer dans `identity_providers.oidc.clients` :
`client_id: music-library`, `redirect_uris: [https://<host>/auth/callback]`,
`scopes: [openid, profile, email, groups]`, `authorization_policy: one_factor`,
`userinfo_signed_response_alg: none`, secret hashé (pbkdf2-sha512).
Les comptes enfants portent un username égal à la valeur de leur tag `owner`
et **pas** le groupe `parents`.
