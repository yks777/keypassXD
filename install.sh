#!/usr/bin/env bash
# Instalação sem sudo. Dependências obtidas do PyPI apenas após execução explícita.
set -euo pipefail
umask 077
SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$HOME/.config/omarchy/plugins/dev.keypassxd"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/keypassxd"
mkdir -p "$PLUGIN_DIR" "$DATA_DIR"
chmod 700 "$PLUGIN_DIR" "$DATA_DIR"
cp "$SOURCE/manifest.json" "$SOURCE/BarWidget.qml" "$SOURCE/Service.qml" "$SOURCE/launch.sh" "$PLUGIN_DIR/"
cp -R "$SOURCE/app" "$SOURCE/assets" "$PLUGIN_DIR/"
chmod 700 "$PLUGIN_DIR/launch.sh"
python3 -m venv "$DATA_DIR/.venv"
"$DATA_DIR/.venv/bin/python" -m pip install --disable-pip-version-check -r "$SOURCE/requirements.txt"
if command -v omarchy >/dev/null 2>&1; then
    omarchy plugin validate "$PLUGIN_DIR"
fi
if command -v omarchy-shell >/dev/null 2>&1; then
    omarchy-shell shell rescanPlugins
fi
printf '\nkeypassXD instalado. Ative com:\n  omarchy plugin enable dev.keypassxd\n'
printf 'Ou abra com:\n  %s/launch.sh\n' "$PLUGIN_DIR"
printf 'Cofres em: %s/vault.kdbx (não removidos ao desinstalar o plugin)\n' "$DATA_DIR"
