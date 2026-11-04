#!/usr/bin/env bash
# Remove apenas o código. NÃO APAGA vault.kdbx, .backup ou a senha mestra.
set -euo pipefail
TARGET="$HOME/.config/omarchy/plugins/dev.keypassxd"
if command -v omarchy >/dev/null 2>&1; then
    printf 'Desative primeiro, se estiver ativo: omarchy plugin disable dev.keypassxd\n'
fi
if [[ -f "$TARGET/manifest.json" ]] && grep -q '"id": "dev.keypassxd"' "$TARGET/manifest.json"; then
    # Remove o atalho global ALT + K registrado pelo BarWidget.
    if command -v hyprctl >/dev/null 2>&1; then
        hyprctl eval 'pcall(function() hl.unbind("ALT + K") end)' >/dev/null 2>&1 || true
    fi
    rm -rf -- "$TARGET"
fi
printf 'Código removido. Dados preservados em: %s/keypassxd/\n' "${XDG_DATA_HOME:-$HOME/.local/share}"
