#!/bin/sh
# Niveau local = la suite entière : elle n'a pas de classe lente (ni navigateur, ni écran, ni démarrage).
# Qui ajoute la première classe lente sépare les niveaux ici.
exec "$(dirname "$0")/suite-attestee.sh"
