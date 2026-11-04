"""Qt style sheet gerado exclusivamente a partir das cores do tema Omarchy."""
from string import Template

# Substituição completa evita CSS com cores hardcoded depois de trocar de tema.
QSS = Template(r"""
QMainWindow, QDialog { background-color: $bg; color: $text; }
QDialog#framelessPopup { background: transparent; }
QWidget { font-family: 'Inter', 'Noto Sans', sans-serif; font-size: 13px; color: $text; }
QFrame#sidebar { background-color: $side; border-right: 1px solid $border; }
QFrame#middle { background-color: $middle; border-right: 1px solid $border; }
QFrame#detail { background-color: $surface; }
QFrame#row { background-color: $card; border: 1px solid $border; border-radius: 14px; }
QFrame#row:hover { background-color: $hover; border: 1px solid $hover_border; }
QFrame#row[selected="true"] { background-color: $selected; border: 1px solid $accent; }
QFrame#tile { background-color: $tile; border-radius: 11px; }
QFrame#protection { background-color: $card; border: 1px solid $border; border-radius: 15px; }
QFrame#popup { background-color: $middle; border: 1px solid $border; border-radius: 14px; }
QFrame#poprow { background-color: $card; border: 1px solid $border; border-radius: 12px; }
QFrame#poprow:hover { background-color: $hover; border: 1px solid $hover_border; }
QFrame#poprow[selected="true"] { background-color: $selected; border: 1px solid $accent; }
QLineEdit, QTextEdit, QComboBox {
    background-color: $field; color: $text; border: 1px solid $border;
    border-radius: 10px; padding: 10px 12px; selection-background-color: $selection;
    selection-color: $on_selection;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid $accent; }
QLineEdit::placeholder { color: $muted; }
QPushButton { border: 0; color: $text; border-radius: 10px; padding: 10px 13px; background-color: $button; }
QPushButton:hover { background-color: $button_hover; }
QPushButton:pressed { background-color: $button_pressed; }
QPushButton#primary { background-color: $accent; color: $on_accent; font-weight: 700; }
QPushButton#primary:hover { background-color: $accent2; color: $on_accent_hover; }
QPushButton#nav { background: transparent; color: $muted; text-align: left; padding: 12px 13px; }
QPushButton#nav:hover { background: $hover; color: $text; }
QPushButton#nav[active="true"] { background: $nav_active; color: $accent2; border-left: 3px solid $accent; }
QPushButton#ghost { background: $field; border: 1px solid $border; }
QPushButton#danger { background-color: $danger; color: $on_danger; font-weight: 700; }
QPushButton#danger:hover { background-color: $danger_hover; color: $on_danger; }
QPushButton#tiny { background: transparent; border: 1px solid $border; padding: 7px; }
QPushButton#tiny:hover { background: $button_hover; }
QPushButton#chip { background: transparent; color: $muted; border: 1px solid $border; padding: 6px 11px; border-radius: 10px; }
QPushButton#chip:hover { background: $hover; color: $text; }
QPushButton#chip[active="true"] { background: $nav_active; color: $accent2; border: 1px solid $accent; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0; }
QScrollBar:vertical { background: $surface; width: 7px; border: 0; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 3px; min-height: 40px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QComboBox QAbstractItemView { background: $card; color: $text; selection-background-color: $selection; }
QToolTip { color: $text; background-color: $tooltip; border: 1px solid $border; padding: 5px; }
""")


def style_for(colors: dict[str, str]) -> str:
    return QSS.substitute(colors)
