#!/usr/bin/env python3
"""keypassXD — interface desktop local para cofres KDBX.

A interface roda fora do omarchy-shell; nenhum segredo é enviado pelo bar-widget.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import sys
import time

# Permite executar como script (launch.sh → app/main.py) ou como módulo,
# tanto na pasta de desenvolvimento quanto na cópia instalada do plugin.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QEvent, QTimer, Qt, QSize, QByteArray
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QVBoxLayout,
    QWidget, QTextEdit, QSizePolicy, QInputDialog,
)

from filters import filter_records
from generator import generate_password
from theme import read_active_theme
from styles import style_for
from vault import VAULT_DIR, VAULT_PATH, Vault

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "assets" / "icons"
# Paleta global (somente cores; nenhum segredo é guardado aqui).
# Inicializada antes de criar os widgets e atualizada no lugar ao trocar o tema.
COLORS: dict[str, str] = {}


def icon(name: str, size: int = 20, role: str = "muted") -> QIcon:
    """Coloriza os 22 SVGs locais usando o tema corrente, nunca um ícone remoto."""
    svg = (ICONS / f"{name}.svg").read_bytes()
    stroke = COLORS.get(role, COLORS.get("muted", "#aaaaaa"))
    svg = svg.replace(b'stroke="#A7B4CC"', f'stroke="{stroke}"'.encode("ascii"))
    renderer = QSvgRenderer(QByteArray(svg))
    image = QPixmap(size, size)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return QIcon(image)


def icon_label(name: str, size: int, role: str = "accent") -> QLabel:
    item = QLabel()
    item.setProperty("themeIcon", name)
    item.setProperty("themeIconSize", size)
    item.setProperty("themeIconRole", role)
    item.setPixmap(icon(name, size, role).pixmap(size, size))
    return item


def text_label(text: str, size: int = 13, color: str = "text", bold: bool = False) -> QLabel:
    item = QLabel(text)
    item.setTextFormat(Qt.TextFormat.PlainText)
    item.setWordWrap(True)
    f = QFont("Inter", size)
    f.setBold(bold)
    item.setFont(f)
    item.setProperty("themeTextRole", color)
    item.setStyleSheet(f"color: {COLORS.get(color, color)}; background: transparent;")
    return item


def btn(label: str = "", picture: str | None = None, role: str = "ghost", min_width: int = 0) -> QPushButton:
    button = QPushButton(label)
    button.setObjectName(role)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if picture:
        tint = "on_accent" if role in ("primary", "danger") else "muted"
        button.setProperty("themeIcon", picture)
        button.setProperty("themeIconRole", tint)
        button.setIcon(icon(picture, 19, tint))
        button.setIconSize(QSize(19, 19))
    if min_width:
        button.setMinimumWidth(min_width)
    return button


def recolor_widgets() -> None:
    """Recolore também componentes visíveis nos diálogos e na lista atual."""
    app = QApplication.instance()
    if app is None:
        return
    for root in app.topLevelWidgets():
        for widget in [root, *root.findChildren(QWidget)]:
            if isinstance(widget, QLabel):
                text_role = widget.property("themeTextRole")
                if text_role is not None:
                    color = COLORS.get(text_role, text_role)
                    widget.setStyleSheet(f"color: {color}; background: transparent;")
                glyph = widget.property("themeIcon")
                if glyph:
                    n = int(widget.property("themeIconSize"))
                    widget.setPixmap(icon(glyph, n, widget.property("themeIconRole") or "accent").pixmap(n, n))
            elif isinstance(widget, QPushButton):
                glyph = widget.property("themeIcon")
                if glyph:
                    role = widget.property("themeIconRole") or "muted"
                    widget.setIcon(icon(glyph, widget.iconSize().width(), role))


def clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear(item.layout())


def copy_secret(value: str) -> None:
    """Copia senha com dica de segredo e limpeza automática em 20 s.
    Cobre Clipboard e Selection (Wayland/X11)."""
    from PySide6.QtCore import QMimeData
    mime = QMimeData()
    mime.setText(value)
    # Indício para gerenciadores compatíveis. NÃO é garantia de exclusão do histórico.
    mime.setData("x-kde-passwordManagerHint", b"secret")
    QGuiApplication.clipboard().setMimeData(mime)
    QTimer.singleShot(20000, lambda copied=value: clear_clipboard_value(copied))


def clear_clipboard_value(copied: str) -> None:
    """Limpa o clipboard só se ainda contiver a senha copiada."""
    from PySide6.QtGui import QClipboard
    clipboard = QGuiApplication.clipboard()
    try:
        if clipboard.text() == copied:
            clipboard.clear()
        # Wayland/X11 têm área primária (Selection) separada: tenta limpar
        # também para não deixar a senha colada em seleção de texto.
        try:
            if clipboard.text(QClipboard.Mode.Selection) == copied:
                clipboard.clear(QClipboard.Mode.Selection)
        except Exception:
            pass
    except Exception:
        pass


def ensure_unlocked(parent, vault: Vault, on_success=None) -> bool:
    """Loop de desbloqueio/criação do cofre, compartilhado pela tela cheia e
    pelo popup. Retorna True se o cofre ficou aberto (chamando on_success),
    False se o usuário cancelou (fechando o parent, como a MainWindow faz)."""
    while True:
        creating = not vault.exists()
        dlg = MasterDialog(creating, parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            if not vault.unlocked:
                parent.close()
            return False
        password = dlg.password.text()
        try:
            if creating:
                vault.create(password)
            else:
                vault.unlock(password)
        except Exception as exc:
            print(f"keypassXD: falha ao abrir o cofre: {type(exc).__name__}", file=sys.stderr)
            QMessageBox.warning(parent, "Não foi possível abrir o cofre",
                                "Verifique a senha e tente novamente.\n"
                                "Nenhum dado foi alterado.")
            continue
        finally:
            # Reduz a vida da senha mestra em RAM: limpa o diálogo e
            # descarta a cópia Python o quanto antes (sem garantia de
            # wipe — limitação conhecida de CPython/Qt).
            try:
                del password
            except UnboundLocalError:
                pass
            dlg.password.clear()
            if dlg.confirm:
                dlg.confirm.clear()
        if on_success is not None:
            on_success()
        return True


class MasterDialog(QDialog):
    def __init__(self, creating: bool, parent=None):
        super().__init__(parent)
        self.creating = creating
        self.setWindowTitle("keypassXD · " + ("Criar cofre" if creating else "Desbloquear cofre"))
        self.setMinimumWidth(460)
        self.setModal(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 32, 32, 28)
        outer.setSpacing(16)
        header = QHBoxLayout()
        emblem = icon_label("shield-key", 46)
        header.addWidget(emblem)
        top = QVBoxLayout()
        top.addWidget(text_label("Seu espaço privado", 20, bold=True))
        top.addWidget(text_label("Cofre local criptografado no formato KDBX", 10, "muted"))
        header.addLayout(top, 1)
        outer.addLayout(header)
        outer.addSpacing(10)
        outer.addWidget(text_label("Criar senha mestra" if creating else "Senha mestra", 13, bold=True))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Digite sua senha mestra")
        outer.addWidget(self.password)
        self.confirm = None
        if creating:
            outer.addWidget(text_label("Repita a senha mestra", 13, bold=True))
            self.confirm = QLineEdit()
            self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm.setPlaceholderText("Confirme a senha mestra")
            outer.addWidget(self.confirm)
            outer.addWidget(text_label("Use 14 caracteres ou mais. Sem recuperação: faça backup do arquivo .kdbx.", 11, "muted"))
        else:
            outer.addWidget(text_label("A senha mestra não é armazenada em arquivo separado.", 11, "muted"))
        buttons = QHBoxLayout()
        cancel = btn("Cancelar")
        cancel.clicked.connect(self.reject)
        submit = btn("Criar cofre" if creating else "Desbloquear", "lock", "primary")
        submit.clicked.connect(self.validate)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        buttons.addWidget(submit)
        outer.addLayout(buttons)
        self.password.returnPressed.connect(self.validate if not creating else self.confirm.setFocus)
        if self.confirm:
            self.confirm.returnPressed.connect(self.validate)

    def validate(self):
        pw = self.password.text()
        if not pw:
            QMessageBox.warning(self, "Senha obrigatória", "Digite a senha mestra.")
            return
        if self.creating and (len(pw) < 11 or pw != self.confirm.text()):
            QMessageBox.warning(self, "Senha inválida", "Use ao menos 11 caracteres e confirme a mesma senha.")
            return
        self.accept()


class EntryDialog(QDialog):
    def __init__(self, folders: list[str], item: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("keypassXD · " + ("Editar entrada" if item else "Nova senha"))
        self.setMinimumWidth(520)
        self.setModal(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(27, 27, 27, 25)
        root.setSpacing(14)
        root.addWidget(text_label("Editar credencial" if item else "Adicionar credencial", 21, bold=True))
        root.addWidget(text_label("Todos os dados serão salvos no cofre criptografado.", 11, "muted"))
        fields = QFormLayout()
        fields.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        fields.setHorizontalSpacing(22)
        fields.setVerticalSpacing(14)
        self.title_field = QLineEdit(item["title"] if item else "")
        self.title_field.setPlaceholderText("Ex.: GitHub")
        fields.addRow("Serviço", self.title_field)
        self.user_field = QLineEdit(item["username"] if item else "")
        self.user_field.setPlaceholderText("Usuário ou e-mail")
        fields.addRow("Usuário", self.user_field)
        self.password_field = QLineEdit()
        self.password_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_field.setPlaceholderText("Deixe vazio para manter" if item else "Crie ou gere uma senha")
        password_controls = QHBoxLayout()
        password_controls.setSpacing(6)
        password_controls.addWidget(self.password_field, 1)
        show = btn("", "eye", "tiny")
        show.setToolTip("Mostrar/ocultar senha")
        show.clicked.connect(lambda: self.password_field.setEchoMode(
            QLineEdit.EchoMode.Normal if self.password_field.echoMode() == QLineEdit.EchoMode.Password
            else QLineEdit.EchoMode.Password))
        password_controls.addWidget(show)
        generate = btn("Gerar", "refresh", "ghost")
        generate.clicked.connect(lambda: self.password_field.setText(generate_password()))
        password_controls.addWidget(generate)
        fields.addRow("Senha", password_controls)
        self.url_field = QLineEdit(item["url"] if item else "")
        self.url_field.setPlaceholderText("https://exemplo.com")
        fields.addRow("Website", self.url_field)
        self.folder = QComboBox()
        self.folder.addItems(["Geral"] + folders)
        if item:
            found = self.folder.findText(item["group"])
            if found >= 0:
                self.folder.setCurrentIndex(found)
        fields.addRow("Pasta", self.folder)
        self.notes = QTextEdit()
        self.notes.setFixedHeight(92)
        self.notes.setPlaceholderText("Notas opcionais")
        self.notes.setPlainText(item["notes"] if item else "")
        fields.addRow("Notas", self.notes)
        root.addLayout(fields)
        controls = QHBoxLayout()
        close = btn("Cancelar")
        close.clicked.connect(self.reject)
        save = btn("Salvar no cofre", "check", "primary")
        save.clicked.connect(self.validate)
        controls.addWidget(close)
        controls.addStretch(1)
        controls.addWidget(save)
        root.addLayout(controls)

    def validate(self):
        if not self.title_field.text().strip():
            QMessageBox.warning(self, "Falta o serviço", "Informe o nome do serviço.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "title": self.title_field.text().strip(),
            "username": self.user_field.text().strip(),
            "password": self.password_field.text(),
            "url": self.url_field.text().strip(),
            "group": self.folder.currentText(),
            "notes": self.notes.toPlainText(),
        }


class ResetDialog(QDialog):
    """Confirmação do 'apagar tudo': popup centralizado onde o usuário
    digita a senha mestra e confirma. A senha é provada (verify_password)
    antes de qualquer arquivo ser destruído."""

    def __init__(self, vault: Vault, parent=None):
        super().__init__(parent)
        self.vault = vault
        self.setWindowTitle("keypassXD · Apagar tudo")
        self.setMinimumWidth(460)
        self.setModal(True)
        # Mesmo visual de popup da busca: frameless + fundo translúcido
        # + cartão arredondado, centralizado na tela (showEvent).
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Janela transparente via stylesheet global (QDialog#framelessPopup).
        self.setObjectName("framelessPopup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        card = QFrame()
        card.setObjectName("popup")
        outer.addWidget(card)
        root = QVBoxLayout(card)
        root.setContentsMargins(32, 32, 32, 28)
        root.setSpacing(16)
        header = QHBoxLayout()
        emblem = icon_label("trash", 46)
        header.addWidget(emblem)
        top = QVBoxLayout()
        top.addWidget(text_label("Apagar tudo", 20, bold=True))
        top.addWidget(text_label("Zona de perigo · irreversível", 10, "muted"))
        header.addLayout(top, 1)
        outer.addLayout(header)
        outer.addSpacing(10)
        outer.addWidget(text_label(
            "Apaga vault.kdbx + vault.backup.kdbx e recomeça do zero.\n"
            "Sem recuperação. O cofre atual não existirá mais.", 11, "muted"))
        outer.addWidget(text_label("Senha mestra", 13, bold=True))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Digite sua senha mestra")
        outer.addWidget(self.password)
        buttons = QHBoxLayout()
        cancel = btn("Cancelar")
        cancel.clicked.connect(self.reject)
        submit = btn("Apagar tudo", "trash", "danger")
        submit.clicked.connect(self.validate)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        buttons.addWidget(submit)
        outer.addLayout(buttons)
        self.password.returnPressed.connect(self.validate)

    def validate(self):
        password = self.password.text()
        if not password:
            QMessageBox.warning(self, "Senha obrigatória", "Digite a senha mestra.")
            return
        try:
            # Prova a senha antes de destruir qualquer arquivo.
            # verify_password (não change_password): senhas antigas de
            # 10–13 caracteres não devem bloquear o reset, e nenhum
            # save é necessário.
            self.vault.verify_password(password)
        except Exception:
            print("keypassXD: reset bloqueado (senha atual incorreta)", file=sys.stderr)
            QMessageBox.warning(self, "Senha incorreta",
                                "A senha mestra não confere.\nNenhum dado foi apagado.")
            self.password.clear()
            return
        finally:
            # Reduz a vida da senha mestra em RAM (limitação conhecida
            # de CPython/Qt: sem garantia de wipe).
            try:
                del password
            except UnboundLocalError:
                pass
        self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)
        self.activateWindow()


class SettingsDialog(QDialog):
    """Backup criptografado, troca de senha mestra e reset. Tudo 100% local."""

    def __init__(self, window: "MainWindow", parent=None):
        super().__init__(parent)
        self.window = window
        self.setWindowTitle("keypassXD · Configurações")
        self.setMinimumWidth(540)
        self.setModal(True)
        # Popup centralizado (sem janela em foco), igual ao popup
        # de busca: frameless + fundo translúcido + cartão arredondado.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Janela transparente via stylesheet global (QDialog#framelessPopup).
        # Não usar setStyleSheet aqui: regra sem seletor vazaria para os
        # filhos e apagaria os fundos do cartão, botões e campos.
        self.setObjectName("framelessPopup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        card = QFrame()
        card.setObjectName("popup")
        outer.addWidget(card)
        root = QVBoxLayout(card)
        root.setContentsMargins(27, 27, 27, 25)
        root.setSpacing(14)
        root.addWidget(text_label("Configurações", 21, bold=True))
        root.addWidget(text_label("Tudo neste diálogo é 100% local e criptografado.", 11, "muted"))

        root.addWidget(text_label("BACKUP CRIPTOGRAFADO", 10, "muted", True))
        root.addWidget(text_label("Copia o .kdbx com a mesma senha mestra. Importar substitui o cofre atual com backup automático.", 11, "muted"))
        backup_row = QHBoxLayout()
        backup_row.setSpacing(8)
        export = btn("Exportar backup", "export")
        export.clicked.connect(window.export_backup)
        backup_row.addWidget(export, 1)
        imp = btn("Importar backup", "import")
        imp.clicked.connect(self._import_and_close)
        backup_row.addWidget(imp, 1)
        root.addLayout(backup_row)

        root.addWidget(text_label("TROCAR SENHA MESTRA", 10, "muted", True))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.current_pw = QLineEdit()
        self.current_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.current_pw.setPlaceholderText("Senha mestra atual")
        form.addRow("Atual", self.current_pw)
        self.new_pw = QLineEdit()
        self.new_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pw.setPlaceholderText("Nova senha (14+ caracteres)")
        form.addRow("Nova", self.new_pw)
        self.confirm_pw = QLineEdit()
        self.confirm_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_pw.setPlaceholderText("Repita a nova senha")
        form.addRow("Confirmar", self.confirm_pw)
        root.addLayout(form)
        change = btn("Alterar senha mestra", "key", "primary")
        change.clicked.connect(self._change_password)
        root.addWidget(change)

        root.addWidget(text_label("ZONA DE PERIGO", 10, "muted", True))
        root.addWidget(text_label("Apaga vault.kdbx + vault.backup.kdbx e recomeça do zero. Sem recuperação.", 11, "muted"))
        reset = btn("Apagar tudo e recomeçar", "trash", "danger")
        reset.setToolTip("Confirme com a senha mestra")
        reset.clicked.connect(self._confirm_reset)
        root.addWidget(reset)

        close = btn("Fechar")
        close.clicked.connect(self.accept)
        root.addWidget(close)

    def _import_and_close(self):
        self.window.import_backup()
        if self.window.vault.unlocked and self.window.records:
            self.accept()

    def _wipe(self, *fields: QLineEdit):
        for field in fields:
            try:
                field.clear()
            except RuntimeError:
                pass

    def _change_password(self):
        current = self.current_pw.text()
        new = self.new_pw.text()
        confirm = self.confirm_pw.text()
        try:
            if not new or len(new) < 11 or new != confirm:
                QMessageBox.warning(self, "Senha inválida",
                                    "A nova senha precisa de 11+ caracteres e confirmação igual.")
                return
            self.window.vault.change_password(current, new)
            self.window._last_activity = time.monotonic()
            self.window.message("Senha mestra alterada")
            QMessageBox.information(self, "Senha alterada",
                                    "Senha mestra atualizada.\nUse a nova senha no próximo desbloqueio.")
        except Exception as exc:
            print(f"keypassXD: falha ao trocar senha: {type(exc).__name__}", file=sys.stderr)
            QMessageBox.warning(self, "Não foi possível trocar a senha",
                                "Verifique a senha atual e tente novamente.\n"
                                "Nenhum dado foi alterado.")
            return
        finally:
            try:
                del current, new, confirm
            except UnboundLocalError:
                pass
            self._wipe(self.current_pw, self.new_pw, self.confirm_pw)

    def showEvent(self, event):
        super().showEvent(event)
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)
        self.activateWindow()

    def _confirm_reset(self):
        """Abre o popup de confirmação (senha + 'Apagar tudo')."""
        dlg = ResetDialog(self.window.vault, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.window.reset_vault()
            self.accept()


class ClickableCard(QFrame):
    """Card de credencial — nenhum campo de senha é carregado aqui."""
    def __init__(self, item: dict, selected: bool, callback):
        super().__init__()
        self.item = item
        self.setObjectName("row")
        self.setProperty("selected", selected)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 14, 11, 14)
        layout.setSpacing(13)
        tile = QFrame()
        tile.setObjectName("tile")
        tile.setFixedSize(45, 45)
        tile_l = QVBoxLayout(tile)
        tile_l.setContentsMargins(0, 0, 0, 0)
        tile_icon = icon_label("globe", 22)
        tile_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile_l.addWidget(tile_icon)
        layout.addWidget(tile)
        names = QVBoxLayout()
        names.setSpacing(3)
        title = text_label(item["title"], 12, bold=True)
        title.setMaximumHeight(22)
        names.addWidget(title)
        subtitle = text_label(item["username"] or item["group"], 10, "muted")
        subtitle.setMaximumHeight(19)
        names.addWidget(subtitle)
        layout.addLayout(names, 1)
        if item["favorite"]:
            star = icon_label("star", 15)
            layout.addWidget(star)
        chevron = icon_label("chevron-right", 15, "muted")
        layout.addWidget(chevron)
        self.callback = callback

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.callback(self.item["uuid"])
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    LOCK_AFTER_SECONDS = 300

    def __init__(self, active_theme, vault: Vault | None = None):
        super().__init__()
        self.setWindowTitle("keypassXD · Meu cofre")
        self.resize(1210, 775)
        self.setMinimumSize(1000, 650)
        self.vault = vault if vault is not None else Vault()
        self.records: list[dict] = []
        self.selected_uuid: str | None = None
        self.view = "all"
        self._last_activity = time.monotonic()
        self._reveal_uuid: str | None = None
        self._authenticating = False
        self._active_theme = active_theme
        self._build()
        self.theme_info.setText("Tema: " + self._active_theme.name)
        # O Omarchy substitui o diretório theme atomicamente. Consultar a cada
        # 1,5 s detecta a troca mesmo quando um QFileSystemWatcher perderia o inode.
        self.theme_timer = QTimer(self)
        self.theme_timer.setInterval(1500)
        self.theme_timer.timeout.connect(self._check_theme)
        self.theme_timer.start()
        self.inactivity = QTimer(self)
        self.inactivity.timeout.connect(self._check_lock)
        self.inactivity.start(10000)
        app = QApplication.instance()
        app.installEventFilter(self)
        # Trava também ao suspender/ocultar a sessão (tela bloqueada, troca de
        # usuário): além do bloqueio por minimize e por 5 min de inatividade.
        try:
            app.applicationStateChanged.connect(self._on_app_state)
        except (AttributeError, RuntimeError):
            pass
        QTimer.singleShot(0, self.unlock)

    def _on_app_state(self, state) -> None:
        try:
            from PySide6.QtCore import Qt as _Qt
            if state == _Qt.ApplicationState.ApplicationSuspended and self.vault.unlocked:
                self.lock(prompt=False)
        except Exception:
            pass

    def _check_theme(self):
        updated = read_active_theme()
        if updated.identity == self._active_theme.identity:
            return
        self._active_theme = updated
        COLORS.clear()
        COLORS.update(updated.colors)
        QApplication.instance().setStyleSheet(style_for(COLORS))
        QApplication.instance().setWindowIcon(icon("shield-key", 64))
        self.theme_info.setText("Tema: " + updated.name)
        recolor_widgets()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress,
                            QEvent.Type.MouseMove, QEvent.Type.Wheel):
            if QApplication.activeWindow() is not None:
                self._last_activity = time.monotonic()
        return super().eventFilter(obj, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized() and self.vault.unlocked:
                self.lock(prompt=False)
            elif not self.isMinimized() and not self.vault.unlocked and not self._authenticating:
                QTimer.singleShot(0, self._initial_unlock)

    def _initial_unlock(self):
        # Veio do popup com o cofre já aberto: apenas atualiza a interface.
        if self.vault.unlocked:
            self._last_activity = time.monotonic()
            self.refresh()
            return
        self.unlock()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        body = QHBoxLayout(central)
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(238)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(20, 29, 20, 24)
        side.setSpacing(10)
        brand = QHBoxLayout()
        brand_icon = icon_label("shield-key", 35)
        brand.addWidget(brand_icon)
        brand_title = QVBoxLayout()
        brand_title.setSpacing(0)
        brand_title.addWidget(text_label("keypassXD", 19, bold=True))
        brand_title.addWidget(text_label("PASSWORD VAULT", 9, "accent"))
        brand.addLayout(brand_title)
        brand.addStretch()
        side.addLayout(brand)
        side.addSpacing(37)
        side.addWidget(text_label("BIBLIOTECA", 9, "muted", True))
        self.nav_buttons = {}
        for key, name, glyph in (("all", "Todas as senhas", "grid"),
                                 ("favorites", "Favoritos", "star"),
                                 ("recent", "Recentes", "refresh")):
            button = btn(name, glyph, "nav")
            button.setProperty("active", key == "all")
            button.clicked.connect(lambda checked=False, k=key: self.change_view(k))
            self.nav_buttons[key] = button
            side.addWidget(button)
        side.addSpacing(22)
        sections = QHBoxLayout()
        sections.addWidget(text_label("PASTAS", 9, "muted", True))
        sections.addStretch()
        new_folder = btn("", "plus", "tiny")
        new_folder.setToolTip("Criar pasta")
        new_folder.setFixedSize(28, 28)
        new_folder.clicked.connect(self.new_folder)
        sections.addWidget(new_folder)
        side.addLayout(sections)
        self.folder_box = QVBoxLayout()
        self.folder_box.setSpacing(2)
        side.addLayout(self.folder_box)
        side.addStretch(1)
        foot = QFrame()
        foot.setObjectName("protection")
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(13, 17, 13, 16)
        fl.setSpacing(8)
        fl.addWidget(text_label("PROTEÇÃO LOCAL", 9, "accent", True))
        fl.addWidget(text_label("Cofre KDBX criptografado", 11, bold=True))
        fl.addWidget(text_label("Bloqueio após 5 min sem atividade", 10, "muted"))
        self.kdf_info = text_label("KDF: Argon2id · 100% local", 10, "muted")
        fl.addWidget(self.kdf_info)
        self.theme_info = text_label("Tema Omarchy · automático", 10, "muted")
        fl.addWidget(self.theme_info)
        side.addWidget(foot)
        self.lock_btn = btn("Bloquear cofre", "lock", "ghost")
        self.lock_btn.clicked.connect(lambda: self.lock())
        side.addWidget(self.lock_btn)
        self.settings_btn = btn("Configurações", "settings", "ghost")
        self.settings_btn.setToolTip("Backup criptografado, senha mestra e reset")
        self.settings_btn.clicked.connect(self.open_settings)
        side.addWidget(self.settings_btn)
        body.addWidget(self.sidebar)

        self.middle = QFrame()
        self.middle.setObjectName("middle")
        self.middle.setMinimumWidth(355)
        middle = QVBoxLayout(self.middle)
        middle.setContentsMargins(24, 30, 24, 18)
        middle.setSpacing(17)
        header = QHBoxLayout()
        h = QVBoxLayout()
        h.addWidget(text_label("Meu cofre", 25, bold=True))
        self.total = text_label("Desbloqueie para visualizar", 11, "muted")
        h.addWidget(self.total)
        header.addLayout(h)
        header.addStretch()
        middle.addLayout(header)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar serviços, URLs, usuários...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.render_list)
        middle.addWidget(self.search)
        add = btn("Adicionar senha", "plus", "primary")
        add.setMinimumHeight(43)
        add.clicked.connect(self.add_entry)
        middle.addWidget(add)
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        middle.addWidget(self.list_scroll, 1)
        self.status = text_label("Dados armazenados apenas neste computador", 10, "muted")
        middle.addWidget(self.status)
        body.addWidget(self.middle, 5)

        self.detail = QFrame()
        self.detail.setObjectName("detail")
        self.detail.setMinimumWidth(382)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(30, 33, 30, 22)
        self.detail_content = QVBoxLayout()
        self.detail_content.setSpacing(16)
        detail_layout.addLayout(self.detail_content, 1)
        body.addWidget(self.detail, 6)
        self.show_placeholder()

    def message(self, text: str):
        self.status.setText(text)
        QTimer.singleShot(4500, lambda: self.status.setText("Armazenamento local · Formato KDBX"))

    def unlock(self):
        if self._authenticating:
            return

        def _ready() -> None:
            self._last_activity = time.monotonic()
            self.refresh()

        self._authenticating = True
        try:
            success = ensure_unlocked(self, self.vault, _ready)
        finally:
            self._authenticating = False
        if not success:
            QApplication.instance().quit()

    def lock(self, prompt: bool = True):
        if not self.vault.unlocked:
            return
        self._clear_password_display()
        self.records = []
        self.selected_uuid = None
        self.vault.lock()
        self.search.clear()
        self.total.setText("Cofre bloqueado")
        try:
            self.kdf_info.setText("KDF: Argon2id · 100% local")
        except AttributeError:
            pass
        self.render_list()
        self.show_placeholder("Cofre bloqueado", "Desbloqueie com sua senha mestra para continuar.")
        if prompt:
            QTimer.singleShot(0, self.unlock)

    def _check_lock(self):
        if self.vault.unlocked and time.monotonic() - self._last_activity >= self.LOCK_AFTER_SECONDS:
            self.lock()

    def refresh(self, select: str | None = None):
        self.records = self.vault.entries() if self.vault.unlocked else []
        self.total.setText(f"{len(self.records)} credenciais em segurança")
        try:
            info = self.vault.kdf_status()
            algo = str(info.get("algorithm", "argon2id"))
            self.kdf_info.setText(f"KDF: {algo} · 100% local")
        except Exception:
            pass
        self.render_folders()
        if select:
            self.selected_uuid = select
        if self.selected_uuid and not any(x["uuid"] == self.selected_uuid for x in self.records):
            self.selected_uuid = None
        self.render_list()
        self.show_detail()

    def render_folders(self):
        clear(self.folder_box)
        if not self.vault.unlocked:
            return
        for folder in self.vault.groups():
            row = QFrame()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            button = btn(folder, "folder", "nav")
            button.setProperty("active", self.view == "group:" + folder)
            button.clicked.connect(lambda checked=False, f=folder: self.change_view("group:" + f))
            row_layout.addWidget(button, 1)
            remove = btn("", "trash", "tiny")
            remove.setToolTip("Apagar pasta")
            remove.setFixedSize(28, 28)
            remove.clicked.connect(lambda checked=False, f=folder: self.delete_folder(f))
            row_layout.addWidget(remove)
            self.folder_box.addWidget(row)

    def change_view(self, view: str):
        if not self.vault.unlocked:
            return
        self.view = view
        for key, button in self.nav_buttons.items():
            button.setProperty("active", key == view)
            button.style().unpolish(button)
            button.style().polish(button)
        self.render_folders()
        self.render_list()

    def render_list(self):
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(0, 2, 0, 10)
        layout.setSpacing(10)
        if self.vault.unlocked:
            query = self.search.text()
            items = filter_records(self.records, query)
            if self.view == "favorites":
                items = [r for r in items if r["favorite"]]
            elif self.view.startswith("group:"):
                items = [r for r in items if r["group"] == self.view[6:]]
            elif self.view == "recent":
                items = sorted(items, key=lambda r: r["modified"], reverse=True)
        else:
            items = []
        if not items:
            layout.addSpacing(75)
            msg = text_label("Nenhuma credencial encontrada" if self.vault.unlocked else "Cofre protegido", 14, "muted")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(msg)
        for entry in items:
            layout.addWidget(ClickableCard(entry, entry["uuid"] == self.selected_uuid, self.select))
        layout.addStretch(1)
        self.list_scroll.setWidget(outer)

    def select(self, uuid: str):
        if not self.vault.unlocked:
            return
        self._clear_password_display()
        self.selected_uuid = uuid
        self.render_list()
        self.show_detail()

    def show_placeholder(self, heading="Selecione uma credencial", subtitle="Escolha um item na lista para visualizar seus detalhes."):
        self.password_view = None
        clear(self.detail_content)
        self.detail_content.addStretch(1)
        symbol = icon_label("shield-key", 64)
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_content.addWidget(symbol)
        heading_label = text_label(heading, 20, bold=True)
        heading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_content.addWidget(heading_label)
        sub = text_label(subtitle, 11, "muted")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_content.addWidget(sub)
        self.detail_content.addStretch(2)

    def show_detail(self):
        self._reveal_uuid = None
        if not self.selected_uuid or not self.vault.unlocked:
            self.show_placeholder()
            return
        item = next((r for r in self.records if r["uuid"] == self.selected_uuid), None)
        if item is None:
            self.show_placeholder()
            return
        clear(self.detail_content)
        self.detail_content.addWidget(text_label("DETALHES DA CREDENCIAL", 9, "muted", True))
        self.detail_content.addSpacing(16)
        emblem = icon_label("globe", 54)
        emblem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_content.addWidget(emblem)
        name = text_label(item["title"], 23, bold=True)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_content.addWidget(name)
        folder = text_label(item["group"], 11, "accent")
        folder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_content.addWidget(folder)
        self.detail_content.addSpacing(22)
        self.detail_content.addWidget(text_label("USUÁRIO", 10, "muted", True))
        user_row = QHBoxLayout()
        user_row.addWidget(text_label(item["username"] or "Não informado", 13), 1)
        copy_user = btn("", "copy", "tiny")
        copy_user.setToolTip("Copiar usuário")
        copy_user.clicked.connect(lambda: self.copy_value(item["username"], False))
        user_row.addWidget(copy_user)
        self.detail_content.addLayout(user_row)
        self.detail_content.addSpacing(8)
        self.detail_content.addWidget(text_label("SENHA", 10, "muted", True))
        password_row = QHBoxLayout()
        self.password_view = text_label("••••••••••••••••", 16)
        password_row.addWidget(self.password_view, 1)
        self.eye = btn("", "eye", "tiny")
        self.eye.setToolTip("Mostrar por 12 segundos")
        self.eye.clicked.connect(self.toggle_reveal)
        password_row.addWidget(self.eye)
        copy_pass = btn("", "copy", "tiny")
        copy_pass.setToolTip("Copiar senha por 20 segundos")
        copy_pass.clicked.connect(self.copy_password)
        password_row.addWidget(copy_pass)
        self.detail_content.addLayout(password_row)
        self.detail_content.addWidget(text_label("ÁREA DE TRANSFERÊNCIA: expira em 20 segundos", 9, "muted"))
        self.detail_content.addSpacing(10)
        self.detail_content.addWidget(text_label("WEBSITE", 10, "muted", True))
        self.detail_content.addWidget(text_label(item["url"] or "Não informado", 12))
        if item["notes"]:
            self.detail_content.addSpacing(10)
            self.detail_content.addWidget(text_label("NOTAS", 10, "muted", True))
            notes = text_label(item["notes"], 11)
            notes.setMaximumHeight(110)
            self.detail_content.addWidget(notes)
        self.detail_content.addStretch(1)
        actions1 = QHBoxLayout()
        favorite = btn("Remover favorito" if item["favorite"] else "Favoritar", "star")
        favorite.clicked.connect(lambda: self.toggle_favorite(item["uuid"], not item["favorite"]))
        edit = btn("Editar", "edit")
        edit.clicked.connect(self.edit_entry)
        actions1.addWidget(favorite, 1)
        actions1.addWidget(edit, 1)
        self.detail_content.addLayout(actions1)
        delete = btn("Excluir credencial", "trash", "danger")
        delete.clicked.connect(self.delete_entry)
        self.detail_content.addWidget(delete)

    def _clear_password_display(self):
        self._reveal_uuid = None
        if getattr(self, "password_view", None) is not None:
            try:
                self.password_view.setText("••••••••••••••••")
            except RuntimeError:
                self.password_view = None  # Widget Qt já destruído.

    def toggle_reveal(self):
        if not self.selected_uuid or not self.vault.unlocked:
            return
        if self._reveal_uuid == self.selected_uuid:
            self._clear_password_display()
            return
        try:
            self.password_view.setText(self.vault.get_password(self.selected_uuid))
            self._reveal_uuid = self.selected_uuid
            uuid = self.selected_uuid
            QTimer.singleShot(12000, lambda: self._clear_password_display() if self._reveal_uuid == uuid else None)
        except Exception as exc:
            self.error(exc)

    def copy_value(self, value: str, secret: bool = False):
        if not value:
            self.message("Este campo está vazio")
            return
        if secret:
            copy_secret(value)
            self.message("Senha copiada. A limpeza será tentada em 20 s.")
        else:
            from PySide6.QtCore import QMimeData
            mime = QMimeData()
            mime.setText(value)
            QGuiApplication.clipboard().setMimeData(mime)
            self.message("Usuário copiado para a área de transferência")

    def copy_password(self):
        if not self.vault.unlocked or not self.selected_uuid:
            return
        try:
            self.copy_value(self.vault.get_password(self.selected_uuid), True)
        except Exception as exc:
            self.error(exc)

    def add_entry(self):
        if not self.vault.unlocked:
            return
        dialog = EntryDialog(self.vault.groups(), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                uid = self.vault.upsert(None, dialog.values())
                self.refresh(uid)
                self.message("Credencial salva no cofre")
            except Exception as exc:
                self.error(exc)

    def edit_entry(self):
        if not self.selected_uuid or not self.vault.unlocked:
            return
        current = next((r for r in self.records if r["uuid"] == self.selected_uuid), None)
        if not current:
            return
        dialog = EntryDialog(self.vault.groups(), item=current, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                uid = self.vault.upsert(self.selected_uuid, dialog.values())
                self._clear_password_display()
                self.refresh(uid)
                self.message("Credencial atualizada")
            except Exception as exc:
                self.error(exc)

    def toggle_favorite(self, uuid: str, state: bool):
        try:
            self.vault.set_favorite(uuid, state)
            self.refresh(uuid)
        except Exception as exc:
            self.error(exc)

    def delete_entry(self):
        if not self.selected_uuid:
            return
        answer = QMessageBox.question(self, "Excluir credencial",
                                      "Excluir esta credencial permanentemente do cofre?\n"
                                      "Uma cópia criptografada da versão anterior ficará no backup.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.vault.delete(self.selected_uuid)
            self.selected_uuid = None
            self.refresh()
            self.message("Credencial excluída")
        except Exception as exc:
            self.error(exc)

    def new_folder(self):
        if not self.vault.unlocked:
            return
        name, ok = QInputDialog.getText(self, "Nova pasta", "Nome da pasta:")
        if not ok:
            return
        try:
            self.vault.add_group(name)
            self.refresh()
            self.change_view("group:" + name.strip())
        except Exception as exc:
            self.error(exc)

    def delete_folder(self, folder: str):
        """Apaga uma pasta. Pergunta antes o que fazer com as senhas dentro:
        mover para "Geral" (padrão, sem perda) ou apagar tudo (permanente)."""
        if not self.vault.unlocked:
            return
        count = sum(1 for r in self.records if r["group"] == folder)
        if count:
            box = QMessageBox(self)
            box.setWindowTitle("Apagar pasta")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f'A pasta "{folder}" tem {count} credencial(is).')
            box.setInformativeText(
                'Mover para "Geral" não apaga nenhuma senha.\n'
                '"Apagar tudo" é permanente e não há recuperação; '
                "a versão anterior do cofre fica em vault.backup.kdbx.")
            move_btn = box.addButton(
                f"Mover {count} credencial(is) para Geral", QMessageBox.ButtonRole.AcceptRole)
            trash_btn = box.addButton("Apagar tudo", QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(move_btn)
            box.exec()
            clicked = box.clickedButton()
            if clicked is None or clicked is cancel_btn:
                return
            delete_entries = clicked is trash_btn
        else:
            answer = QMessageBox.question(
                self, "Apagar pasta",
                f'Apagar a pasta "{folder}"?\nEla está vazia; nenhuma senha será afetada.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            delete_entries = False
        try:
            self.vault.delete_group(folder, delete_entries)
        except Exception as exc:
            self.error(exc)
            return
        if self.view == "group:" + folder:
            self.view = "all"
        self.refresh()
        if count and not delete_entries:
            self.message(f'Pasta "{folder}" apagada; {count} credencial(is) movida(s) para Geral')
        else:
            self.message(f'Pasta "{folder}" apagada')

    def open_settings(self):
        """Abre o diálogo de Configurações com backup, troca de senha e reset."""
        dlg = SettingsDialog(self)
        dlg.exec()

    def reset_vault(self):
        """Reseta o cofre atual: apaga todos os dados e recomeça do zero."""
        try:
            self.vault.reset()
            self.records = []
            self.selected_uuid = None
            self.view = "all"
            self.render_list()
            self.show_placeholder("Cofre vazio", "Adicione sua primeira credencial.")
            self._last_activity = time.monotonic()
            self.message("Cofre reiniciado — recomece com uma nova senha mestra")
            # vault.reset() já fez self.kp = None; unlocked é property
            # somente-leitura, então não se pode atribuir. Segue direto para
            # o fluxo de desbloqueio, que cria o novo cofre.
            self.unlock()
        except Exception as exc:
            self.error(exc)

    def export_backup(self):
        """Exporta cópia criptografada .kdbx para o caminho escolhido. 100% local."""
        if not self.vault.unlocked:
            self.message("Desbloqueie o cofre para exportar")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Exportar backup criptografado",
            "keypassxd-backup.kdbx", "KeePass KDBX (*.kdbx)")
        if not dest:
            return
        try:
            self.vault.export_to(Path(dest))
            self.message("Backup criptografado exportado (mesma senha mestra)")
        except Exception as exc:
            self.error(exc)

    def import_backup(self):
        """Importa .kdbx substituindo o cofre atual, com backup automático. 100% local."""
        if not self.vault.unlocked:
            self.message("Desbloqueie o cofre para importar")
            return
        src, _ = QFileDialog.getOpenFileName(
            self, "Importar cofre criptografado",
            str(Path.home()), "KeePass KDBX (*.kdbx)")
        if not src:
            return
        answer = QMessageBox.question(
            self, "Substituir cofre?",
            "O cofre atual será substituído pelo arquivo importado.\n"
            "Uma cópia criptografada do cofre atual ficará em vault.backup.kdbx.\n"
            "Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        dlg = MasterDialog(False, self)
        dlg.setWindowTitle("keypassXD · Senha do arquivo importado")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password.text()
        try:
            self.vault.import_from(Path(src), password)
        except Exception as exc:
            print(f"keypassXD: falha ao importar: {type(exc).__name__}", file=sys.stderr)
            QMessageBox.warning(self, "Não foi possível importar",
                                "Verifique o arquivo e a senha.\n"
                                "Nenhum dado foi alterado.")
            return
        finally:
            try:
                del password
            except UnboundLocalError:
                pass
            try:
                dlg.password.clear()
            except RuntimeError:
                pass
        self._last_activity = time.monotonic()
        self.view = "all"
        self.refresh()
        self.message("Cofre importado — anterior em vault.backup.kdbx")

    def error(self, exc: Exception):
        # Mensagem genérica de propósito: detalhes de exceção podem conter
        # caminhos locais; vão para stderr, nunca para a caixa de diálogo.
        print(f"keypassXD: {type(exc).__name__}", file=sys.stderr)
        QMessageBox.warning(self, "keypassXD",
                            "Não foi possível concluir a operação.\n"
                            "Nenhum dado foi exposto; tente novamente.")


def main() -> int:
    os.umask(0o077)
    # Aplicativo de instância única, evitando duas gravações simultâneas.
    VAULT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    if VAULT_DIR.is_symlink():
        print("keypassXD: diretório de dados é um link simbólico; cancelando.", file=sys.stderr)
        return 1
    os.chmod(VAULT_DIR, 0o700)
    lock_fd = os.open(VAULT_DIR / "instance.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("keypassXD já está aberto nesta sessão.", file=sys.stderr)
        os.close(lock_fd)
        return 0
    app = QApplication(sys.argv)
    initial_theme = read_active_theme()
    COLORS.update(initial_theme.colors)
    app.setStyleSheet(style_for(COLORS))
    app.setApplicationName("keypassXD")
    # app_id estável no Wayland (sem isso a classe viraria "python" e o
    # registro no portal falharia — ver log: desktopFileName not set).
    app.setDesktopFileName("dev.keypassxd")
    app.setWindowIcon(icon("shield-key", 64))
    # Fluxo único: sempre a tela grande (criar/editar/configurações).
    vault = Vault()
    window = MainWindow(initial_theme, vault=vault)
    # Trava o cofre ao sair, inclusive por sinal de quit (além do lock
    # explícito após app.exec()).
    try:
        app.aboutToQuit.connect(vault.lock)
    except (AttributeError, RuntimeError):
        pass
    window.show()
    window.activateWindow()
    window.raise_()
    code = app.exec()
    vault.lock()
    os.close(lock_fd)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
