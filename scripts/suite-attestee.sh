#!/bin/sh
# Suite entière de music-library, jouée par `attester` dans une extraction neuve du commit.
# Venv jetable, installation du projet, pytest avec rapport JUnit. Code de sortie non nul si rouge.
# Le clone doit garder son historique : deux tests lisent des commits cités dans
# docs/quality/recommendations.md.
set -eu
cd "$(dirname "$0")/.."
venv=$(mktemp -d)
trap 'rm -rf "$venv"' EXIT
python3 -m venv "$venv"
"$venv/bin/pip" install --quiet -e '.[dev]'
"$venv/bin/python" -m pytest -p no:cacheprovider --junitxml=resultats.xml
