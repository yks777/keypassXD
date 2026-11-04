import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

// keypassXD Service — dono do atalho global ALT+K (padrão Flowdeck/CoinConvert).
// BarWidget é só um lançador; o cofre real roda fora do omarchy-shell em
// processo Python próprio (launch.sh). 100% local: este QML não faz rede,
// não lê o .kdbx, só registra o bind via hyprctl e dispara o lançador via IPC.
Item {
  id: root

  // Injetados pela shell no load (mesmo contrato de Flowdeck/Overlay).
  property var shell: null
  property var manifest: null
  property string omarchyPath: ""

  readonly property string pluginId: "dev.keypassxd"

  // Diretório do plugin resolvido dinamicamente (sem hardcoded /home/...).
  property string pluginDir: Qt.resolvedUrl("Service.qml").toString().replace(/^file:\/\//, "").replace(/Service\.qml$/, "")
  readonly property string launchScript: root.pluginDir + "launch.sh"

  function open() {
    launchProc.running = true;
  }

  function toggle() {
    root.open();
  }

  Process {
    id: launchProc
    command: ["bash", "-c", "exec \"$0\"", root.launchScript]
  }

  // ============================ global shortcuts ============================
  // Mesma abordagem de Flowdeck (Service.qml) e CoinConvert (Overlay.qml):
  // `hyprctl eval` + `hl.bind(...)` com chord normalizado, unbind prévio via
  // pcall, re-aplicação após `configreloaded` e limpeza no onDestruction.
  // O bind chama `omarchy-shell dev.keypassxd open` (IPC abaixo), não um
  // caminho absoluto — sobrevive a moves/reinstalls do plugin.

  property var appliedShortcutChords: []

  function shortcutChordOf(id) {
    return String(id || "").split("+").map(function(k) { return k.trim().toUpperCase(); }).join(" + ");
  }

  function applyShortcuts() {
    var lines = [];
    var chords = [];
    for (var i = 0; i < root.appliedShortcutChords.length; i++)
      lines.push('pcall(function() hl.unbind("' + root.appliedShortcutChords[i] + '") end)');
    var binds = [
      { id: "ALT+K", cmd: "omarchy-shell dev.keypassxd open" }
    ];
    for (var j = 0; j < binds.length; j++) {
      if (!binds[j].id) continue;
      var chord = root.shortcutChordOf(binds[j].id);
      chords.push(chord);
      lines.push('pcall(function() hl.unbind("' + chord + '") end)');
      lines.push('hl.bind("' + chord + '", hl.dsp.exec_cmd("' + binds[j].cmd + '"), { description = "keypassXD" })');
    }
    root.appliedShortcutChords = chords;
    if (lines.length > 0) Quickshell.execDetached(["hyprctl", "eval", lines.join("; ")]);
  }

  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (event && event.name === "configreloaded") shortcutsReloadTimer.restart();
    }
  }

  Timer {
    id: shortcutsReloadTimer
    interval: 300
    repeat: false
    onTriggered: { root.appliedShortcutChords = []; root.applyShortcuts(); }
  }

  Component.onCompleted: root.applyShortcuts()

  Component.onDestruction: {
    var lines = root.appliedShortcutChords.map(function(c) { return 'pcall(function() hl.unbind("' + c + '") end)'; });
    if (lines.length > 0) Quickshell.execDetached(["hyprctl", "eval", lines.join("; ")]);
  }

  // ============================ plugin IPC ==============================
  // ALT+K chama `omarchy-shell dev.keypassxd open`; o clique no cadeado usa
  // `shell.serviceFor("dev.keypassxd").open()` com fallback para bar.run.

  IpcHandler {
    target: "dev.keypassxd"
    function open(): string { root.open(); return "ok"; }
    function toggle(): string { root.toggle(); return "ok"; }
    function ping(): string { return "ok"; }
  }
}
