import QtQuick
import Quickshell
import qs.Ui

// Somente um lançador: NENHUMA senha entra no processo do omarchy-shell.
// O cofre real roda fora do shell, em processo Python próprio (launch.sh).
// 100% local: este QML não faz rede, não lê o .kdbx, só executa o lançador.
// O atalho global ALT+K vive no Service.qml (padrão Flowdeck/CoinConvert:
// hyprctl eval + hl.bind + IPC `omarchy-shell dev.keypassxd open`).
BarWidget {
    id: root
    moduleName: "dev.keypassxd"
    implicitWidth: launcher.implicitWidth
    implicitHeight: launcher.implicitHeight

    function openVault() {
        try {
            if (root.bar && root.bar.shell && typeof root.bar.shell.serviceFor === "function") {
                const svc = root.bar.shell.serviceFor(root.moduleName)
                if (svc && typeof svc.open === "function") {
                    svc.open()
                    return
                }
            }
        } catch (e) {}
        // Fallback: executa o lançador direto (mesmo que o Service faz via IPC).
        // bash -lc expande $HOME dentro de aspas duplas (aspas simples
        // impediriam a expansão e quebrariam o lançador).
        if (root.bar)
            root.bar.run('"$HOME/.config/omarchy/plugins/dev.keypassxd/launch.sh"')
    }

    BarIconButton {
        id: launcher
        anchors.fill: parent
        bar: root.bar
        // Glifo vetorial do Nerd Font (cadeado U+F023), não é emoji.
        text: "\uf023"
        tooltipText: "keypassXD · Abrir gerenciador (Alt+K)"
        onPressed: function(buttonCode) {
            if (buttonCode === Qt.LeftButton)
                root.openVault()
        }
    }
}
