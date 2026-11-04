"""Integração com a paleta nativa do tema ativo do Omarchy (sem Qt).

Omarchy Quattro publica colors.toml em XDG_STATE_HOME/omarchy/current/theme.
A versão mais antiga pode publicá-lo em XDG_CONFIG_HOME/omarchy/current/theme.
Nunca executamos código ou templates do tema; lemos apenas valores de cores hex.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import tomllib

COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

# Apenas fallback quando o Omarchy não oferece uma paleta válida.
DEFAULTS = {
    "background": "#10131b",
    "foreground": "#e6e9f0",
    "accent": "#94a3ff",
    "red": "#ef738b",
    "green": "#71c7a2",
}


def color(raw: object, default: str) -> str:
    return str(raw).lower() if isinstance(raw, str) and COLOR_PATTERN.fullmatch(raw) else default


def rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def mix(first: str, second: str, fraction: float) -> str:
    a, b = rgb(first), rgb(second)
    x = max(0.0, min(1.0, fraction))
    return "#" + "".join(f"{round(p + (q - p) * x):02x}" for p, q in zip(a, b))


def _luminance(hex_color: str) -> float:
    components = []
    for value in rgb(hex_color):
        c = value / 255
        components.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * components[0] + 0.7152 * components[1] + 0.0722 * components[2]


def contrast(a: str, b: str) -> float:
    first, second = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def on_accent(accent: str) -> str:
    return "#ffffff" if contrast(accent, "#ffffff") > contrast(accent, "#111111") else "#111111"


def palette_from_toml(data: dict, light_mode: bool = False) -> dict[str, str]:
    """Deriva tons sem cores fixas; protege legibilidade no modo claro/escuro."""
    base = data.get("colors", data)
    if not isinstance(base, dict):
        base = {}
    bg = color(base.get("background", base.get("color0")), DEFAULTS["background"])
    fg = color(base.get("foreground", base.get("color7")), DEFAULTS["foreground"])
    accent = color(base.get("accent", base.get("color4")), DEFAULTS["accent"])
    red = color(base.get("red", base.get("color1")), DEFAULTS["red"])
    green = color(base.get("green", base.get("color2")), DEFAULTS["green"])

    mode = str(base.get("mode", data.get("mode", ""))).lower()
    is_light = mode == "light" or (mode != "dark" and (light_mode or _luminance(bg) > 0.48))
    # Se o autor fornecer foreground de baixo contraste, recupera uma cor legível.
    if contrast(bg, fg) < 4.5:
        fg = "#171717" if is_light else "#f4f4f4"
    text_muted = mix(fg, bg, 0.25)
    if contrast(bg, text_muted) < 4.5:
        text_muted = fg
    panel = mix(bg, fg, 0.035 if is_light else 0.045)
    surface = mix(bg, fg, 0.060)
    card = mix(bg, fg, 0.100)
    border = mix(bg, fg, 0.20)
    selection = color(base.get("selection"), mix(bg, accent, 0.24))
    # O selection do tema pode ser quase igual ao background; nesse caso use tom derivado.
    if contrast(selection, bg) < 1.1:
        selection = mix(bg, accent, 0.30)
    accent_hover = mix(accent, fg, 0.26)
    return {
        "bg": bg, "side": panel, "middle": mix(bg, fg, 0.024), "surface": surface,
        "card": card, "border": border, "text": fg, "muted": text_muted,
        "accent": accent, "accent2": accent_hover,
        "on_accent": on_accent(accent), "on_accent_hover": on_accent(accent_hover),
        "danger": red, "on_danger": on_accent(red), "green": green, "selection": selection,
        "on_selection": on_accent(selection),
        "tile": mix(bg, accent, 0.18), "hover": mix(bg, fg, 0.14),
        "hover_border": mix(border, accent, 0.33),
        "selected": mix(bg, accent, 0.20),
        "field": mix(bg, fg, 0.075),
        "button": mix(bg, fg, 0.13),
        "button_hover": mix(bg, fg, 0.20),
        "button_pressed": mix(bg, fg, 0.25),
        "nav_active": mix(bg, accent, 0.15),
        "danger_bg": mix(bg, red, 0.14),
        "danger_hover": mix(bg, red, 0.24),
        "tooltip": mix(bg, fg, 0.17),
        "scroll": mix(bg, fg, 0.22),
        "light": "true" if is_light else "false",
    }


@dataclass(frozen=True)
class ActiveTheme:
    colors: dict[str, str]
    identity: tuple[str, bytes, bool, str]
    name: str
    path: Path | None


def theme_candidates(*, state_home: Path | None = None,
                     config_home: Path | None = None) -> tuple[Path, Path]:
    home = Path.home()
    state = state_home if state_home is not None else Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
    config = config_home if config_home is not None else Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return (state / "omarchy/current/theme/colors.toml",
            config / "omarchy/current/theme/colors.toml")


def read_active_theme(*, state_home: Path | None = None,
                      config_home: Path | None = None) -> ActiveTheme:
    """Lê o tema a cada consulta, tolerando a troca atômica do diretório pelo Omarchy."""
    for candidate in theme_candidates(state_home=state_home, config_home=config_home):
        try:
            raw = candidate.read_bytes()
            parsed = tomllib.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                continue
            light_mode = (candidate.parent / "light.mode").exists()
            colors = palette_from_toml(parsed, light_mode)
            # Tema Quattro grava theme.name no mesmo diretório pai da pasta theme.
            name_file = candidate.parent.parent / "theme.name"
            try:
                name = (name_file.read_text(encoding="utf-8").splitlines() or ["Omarchy"])[0].strip()[:64] or "Omarchy"
            except (OSError, UnicodeError):
                name = "Omarchy"
            identity = (str(candidate), raw, light_mode, name)
            return ActiveTheme(colors, identity, name, candidate)
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            continue  # A pasta pode desaparecer momentaneamente durante a troca.
    return ActiveTheme(palette_from_toml({}), ("fallback", b"", False, "Padrão"), "Padrão", None)
