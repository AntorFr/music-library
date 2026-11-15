# Consignes projet — Music Library

## Tests : suite déclarée et attestée

La suite est déclarée dans [.sdlc.yaml](.sdlc.yaml) (`tests:`, avec le niveau `local:`). Aucun workflow GitHub ne la joue, ni sur push ni sur pull request : sa preuve est l'**attestation**, le statut `tests-complets` posé sur le commit par `attester --publier`.

- Pendant le travail : le niveau local (`scripts/suite-locale.sh`, ici la même suite que l'entière, sans classe lente).
- Avant de fusionner ou de taguer : `attester --publier` sur le dernier commit poussé.
- Une release se fait par un tag `v*` sur un commit attesté ; `docker-publish.yml` refuse de construire l'image sans l'attestation.

## Versionnage

Lors de chaque release (création d'un tag `vX.Y.Z[-suffix]`), **mettre à jour la version dans tous les emplacements** :

- [pyproject.toml](pyproject.toml) → champ `version`
- [app/config.py](app/config.py) → `app_version`

Ces deux valeurs doivent toujours correspondre exactement au tag git. Le bump doit être inclus **dans le commit qui sera taggé** (pas dans un commit suivant), sinon l'image Docker buildée affichera l'ancien numéro dans `/health`.

Workflow type pour une release :
1. Faire les modifs fonctionnelles.
2. Bump des deux champs `version` / `app_version`.
3. Commit unique (modifs + bump).
4. Push, `attester --publier`, puis `git tag vX.Y.Z` + `git push --tags`.
5. Optionnel : `gh release create` pour les notes (déclenche aussi le tag `:latest`).
