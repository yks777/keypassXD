#!/usr/bin/env bash
# keypassXD: abre o cofre local. 100% offline em uso (rede só no pip install).
# Não requer KeePassXC instalado; o KDBX é lido pela venv própria (PyKeePass).
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
PLUGIN_DIR="${HOME}/.config/omarchy/plugins/dev.keypassxd"
PYTHON="${XDG_DATA_HOME:-${HOME}/.local/share}/keypassxd/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo 'keypassXD: execute install.sh antes de abrir o gerenciador.' >&2
  exit 1
fi
# Sempre abre a tela grande do gerenciador (popup removido).
exec "$PYTHON" "$PLUGIN_DIR/app/main.py" "$@"
