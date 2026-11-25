import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes
import QtQuick.Dialogs
import QtMultimedia
import QtCore

ApplicationWindow {
    id: win
    width: 1180; height: 720
    minimumWidth: 560; minimumHeight: 360
    visible: true
    color: "#000000"
    title: player.hasMedia ? player.title : "Flow~"
    flags: Qt.Window | (cfg.alwaysOnTop ? Qt.WindowStaysOnTopHint : 0)

    readonly property bool fullscreen: visibility === Window.FullScreen
    property bool uiAwake: true
    property bool scrubbing: false
    property real scrubFrac: 0
    property bool queueOpen: false
    property bool browserOpen: true
    property bool settingsOpen: false
    property int sel: 0
    property string selPath: ""
    property real lx: -1
    property real ly: -1
    readonly property bool popupOpen: audioPop.opened || subPop.opened || fxPop.opened || speedPop.opened || morePop.opened || settingsOpen
    readonly property bool showUi: browserOpen || !player.playing || uiAwake || popupOpen || scrubbing || !player.hasMedia
    readonly property bool compact: bar.width < 720
    readonly property var speeds: [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]

    function fmt(ms) {
        if (ms === undefined || isNaN(ms) || ms < 0) ms = 0
        var s = Math.floor(ms / 1000)
        var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60
        return (h > 0 ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (x < 10 ? "0" : "") + x
    }
    readonly property var audioExts: ["mp3","flac","wav","aac","m4a","ogg","oga","opus","wma","aiff","ape","mka"]
    function kindOfName(n) {
        var i = n.lastIndexOf(".")
        return (i >= 0 && audioExts.indexOf(n.substring(i + 1).toLowerCase()) >= 0) ? "audio" : "video"
    }
    function groupIcon(tag) {
        return tag === "movies" ? "film" : (tag === "series" ? "tree" : (tag === "show" ? "list" : (tag === "extras" ? "plus" : (tag === "audio" ? "music" : "open"))))
    }
    function clamp01(v) { return Math.max(0, Math.min(1, v)) }
    function wake() { uiAwake = true; idleTimer.restart() }
    function moved(x, y) {
        if (Math.abs(x - lx) + Math.abs(y - ly) > 2) { lx = x; ly = y; wake() }
    }
    function select(i) {
        var n = tree.count
        if (n === 0) { sel = 0; selPath = ""; return }
        sel = Math.max(0, Math.min(n - 1, i))
        selPath = library.pathAt(sel)
        tree.positionViewAtIndex(sel, ListView.Contain)
    }
    function treeRight() {
        if (!library.isDir(sel)) return
        if (!library.isOpen(sel)) library.setOpen(sel, true)
        else select(sel + 1)
    }
    function treeLeft() {
        if (library.isDir(sel) && library.isOpen(sel)) library.setOpen(sel, false)
        else { var p = library.parentIndex(sel); if (p >= 0) select(p) }
    }
    function toggleFullscreen() { visibility = fullscreen ? Window.Windowed : Window.FullScreen; wake() }
    function openDialog(append) {
        fd.append = append
        if (fullscreen) {
            visibility = Window.Windowed
            Qt.callLater(function() { fd.open() })
        } else {
            fd.open()
        }
    }
    function volIcon(v, muted) {
        if (muted || v <= 0) return "vol0"
        return v < 0.34 ? "vol1" : (v < 0.67 ? "vol2" : "vol3")
    }
    function adjustVolume(d) { player.setVolume(clamp01(player.volume + d)); wake() }
    function toggleMute() { player.toggleMute(); wake() }
    function skip(ms) {
        if (!player.hasMedia) return
        player.seekBy(ms); wake()
    }
    function stepSpeed(dir) {
        var best = 0
        for (var i = 0; i < speeds.length; i++)
            if (Math.abs(speeds[i] - player.speed) < Math.abs(speeds[best] - player.speed)) best = i
        var n = Math.max(0, Math.min(speeds.length - 1, best + dir))
        setSpeed(speeds[n])
    }
    function setSpeed(r) { player.setSpeed(r); wake(); island.flash("speed", r + "\u00d7", -1, UI.accent, "") }
    function cycleSubtitle() {
        if (!player.hasMedia) return
        var t = player.subtitleTracks, usable = []
        for (var i = 0; i < t.length; i++) if (t[i].usable) usable.push(i)
        if (usable.length === 0) {
            var msg = t.length > 0 ? "Only image subtitles here \u2014 Shift+C loads a file"
                                   : (player.subtitleLoading ? "Reading subtitles\u2026" : "No subtitles \u2014 Shift+C loads a file")
            island.flash("subtitle", msg, -1, UI.textDim, ""); wake(); return
        }
        var at = usable.indexOf(player.activeSubtitle)
        var next = (at + 1 >= usable.length) ? -1 : usable[at + 1]
        player.selectSubtitle(next)
        island.flash("subtitle", next < 0 ? "Subtitles off" : t[next].label, -1, UI.accent, "")
        wake()
    }
    function nudgeSubtitle(ms) {
        if (!player.hasMedia) return
        player.adjustSubtitleDelay(ms)
        var d = player.subtitleDelay / 1000
        island.flash("subtitle", "Subtitle delay " + (d > 0 ? "+" : "") + d.toFixed(1) + " s", -1, UI.accent, "")
        wake()
    }
    function openSubtitleDialog() {
        if (!player.hasMedia) { island.flash("warn", "Open a video first", -1, UI.danger, ""); return }
        if (fullscreen) {
            visibility = Window.Windowed
            Qt.callLater(function() { sfd.open() })
        } else {
            sfd.open()
        }
    }
    readonly property var fxOrder: ["off", "hdr", "cinematic", "vibrant"]
    function fxLabel(n) {
        return n === "hdr" ? "HDR boost" : (n === "cinematic" ? "Cinematic" : (n === "vibrant" ? "Vibrant" : (n === "custom" ? "Custom" : "Original")))
    }
    function applyPreset(name) {
        var p = FxPresets[name]
        if (!p) return
        for (var k in p) if (k !== "fxLetterbox") cfg[k] = p[k]   // cinematic bars are a separate switch
        cfg.fxPreset = name
        island.flash("sliders", "Picture: " + fxLabel(name), -1, UI.accent, "")
        wake()
    }
    function cyclePicture() {
        if (!player.hasVideo) { island.flash("sliders", "Picture tools are for video", -1, UI.textDim, ""); wake(); return }
        var i = fxOrder.indexOf(cfg.fxPreset)
        applyPreset(fxOrder[(i + 1) % fxOrder.length])
    }
    function trackLabel() {
        var t = player.audioTracks
        return (t.length > 0 && player.activeTrack >= 0 && player.activeTrack < t.length) ? t[player.activeTrack].label : "Default"
    }

    Component.onCompleted: { browserOpen = cfg.openLibrary; wake() }
    onBrowserOpenChanged: { if (browserOpen) { player.saveProgress(); if (fullscreen) visibility = Window.Windowed } }
    function resetAll() { for (var k in cfgDefaults) cfg[k] = cfgDefaults[k] }

    Timer {
        id: idleTimer
        interval: Math.round(cfg.hideDelay * 1000 * (win.fullscreen ? 0.8 : 1))
        onTriggered: {
            if (!win.fullscreen && (barHover.hovered || queueHover.hovered || actHover.hovered)) restart()
            else win.uiAwake = false
        }
    }
    Timer { id: clickTimer; interval: 220; onTriggered: { player.togglePlay(); win.wake() } }
    Timer { id: scrubTimer; interval: 90; onTriggered: player.seek(win.scrubFrac * player.duration) }

    Binding { target: UI; property: "panel"; value: Qt.rgba(0.165, 0.165, 0.165, cfg.panelOpacity) }
    Binding { target: UI; property: "physics"; value: cfg.physics }
    Binding { target: UI; property: "sp"; value: cfg.physics ? cfg.stiffness : 6.0 }
    Binding { target: UI; property: "dp"; value: cfg.physics ? 0.5 - 0.42 * cfg.bounce : 0.9 }
    Binding { target: UI; property: "hoverScale"; value: cfg.hoverScale }
    Binding { target: UI; property: "magnet"; value: cfg.magnet }

    Connections {
        target: player
        function onErrorMessage(msg) { island.flash("warn", msg, -1, UI.danger, "") }
        function onTrackStarted(t) {
            win.browserOpen = false
            win.queueOpen = false
            island.flash("play", t, -1, UI.accent, "")
        }
    }
    Connections {
        target: library
        function fix() {
            if (win.selPath !== "") {
                var i = library.indexOfPath(win.selPath)
                if (i >= 0) win.sel = i
                else win.sel = Math.max(0, Math.min(win.sel, tree.count - 1))
            } else if (tree.count > 0) win.select(0)
        }
        function onRowsInserted() { Qt.callLater(fix) }
        function onRowsRemoved() { Qt.callLater(fix) }
    }

    FileDialog {
        id: fd
        property bool append: false
        title: append ? "Add to queue" : "Open media"
        fileMode: FileDialog.OpenFiles
        nameFilters: player.fileFilters
        currentFolder: player.lastFolder !== "" ? player.lastFolder : StandardPaths.writableLocation(StandardPaths.MoviesLocation)
        onAccepted: append ? player.enqueueUrls(selectedFiles) : player.openUrls(selectedFiles)
    }
    FileDialog {
        id: sfd
        title: "Load subtitle"
        fileMode: FileDialog.OpenFiles
        nameFilters: player.subtitleFilters
        currentFolder: player.lastFolder !== "" ? player.lastFolder : StandardPaths.writableLocation(StandardPaths.MoviesLocation)
        onAccepted: player.addSubtitleFiles(selectedFiles)
    }

    Shortcut { sequences: ["Space", "K"]; onActivated: { player.togglePlay(); win.wake() } }
    Shortcut { sequence: "Left"; enabled: !win.browserOpen && !win.settingsOpen; onActivated: win.skip(-cfg.seekSmall * 1000) }
    Shortcut { sequence: "Right"; enabled: !win.browserOpen && !win.settingsOpen; onActivated: win.skip(cfg.seekSmall * 1000) }
    Shortcut { sequence: "Shift+Left"; enabled: !win.browserOpen && !win.settingsOpen; onActivated: win.skip(-cfg.seekLarge * 1000) }
    Shortcut { sequence: "Shift+Right"; enabled: !win.browserOpen && !win.settingsOpen; onActivated: win.skip(cfg.seekLarge * 1000) }
    Shortcut { sequence: "Up"; enabled: !win.browserOpen && !win.settingsOpen; onActivated: win.adjustVolume(cfg.volStep / 100) }
    Shortcut { sequence: "Down"; enabled: !win.browserOpen && !win.settingsOpen; onActivated: win.adjustVolume(-cfg.volStep / 100) }
    Shortcut { sequence: "M"; onActivated: win.toggleMute() }
    Shortcut { sequence: "C"; onActivated: win.cycleSubtitle() }
    Shortcut { sequence: "Shift+C"; onActivated: win.openSubtitleDialog() }
    Shortcut { sequence: "Z"; onActivated: win.nudgeSubtitle(-100) }
    Shortcut { sequence: "X"; onActivated: win.nudgeSubtitle(100) }
    Shortcut { sequence: "V"; onActivated: win.cyclePicture() }
    Shortcut { sequences: ["F", "F11"]; onActivated: win.toggleFullscreen() }
    Shortcut { sequence: "Escape"; enabled: win.fullscreen && !win.popupOpen && !win.browserOpen && !win.settingsOpen; onActivated: { win.visibility = Window.Windowed; win.wake() } }
    Shortcut { sequences: ["N", "Ctrl+Right"]; onActivated: { player.next(); win.wake() } }
    Shortcut { sequences: ["P", "Ctrl+Left"]; onActivated: { player.prev(); win.wake() } }
    Shortcut { sequences: ["]", "="]; onActivated: win.stepSpeed(1) }
    Shortcut { sequences: ["[", "-"]; onActivated: win.stepSpeed(-1) }
    Shortcut { sequence: "Ctrl+O"; onActivated: win.openDialog(false) }
    Shortcut { sequence: "Ctrl+L"; onActivated: { win.queueOpen = !win.queueOpen; win.wake() } }
    Shortcut { sequence: "Ctrl+W"; onActivated: win.close() }
    Shortcut { sequence: "Ctrl+B"; onActivated: { win.browserOpen = !win.browserOpen; win.wake() } }
    Shortcut { sequence: "Ctrl+,"; onActivated: { win.settingsOpen = !win.settingsOpen; win.wake() } }
    Shortcut { sequence: "Escape"; enabled: win.settingsOpen; onActivated: win.settingsOpen = false }

    Shortcut { sequence: "Up"; enabled: win.browserOpen && !win.settingsOpen; onActivated: win.select(win.sel - 1) }
    Shortcut { sequence: "Down"; enabled: win.browserOpen && !win.settingsOpen; onActivated: win.select(win.sel + 1) }
    Shortcut { sequence: "PgUp"; enabled: win.browserOpen && !win.settingsOpen; onActivated: win.select(win.sel - 12) }
    Shortcut { sequence: "PgDown"; enabled: win.browserOpen && !win.settingsOpen; onActivated: win.select(win.sel + 12) }
    Shortcut { sequence: "Home"; enabled: win.browserOpen && !win.settingsOpen; onActivated: win.select(0) }
    Shortcut { sequence: "End"; enabled: win.browserOpen && !win.settingsOpen; onActivated: win.select(tree.count - 1) }
    Shortcut { sequence: "Right"; enabled: win.browserOpen && !win.settingsOpen; onActivated: win.treeRight() }
    Shortcut { sequence: "Left"; enabled: win.browserOpen && !win.settingsOpen; onActivated: win.treeLeft() }
    Shortcut { sequences: ["Return", "Enter"]; enabled: win.browserOpen && !win.settingsOpen; onActivated: library.activate(win.sel) }
    Shortcut { sequence: "Shift+Return"; enabled: win.browserOpen && !win.settingsOpen; onActivated: library.playFolder(win.sel) }
    Shortcut { sequence: "R"; enabled: win.browserOpen && !win.settingsOpen; onActivated: library.rescan() }
    Shortcut { sequence: "O"; enabled: win.browserOpen && !win.settingsOpen; onActivated: win.openDialog(false) }
    Shortcut { sequence: "Escape"; enabled: win.browserOpen && !win.settingsOpen && player.hasMedia; onActivated: win.browserOpen = false }

    component Icon: Item {
        id: ic
        property string name: ""
        property color color: "white"
        property real size: 18
        property real sw: 1.8
        readonly property var def: IconPaths[name] || ({})
        width: size; height: size
        layer.enabled: true
        layer.samples: 4
        Shape {
            width: 24; height: 24
            scale: ic.size / 24
            transformOrigin: Item.TopLeft
            ShapePath {
                fillColor: ic.color; strokeColor: "transparent"; strokeWidth: -1
                PathSvg { path: ic.def.fill || "" }
            }
            ShapePath {
                fillColor: "transparent"; strokeColor: ic.color; strokeWidth: ic.sw
                capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
                PathSvg { path: ic.def.stroke || "" }
            }
        }
    }

    component SoftShadow: Item {
        property real radius: 14
        property real lift: 6
        anchors.fill: parent
        z: -1
        Repeater {
            model: 5
            Rectangle {
                anchors.fill: parent
                anchors.margins: -(index + 1) * 4
                anchors.topMargin: -(index + 1) * 4 + parent.lift
                anchors.bottomMargin: -(index + 1) * 4 - parent.lift
                radius: parent.radius + (index + 1) * 4
                color: "#0d000000"
            }
        }
    }

    component IconButton: Item {
        id: ib
        property string icon: ""
        property string tip: ""
        property string badge: ""
        property bool active: false
        property real iconSize: 18
        property bool tipBelow: false
        property bool still: false
        property alias text: lbl.text
        signal clicked()
        implicitWidth: lbl.text !== "" ? lbl.implicitWidth + 22 : 34
        implicitHeight: 34
        opacity: enabled ? 1 : 0.35
        readonly property bool hot: ma.containsMouse && enabled
        property real mx: (UI.physics && !still && hot) ? (ma.mouseX - width / 2) * UI.magnet : 0
        property real my: (UI.physics && !still && hot) ? (ma.mouseY - height / 2) * UI.magnet : 0
        Behavior on mx { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.05 } }
        Behavior on my { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.05 } }
        Accessible.role: Accessible.Button
        Accessible.name: tip

        Rectangle {
            id: body
            anchors.fill: parent
            radius: 8
            color: ib.active ? "#26ffffff" : "transparent"
            scale: (!UI.physics || ib.still) ? 1 : (ma.pressed ? 1 - UI.hoverScale * 0.9 : (ib.hot ? 1 + UI.hoverScale : 1))
            Behavior on scale { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.002 } }
            transform: Translate { x: ib.mx; y: ib.my }
            Icon {
                anchors.centerIn: parent
                visible: ib.icon !== ""
                name: ib.icon; size: ib.iconSize
                color: ib.active ? UI.accent : UI.text
            }
            Text {
                id: lbl
                anchors.centerIn: parent
                visible: text !== ""
                color: ib.active ? UI.accent : UI.text
                font.pixelSize: 13; font.weight: Font.DemiBold
            }
            Text {
                visible: ib.badge !== ""
                text: ib.badge
                color: UI.accent
                font.pixelSize: 9; font.weight: Font.Bold
                anchors.right: parent.right; anchors.bottom: parent.bottom
                anchors.rightMargin: 6; anchors.bottomMargin: 4
            }
        }
        MouseArea {
            id: ma
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: ib.clicked()
        }
        ToolTip {
            id: tipItem
            visible: cfg.tooltips && ma.containsMouse && ib.tip !== "" && ib.enabled
            delay: 700
            text: ib.tip
            x: (ib.width - width) / 2
            y: ib.tipBelow ? ib.height + 8 : -height - 8
            leftPadding: 9; rightPadding: 9; topPadding: 5; bottomPadding: 5
            contentItem: Text { text: tipItem.text; color: UI.text; font.pixelSize: 12 }
            background: Rectangle { color: "#eb000000"; radius: 6; border.color: UI.hairlineStrong }
        }
    }

    component PrimaryButton: Rectangle {
        id: pb
        property string label: ""
        property string icon: ""
        signal clicked()
        implicitWidth: pbRow.implicitWidth + 28
        implicitHeight: 34
        radius: 8
        color: pbm.pressed ? "#b3b3b3" : (pbm.containsMouse ? "#e0e0e0" : UI.accent)
        scale: !UI.physics ? 1 : (pbm.pressed ? 1 - UI.hoverScale * 0.6 : (pbm.containsMouse ? 1 + UI.hoverScale * 0.6 : 1))
        Behavior on scale { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.002 } }
        Row {
            id: pbRow
            anchors.centerIn: parent
            spacing: 8
            Icon { visible: pb.icon !== ""; name: pb.icon; size: 16; color: "#000000"; anchors.verticalCenter: parent.verticalCenter }
            Text { text: pb.label; color: "#000000"; font.pixelSize: 13; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
        }
        MouseArea { id: pbm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: pb.clicked() }
    }

    component SegBar: Item {
        id: sb
        property real value: 0
        property real buffered: 0
        property int segWidth: 4
        property int gap: 2
        property real segRadius: 1.5
        property string previewText: ""
        property color hoverColor: "#99ffffff"
        readonly property int count: Math.max(1, Math.floor((width + gap) / (segWidth + gap)))
        readonly property real pitch: (width + gap) / count
        readonly property bool hovered: ma.containsMouse
        readonly property real hoverValue: (ma.containsMouse || ma.pressed) ? Math.max(0, Math.min(1, ma.mouseX / Math.max(1, width))) : -1
        signal seekTo(real frac)
        signal dragStarted()
        signal dragEnded()

        Repeater {
            model: sb.count
            Rectangle {
                x: Math.round(index * sb.pitch)
                width: Math.round(index * sb.pitch + sb.pitch - sb.gap) - x
                height: sb.height
                radius: sb.segRadius
                property real near: (UI.physics && cfg.waveBars && sb.hoverValue >= 0)
                                    ? Math.max(0, 1 - Math.abs((index + 0.5) / sb.count - sb.hoverValue) * sb.count / 7) : 0
                Behavior on near { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.005 } }
                transform: Scale { origin.x: width / 2; origin.y: height / 2; yScale: 1 + 0.6 * near }
                color: {
                    var m = (index + 0.5) / sb.count
                    if (m <= sb.value) return UI.segOn
                    if (sb.hoverValue >= 0 && m <= sb.hoverValue) return sb.hoverColor
                    if (m <= sb.buffered) return UI.segBuf
                    return UI.segOff
                }
            }
        }
        MouseArea {
            id: ma
            anchors.fill: parent
            anchors.topMargin: -6; anchors.bottomMargin: -6
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            function frac() { return Math.max(0, Math.min(1, mouseX / Math.max(1, width))) }
            onPressed: { sb.dragStarted(); sb.seekTo(frac()) }
            onPositionChanged: if (pressed) sb.seekTo(frac())
            onReleased: sb.dragEnded()
            onCanceled: sb.dragEnded()
        }
        Rectangle {
            visible: sb.previewText !== "" && (ma.containsMouse || ma.pressed)
            width: bt.implicitWidth + 16; height: 24; radius: 7
            color: "#f2000000"; border.color: UI.hairlineStrong
            x: Math.max(-6, Math.min(sb.width - width + 6, ma.mouseX - width / 2))
            y: -height - 10
            Text { id: bt; anchors.centerIn: parent; text: sb.previewText; color: UI.text; font.pixelSize: 12; font.weight: Font.Medium }
        }
    }

    component Ring: Item {
        id: ring
        property real value: 0
        property int segments: 24
        property real inner: 0.62
        property color onColor: "#fafafa"
        property color offColor: "#3f3f3f"
        readonly property int filled: Math.round(Math.max(0, Math.min(1, value)) * segments)
        function sector(i) {
            var cx = width / 2, cy = height / 2
            var R = Math.min(width, height) / 2 - 1, r = R * inner
            var step = 2 * Math.PI / segments, gap = 0.05
            var a0 = -Math.PI / 2 + i * step + gap / 2, a1 = a0 + step - gap
            function p(rad, a) { return (cx + rad * Math.cos(a)).toFixed(2) + " " + (cy + rad * Math.sin(a)).toFixed(2) }
            return "M " + p(R, a0) + " A " + R + " " + R + " 0 0 1 " + p(R, a1)
                 + " L " + p(r, a1) + " A " + r + " " + r + " 0 0 0 " + p(r, a0) + " Z"
        }
        layer.enabled: true
        layer.samples: 4
        Repeater {
            model: ring.segments
            Shape {
                anchors.fill: parent
                ShapePath {
                    strokeColor: "transparent"; strokeWidth: -1
                    fillColor: index < ring.filled ? ring.onColor : ring.offColor
                    PathSvg { path: ring.sector(index) }
                }
            }
        }
    }

    // The on-screen pill/capsule was removed. flash() is kept as a silent no-op so callers stay simple.
    component Island: QtObject {
        function flash(ic, txt, prog, tn, tl) { }
    }

    component Pop: Popup {
        padding: 6
        modal: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        enter: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 120 }
                NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: 120 }
            }
        }
        exit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 90 } }
        background: Rectangle { radius: 10; color: "#f0262626"; border.color: UI.hairlineStrong; border.width: 1 }
    }

    component PopRow: Rectangle {
        id: pr
        property string label: ""
        property string sub: ""
        property string badge: ""
        property string icon: ""
        property bool checked: false
        property bool dim: false
        property real nudge: (UI.physics && pm.containsMouse) ? 4 : 0
        Behavior on nudge { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.05 } }
        signal activated()
        implicitHeight: 32
        radius: 6
        color: pm.containsMouse ? "#33ffffff" : "transparent"
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 8; anchors.rightMargin: 10
            spacing: 8
            transform: Translate { x: pr.nudge }
            Item {
                Layout.preferredWidth: 16; Layout.preferredHeight: 16
                Icon { anchors.centerIn: parent; visible: pr.checked || pr.icon !== ""; name: pr.checked ? "check" : pr.icon; size: 14; color: "white" }
            }
            Rectangle {
                visible: pr.badge !== ""
                Layout.preferredWidth: bt2.implicitWidth + 12; Layout.preferredHeight: 18
                radius: 4; color: "#33ffffff"
                Text { id: bt2; anchors.centerIn: parent; text: pr.badge; color: "white"; font.pixelSize: 11 }
            }
            Text { Layout.fillWidth: true; text: pr.label; color: pr.dim ? UI.textDim : "white"; elide: Text.ElideRight; font.pixelSize: 13 }
            Text { visible: pr.sub !== ""; text: pr.sub; color: pm.containsMouse ? "#ccffffff" : UI.textDim; font.pixelSize: 12 }
        }
        MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true; onClicked: pr.activated() }
    }

    component Switch2: Item {
        id: sw
        property bool checked: false
        signal toggled(bool value)
        width: 48; height: 28
        Item {
            id: swBody
            anchors.fill: parent
            scale: (UI.physics && swm.containsMouse) ? 1 + UI.hoverScale * 0.6 : 1
            Behavior on scale { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.002 } }
            Rectangle {
                anchors.fill: parent; radius: 14
                color: sw.checked ? UI.accent : "#444444"
                border.color: UI.hairline
                Behavior on color { ColorAnimation { duration: 160 } }
            }
            Rectangle {
                y: 3; height: 22; radius: 11; color: sw.checked ? "#000000" : "white"
                width: swm.pressed ? 28 : 22
                x: sw.checked ? swBody.width - width - 3 : 3
                Behavior on x { SpringAnimation { spring: UI.sp * 1.3; damping: UI.dp; epsilon: 0.1 } }
                Behavior on width { NumberAnimation { duration: 90 } }
            }
        }
        MouseArea {
            id: swm
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: sw.toggled(!sw.checked)
        }
    }

    component Slider2: Item {
        id: sl
        property real from: 0
        property real to: 1
        property real value: 0
        property real step: 0
        property int decimals: 0
        property string suffix: ""
        signal moved(real v)
        readonly property real frac: to > from ? Math.max(0, Math.min(1, (value - from) / (to - from))) : 0
        width: 270; height: 32
        function snap(f) {
            var v = from + Math.max(0, Math.min(1, f)) * (to - from)
            if (step > 0) v = Math.round((v - from) / step) * step + from
            return Math.max(from, Math.min(to, v))
        }
        Item {
            id: trackBox
            width: sl.width - 64; height: parent.height
            Rectangle { width: parent.width; height: 6; radius: 3; color: "#333333"; anchors.verticalCenter: parent.verticalCenter }
            Rectangle {
                width: Math.max(0, knob.x + knob.width / 2); height: 6; radius: 3
                color: UI.accent; anchors.verticalCenter: parent.verticalCenter
            }
            Rectangle {
                id: knob
                width: 18; height: 18; radius: 9; color: "white"
                anchors.verticalCenter: parent.verticalCenter
                x: sl.frac * trackBox.width - width / 2
                Behavior on x { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.1 } }
                scale: !UI.physics ? 1 : (slm.pressed ? 1.35 : (slm.containsMouse ? 1.2 : 1))
                Behavior on scale { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.002 } }
            }
            MouseArea {
                id: slm
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onPressed: m => sl.moved(sl.snap(m.x / width))
                onPositionChanged: m => { if (pressed) sl.moved(sl.snap(m.x / width)) }
            }
        }
        Text {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            width: 56; horizontalAlignment: Text.AlignRight
            text: sl.value.toFixed(sl.decimals) + sl.suffix
            color: UI.textDim; font.pixelSize: 12; font.family: UI.mono
        }
    }

    component Chips: Row {
        id: ch
        property var options: []
        property var current: null
        signal picked(var value)
        spacing: 4
        Repeater {
            model: ch.options
            Rectangle {
                id: chip
                readonly property bool sel: ch.current === modelData.value
                width: ct.implicitWidth + 24; height: 30; radius: 8
                color: sel ? UI.accent : (cm.containsMouse ? "#33ffffff" : "#1affffff")
                Behavior on color { ColorAnimation { duration: 100 } }
                scale: !UI.physics ? 1 : (cm.pressed ? 1 - UI.hoverScale * 0.6 : (cm.containsMouse ? 1 + UI.hoverScale * 0.6 : 1))
                Behavior on scale { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.002 } }
                Text { id: ct; anchors.centerIn: parent; text: modelData.label; color: chip.sel ? "#000000" : "white"; font.pixelSize: 12; font.weight: Font.DemiBold }
                MouseArea {
                    id: cm
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: ch.picked(modelData.value)
                }
            }
        }
    }

    component SectionTitle: Text {
        Layout.fillWidth: true
        Layout.topMargin: 20
        Layout.bottomMargin: 2
        color: UI.textDim; font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.2
    }

    component KeyRow: Item {
        id: kr
        property string keys: ""
        property string what: ""
        Layout.fillWidth: true
        implicitHeight: 32
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            height: 22; width: kt.implicitWidth + 16; radius: 5
            color: "#1fffffff"; border.color: UI.hairline
            Text { id: kt; anchors.centerIn: parent; text: kr.keys; color: UI.text; font.family: UI.mono; font.pixelSize: 11 }
        }
        Text { x: 128; anchors.verticalCenter: parent.verticalCenter; text: kr.what; color: UI.textDim; font.pixelSize: 12 }
    }

    component SettingRow: Item {
        id: sr
        property string title: ""
        property string desc: ""
        default property alias control: slot.data
        Layout.fillWidth: true
        implicitHeight: Math.max(58, tcol.implicitHeight + 24)
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: "#14ffffff" }
        Column {
            id: tcol
            anchors.left: parent.left
            anchors.right: slot.left; anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            Text { width: parent.width; text: sr.title; color: UI.text; font.pixelSize: 14; font.weight: Font.Medium; wrapMode: Text.WordWrap }
            Text { visible: sr.desc !== ""; width: parent.width; text: sr.desc; color: UI.textFaint; font.pixelSize: 12; wrapMode: Text.WordWrap }
        }
        Item {
            id: slot
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: childrenRect.width; height: childrenRect.height
        }
    }

    Item {
        id: stage
        anchors.fill: parent

        HoverHandler { onPointChanged: win.moved(point.position.x, point.position.y) }

        Rectangle {
            anchors.fill: parent
            color: (player.hasMedia && !player.isAudio) ? "#000000" : "#111111"
            Behavior on color { ColorAnimation { duration: 200 } }
        }

        Item {
            id: viz
            anchors.fill: parent
            visible: player.hasMedia && player.isAudio && !win.browserOpen
            readonly property bool live: visible && win.visible
            onLiveChanged: wavefeed.setActive(live)
            Component.onCompleted: wavefeed.setActive(live)

            // Real-time scope: the bars are the spectrum of the audio that is playing right now,
            // the line is its waveform. Both come from wavefeed (flow/visualizer.py).
            Canvas {
                id: scope
                anchors.horizontalCenter: parent.horizontalCenter
                y: viz.height * 0.40 - height / 2
                width: Math.min(viz.width - 48, 1100)
                height: Math.max(80, viz.height * 0.40)
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                Connections {
                    target: wavefeed
                    function onFrame() { if (viz.live) scope.requestPaint() }
                }
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var bars = wavefeed.bars, wave = wavefeed.wave
                    var style = cfg.vizStyle
                    var cy = height / 2
                    ctx.lineCap = "round"
                    ctx.lineJoin = "round"
                    if (style !== "wave") {
                        var n = bars.length
                        var span = Math.min(width, n * 24)
                        var pitch = span / n
                        var x0 = (width - span) / 2
                        ctx.lineWidth = Math.max(3, Math.min(14, pitch * 0.6))
                        for (var i = 0; i < n; i++) {
                            var v = bars[i] || 0
                            var h = v * height * 0.48
                            var x = x0 + pitch * (i + 0.5)
                            ctx.strokeStyle = "rgba(255,255,255," + (0.30 + 0.70 * v).toFixed(2) + ")"
                            ctx.beginPath()
                            ctx.moveTo(x, cy - h)
                            ctx.lineTo(x, cy + h + 0.01)
                            ctx.stroke()
                        }
                    }
                    if (style !== "bars") {
                        var m = wave.length
                        if (m > 1) {
                            ctx.lineWidth = style === "wave" ? 3 : 2
                            ctx.strokeStyle = style === "wave" ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.85)"
                            ctx.beginPath()
                            var amp = height * (style === "wave" ? 0.46 : 0.30)
                            for (var j = 0; j < m; j++) {
                                var px = width * j / (m - 1)
                                var py = cy - (wave[j] || 0) * amp
                                if (j === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                            }
                            ctx.stroke()
                        }
                    }
                }
            }
            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                y: scope.y + scope.height + 26
                spacing: 6
                width: Math.min(parent.width * 0.8, 720)
                Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: player.title; color: "white"; font.pixelSize: 22; font.weight: Font.DemiBold }
                Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: wavefeed.available ? "Audio" : "Audio  \u00b7  live visualizer needs PySide6 6.8 or newer"; color: UI.textDim; font.pixelSize: 13 }
            }
        }

        VideoOutput {
            id: video
            anchors.fill: parent
            fillMode: VideoOutput.PreserveAspectFit
            Component.onCompleted: player.attachVideoOutput(video)
        }

        // Picture tools: colour grading on the GPU (see VideoFX.qml)
        Loader {
            id: fxLoader
            anchors.fill: video
            source: "VideoFX.qml"
            asynchronous: false
            onLoaded: item.source = video
            onStatusChanged: if (status === Loader.Error) console.log("[Flow~] picture tools unavailable (QtQuick.Effects missing?)")
        }
        Binding { target: fxLoader.item; property: "brightness"; value: cfg.fxBrightness; when: fxLoader.item !== null }
        Binding { target: fxLoader.item; property: "contrast"; value: cfg.fxContrast; when: fxLoader.item !== null }
        Binding { target: fxLoader.item; property: "saturation"; value: cfg.fxSaturation; when: fxLoader.item !== null }
        Binding { target: fxLoader.item; property: "warmth"; value: cfg.fxWarmth; when: fxLoader.item !== null }

        // Vignette: darkens the corners of the picture (cinematic look)
        Canvas {
            id: vignette
            readonly property real amount: cfg.fxVignette
            x: video.contentRect.x; y: video.contentRect.y
            width: video.contentRect.width; height: video.contentRect.height
            visible: amount > 0.01 && player.hasVideo && width > 0
            onAmountChanged: requestPaint()
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onVisibleChanged: if (visible) requestPaint()
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var r = Math.sqrt(width * width + height * height) / 2
                var g = ctx.createRadialGradient(width / 2, height / 2, r * 0.35, width / 2, height / 2, r)
                g.addColorStop(0, "rgba(0,0,0,0)")
                g.addColorStop(1, "rgba(0,0,0," + Math.min(0.9, amount * 0.85).toFixed(2) + ")")
                ctx.fillStyle = g
                ctx.fillRect(0, 0, width, height)
            }
        }

        // Cinematic bars (2.39:1): only appear when the picture is taller than that
        Item {
            id: bars239
            visible: cfg.fxLetterbox && player.hasVideo
            x: video.contentRect.x; y: video.contentRect.y
            width: video.contentRect.width; height: video.contentRect.height
            readonly property real barH: Math.max(0, (height - width / 2.39) / 2)
            Rectangle { anchors.top: parent.top; width: parent.width; height: bars239.barH; color: "#000000" }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: bars239.barH; color: "#000000" }
        }

        Item {
            id: subOverlay
            readonly property string line: player.subtitleText
            visible: line !== "" && !win.browserOpen && player.hasMedia
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: (bar.opacity > 0.5 && bar.visible) ? bar.height + 40 : 40
            Behavior on anchors.bottomMargin { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
            width: Math.min(parent.width * 0.86, 1100)
            height: subText.implicitHeight
            Rectangle {
                visible: cfg.subBox
                anchors.centerIn: subText
                width: subText.contentWidth + 28; height: subText.contentHeight + 12
                radius: 8; color: "#a6000000"
            }
            Text {
                id: subText
                width: parent.width
                text: subOverlay.line
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                color: "#ffffff"
                style: Text.Outline; styleColor: "#000000"
                font.pixelSize: Math.round(Math.max(14, Math.min(40, win.height / 22)) * cfg.subSize)
                font.weight: Font.DemiBold
            }
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: (win.showUi || !player.hasMedia) ? Qt.ArrowCursor : Qt.BlankCursor
            onPositionChanged: m => win.moved(m.x, m.y)
            onClicked: if (player.hasMedia) clickTimer.restart()
            onDoubleClicked: { clickTimer.stop(); win.toggleFullscreen() }
            onWheel: wheel => { if (cfg.wheelVolume) win.adjustVolume(wheel.angleDelta.y > 0 ? cfg.volStep / 100 : -cfg.volStep / 100) }
        }

        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 96
            opacity: win.showUi ? 1 : 0
            visible: opacity > 0.01 && player.hasVideo
            Behavior on opacity { NumberAnimation { duration: 220 } }
            gradient: Gradient {
                GradientStop { position: 0; color: "#99000000" }
                GradientStop { position: 1; color: "#00000000" }
            }
        }
        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 200
            opacity: win.showUi ? 1 : 0
            visible: opacity > 0.01 && player.hasVideo
            Behavior on opacity { NumberAnimation { duration: 220 } }
            gradient: Gradient {
                GradientStop { position: 0; color: "#00000000" }
                GradientStop { position: 1; color: "#b3000000" }
            }
        }

        Ring {
            id: spinner
            width: 56; height: 56
            anchors.centerIn: parent
            segments: 20; value: 0.3
            visible: player.buffering && player.hasMedia
            RotationAnimator on rotation { from: 0; to: 360; duration: 1200; loops: Animation.Infinite; running: spinner.visible }
        }

        Rectangle {
            id: browser
            anchors.fill: parent
            color: "#0a0a0a"
            opacity: win.browserOpen ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 160 } }
            MouseArea { anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.ArrowCursor }

            readonly property bool wide: width >= 1000
            Item {
                width: Math.min(browser.wide ? 1160 : 780, parent.width - 48)
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top; anchors.topMargin: Math.max(64, parent.height * 0.09)
                anchors.bottom: parent.bottom; anchors.bottomMargin: Math.max(24, parent.height * 0.06)

                RowLayout {
                  anchors.fill: parent
                  spacing: 28
                ColumnLayout {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    spacing: 14
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "flow~ /"; color: "#8a8a8a"; font.family: UI.mono; font.pixelSize: 14 }
                        Text { text: "choose something to play"; color: "#ffffff"; font.family: UI.mono; font.pixelSize: 14; font.weight: Font.Medium }
                        Item { Layout.fillWidth: true }
                        Text { text: library.status; color: library.scanning ? "#ffffff" : "#6e6e6e"; font.family: UI.mono; font.pixelSize: 12 }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#555555" }

                    Chips {
                        options: [
                            { label: "All " + (library.status, library.countOf("all")), value: "all" },
                            { label: "Movies " + (library.status, library.countOf("movies")), value: "movies" },
                            { label: "Series " + (library.status, library.countOf("series")), value: "series" },
                            { label: "Extras " + (library.status, library.countOf("extras")), value: "extras" },
                            { label: "Audio " + (library.status, library.countOf("audio")), value: "audio" }
                        ]
                        current: library.filter
                        onPicked: v => library.setFilter(v)
                    }

                    ListView {
                        id: tree
                        Layout.fillWidth: true; Layout.fillHeight: true
                        clip: true
                        model: library
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { }
                        delegate: Item {
                            id: rowItem
                            readonly property bool isSel: index === win.sel
                            property real nudge: (UI.physics && rowMouse.containsMouse) ? 7 : 0
                            Behavior on nudge { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.05 } }
                            width: ListView.view.width
                            height: 28
Rectangle { anchors.fill: parent; color: "#14ffffff"; visible: rowMouse.containsMouse && !rowItem.isSel }
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                transform: Translate { x: rowItem.nudge }
                                Text { id: pfx; text: prefix; color: "#5a5a5a"; font.family: UI.mono; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
                                Item {
                                    width: 24; height: 20
                                    anchors.verticalCenter: parent.verticalCenter
                                    Icon {
                                        anchors.centerIn: parent
                                        name: kind === "dir" ? "open" : (kind === "group" ? win.groupIcon(media) : (media === "audio" ? "music" : "film"))
                                        size: 16
                                        color: rowItem.isSel ? "#000000" : (kind === "file" ? "#bbbbbb" : "#ffffff")
                                    }
                                }
                                Rectangle {
                                    height: 20; radius: 2
                                    width: nameText.width + 12
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: rowItem.isSel ? "#ffffff" : "transparent"
                                    Text {
                                        id: nameText
                                        anchors.centerIn: parent
                                        text: (kind !== "file" ? (open ? "\u25be " : "\u25b8 ") : "") + label
                                        width: Math.min(implicitWidth, rowItem.width - pfx.implicitWidth - 24 - 190)
                                        elide: Text.ElideRight
                                        color: rowItem.isSel ? "#000000" : (kind === "dir" ? "#ffffff" : (kind === "group" ? "#cfcfcf" : "#d9d9d9"))
                                        font.family: UI.mono; font.pixelSize: 14
                                        font.weight: kind !== "file" ? Font.Medium : Font.Normal
                                    }
                                }
                                Text { text: kind !== "file" ? "  " + cnt : ""; color: "#6e6e6e"; font.family: UI.mono; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                            }
                            Text {
                                anchors.right: parent.right; anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                text: size; color: "#6e6e6e"; font.family: UI.mono; font.pixelSize: 12
                            }
                            Rectangle {
                                visible: kind === "file"
                                anchors.right: parent.right; anchors.rightMargin: 86
                                anchors.verticalCenter: parent.verticalCenter
                                width: extT.implicitWidth + 12; height: 18; radius: 4
                                color: media === "audio" ? "#26ffffff" : "#26ffffff"
                                Text { id: extT; anchors.centerIn: parent; text: label.lastIndexOf(".") >= 0 ? label.substring(label.lastIndexOf(".") + 1).toUpperCase() : ""; color: media === "audio" ? "#d0d0d0" : "#d0d0d0"; font.family: UI.mono; font.pixelSize: 10; font.weight: Font.Bold }
                            }
                            MouseArea {
                                id: rowMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: win.select(index)
                                onDoubleClicked: library.activate(index)
                            }
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: tree.count === 0
                            horizontalAlignment: Text.AlignHCenter
                            color: "#6e6e6e"; font.family: UI.mono; font.pixelSize: 13
                            text: library.scanning ? "looking for media on this computer\u2026"
                                                   : "nothing found\n[O] open a file, or drop one here"
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#555555" }
                    Text {
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        color: "#6e6e6e"; font.family: UI.mono; font.pixelSize: 12
                        text: "[ENTER] play \u00b7 [\u2191\u2193] navigate \u00b7 [\u2192\u2190] expand \u00b7 [SHIFT+ENTER] play all \u00b7 [R] rescan \u00b7 [O] open file" + (player.hasMedia ? " \u00b7 [ESC] back" : "")
                    }
                }

                Rectangle {
                    visible: browser.wide
                    Layout.preferredWidth: 300
                    Layout.fillHeight: true
                    Layout.topMargin: 0
                    radius: 14; color: "#111111"; border.color: UI.hairline; border.width: 1
                    clip: true
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 18
                        spacing: 14
                        RowLayout {
                            spacing: 12
                            Image { source: LogoUrl; sourceSize.width: 96; sourceSize.height: 96; Layout.preferredWidth: 44; Layout.preferredHeight: 44; fillMode: Image.PreserveAspectFit; smooth: true }
                            ColumnLayout {
                                spacing: 0
                                Text { text: "Flow~"; color: "white"; font.pixelSize: 20; font.weight: Font.DemiBold }
                                Text { text: "media player"; color: UI.textDim; font.pixelSize: 12 }
                            }
                        }
                        Item {
                            id: actSlot
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: topActions.width
                            Layout.preferredHeight: topActions.height
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            rowSpacing: 8; columnSpacing: 8
                            Repeater {
                                model: [
                                    { k: "movies", t: "Movies" },
                                    { k: "series", t: "Web Series" },
                                    { k: "extras", t: "Extras" },
                                    { k: "audio", t: "Audio" }
                                ]
                                Rectangle {
                                    Layout.fillWidth: true; Layout.preferredHeight: 50
                                    radius: 10; color: statMa.containsMouse ? "#2effffff" : "#1affffff"
                                    scale: !UI.physics ? 1 : (statMa.containsMouse ? 1 + UI.hoverScale * 0.5 : 1)
                                    Behavior on scale { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.002 } }
                                    MouseArea { id: statMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: library.setFilter(modelData.k) }
                                    Column {
                                        anchors.centerIn: parent; spacing: 1
                                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: (library.status, library.countOf(modelData.k)); color: "#bbbbbb"; font.pixelSize: 18; font.weight: Font.DemiBold }
                                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.t; color: UI.textDim; font.pixelSize: 11 }
                                    }
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            PrimaryButton { label: "Open file"; icon: "open"; onClicked: win.openDialog(false) }
                            IconButton { text: "Rescan"; onClicked: library.rescan() }
                        }
                        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#26ffffff" }
                        Text { text: "Recent"; color: UI.textDim; font.pixelSize: 12; font.weight: Font.DemiBold }
                        Text { visible: player.recent.length === 0; text: "Nothing played yet"; color: UI.textFaint; font.pixelSize: 12 }
                        Repeater {
                            model: player.recent.slice(0, 5)
                            Rectangle {
                                Layout.fillWidth: true; Layout.preferredHeight: 40
                                id: rcRow
                                radius: 8; color: rcMa.containsMouse ? "#1fffffff" : "transparent"
                                property real nudge: (UI.physics && rcMa.containsMouse) ? 6 : 0
                                Behavior on nudge { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.05 } }
                                readonly property string kindR: win.kindOfName(modelData.url)
                                RowLayout {
                                    anchors.fill: parent; anchors.leftMargin: 8
                                    anchors.rightMargin: contBtn.visible ? contBtn.width + 16 : 8
                                    spacing: 10
                                    transform: Translate { x: rcRow.nudge }
                                    Icon { name: parent.parent.kindR === "audio" ? "music" : "film"; size: 16; color: parent.parent.kindR === "audio" ? "#bbbbbb" : "#bbbbbb" }
                                    ColumnLayout {
                                        Layout.fillWidth: true; spacing: 0
                                        Text { Layout.fillWidth: true; elide: Text.ElideRight; text: modelData.title; color: UI.text; font.pixelSize: 13 }
                                        Text { Layout.fillWidth: true; elide: Text.ElideRight; text: (modelData.resume > 0 ? "at " + win.fmt(modelData.resume) + "  \u00b7  " : "") + modelData.folder; color: UI.textFaint; font.pixelSize: 11 }
                                    }
                                }
                                MouseArea { id: rcMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: player.openRecent(index) }
                                Rectangle {
                                    id: contBtn
                                    visible: modelData.resume > 0
                                    anchors.right: parent.right; anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    height: 24; width: contTxt.implicitWidth + 20; radius: 12
                                    color: cbMa.containsMouse ? "#ffffff" : "#26ffffff"
                                    scale: !UI.physics ? 1 : (cbMa.pressed ? 1 - UI.hoverScale * 0.6 : (cbMa.containsMouse ? 1 + UI.hoverScale * 0.6 : 1))
                                    Behavior on scale { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.002 } }
                                    Text { id: contTxt; anchors.centerIn: parent; text: "Continue"; color: cbMa.containsMouse ? "#000000" : "#ffffff"; font.pixelSize: 11; font.weight: Font.DemiBold }
                                    MouseArea { id: cbMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: player.continueRecent(index) }
                                }
                            }
                        }
                        Item { Layout.fillHeight: true }
                        Text { Layout.alignment: Qt.AlignHCenter; text: "made by xan"; color: UI.textFaint; font.pixelSize: 11 }
                    }
                }
                }
            }
        }

        Item {
            id: topUi
            anchors.fill: parent
            opacity: win.showUi ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 200 } }

            Rectangle {
                id: backBtn
                x: 16
                y: 14
                height: 34; width: backRow.implicitWidth + 22; radius: 17
                visible: !win.browserOpen
                color: backMa.pressed ? UI.press : (backMa.containsMouse ? "#404040" : UI.panel)
                border.color: UI.hairline; border.width: 1
                Behavior on color { ColorAnimation { duration: 90 } }
                scale: !UI.physics ? 1 : (backMa.pressed ? 1 - UI.hoverScale * 0.8 : (backMa.containsMouse ? 1 + UI.hoverScale : 1))
                Behavior on scale { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.002 } }
                Row {
                    id: backRow
                    anchors.centerIn: parent
                    spacing: 4
                    Icon { name: "chevleft"; size: 16; sw: 2; color: "#ffffff"; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: "Back"; color: "#ffffff"; font.pixelSize: 13; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                }
                MouseArea {
                    id: backMa
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { win.browserOpen = true; win.wake() }
                }
            }

            Rectangle {
                id: topActions
                property real slide: (win.browserOpen && browser.wide) ? 1 : 0
                Behavior on slide { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
                property real slotX: 0
                property real slotY: 0
                function sync() {
                    var q = actSlot.mapToItem(topUi, 0, 0)
                    slotX = q.x; slotY = q.y
                }
                x: (topUi.width - width - 16) * (1 - slide) + slotX * slide
                y: 14 * (1 - slide) + slotY * slide
                Component.onCompleted: Qt.callLater(sync)
                Connections {
                    target: stage
                    function onWidthChanged() { Qt.callLater(topActions.sync) }
                    function onHeightChanged() { Qt.callLater(topActions.sync) }
                }
                Connections {
                    target: actSlot
                    function onXChanged() { Qt.callLater(topActions.sync) }
                    function onYChanged() { Qt.callLater(topActions.sync) }
                    function onWidthChanged() { Qt.callLater(topActions.sync) }
                }
                Connections { target: browser; function onWideChanged() { Qt.callLater(topActions.sync) } }
                Connections { target: win; function onBrowserOpenChanged() { Qt.callLater(topActions.sync) } }
                height: 36; width: actRow.implicitWidth + 8; radius: 18
                color: UI.panel; border.color: UI.hairline
                HoverHandler { id: actHover }
                Row {
                    id: actRow
                    anchors.centerIn: parent
                    spacing: 2
                    IconButton { icon: "pin"; tip: "Always on top"; tipBelow: true; active: cfg.alwaysOnTop; onClicked: cfg.alwaysOnTop = !cfg.alwaysOnTop }
                    IconButton { icon: "gear"; tip: "Settings  (Ctrl+,)"; tipBelow: true; active: win.settingsOpen; onClicked: win.settingsOpen = !win.settingsOpen }
                    IconButton { icon: "tree"; tip: "Library  (Ctrl+B)"; tipBelow: true; active: win.browserOpen; onClicked: win.browserOpen = !win.browserOpen }
                    IconButton { icon: "open"; tip: "Open file  (Ctrl+O)"; tipBelow: true; onClicked: win.openDialog(false) }
                    IconButton { icon: "list"; tip: "Queue  (Ctrl+L)"; tipBelow: true; active: win.queueOpen; onClicked: win.queueOpen = !win.queueOpen }
                }
            }
        }

        Rectangle {
            id: queuePanel
            property int tab: 0
            anchors.right: parent.right; anchors.rightMargin: 16
            anchors.top: parent.top; anchors.topMargin: 64
            anchors.bottom: bar.top; anchors.bottomMargin: 14
            width: Math.min(340, parent.width - 32)
            radius: 12; color: UI.panel; border.color: UI.hairline
            opacity: (win.queueOpen && win.showUi && !win.browserOpen) ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 180 } }
            transform: Translate { x: win.queueOpen ? 0 : 20; Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } } }
            SoftShadow { radius: 12 }
            HoverHandler { id: queueHover }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 8
                RowLayout {
                    Layout.fillWidth: true
                    Rectangle {
                        Layout.preferredWidth: 160; Layout.preferredHeight: 30
                        radius: 8; color: "#1fffffff"
                        Row {
                            anchors.fill: parent; anchors.margins: 2; spacing: 2
                            Repeater {
                                model: ["Queue", "Recent"]
                                Rectangle {
                                    width: (parent.width - 2) / 2; height: parent.height; radius: 6
                                    color: queuePanel.tab === index ? "#555555" : (tabMa.containsMouse ? "#26ffffff" : "transparent")
                                    scale: !UI.physics ? 1 : (tabMa.containsMouse ? 1 + UI.hoverScale * 0.5 : 1)
                                    Behavior on scale { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.002 } }
                                    Text {
                                        anchors.centerIn: parent
                                        text: modelData + ((index === 0 && player.queue.length > 0) ? "  " + player.queue.length : "")
                                        color: UI.text; font.pixelSize: 12; font.weight: Font.Medium
                                    }
                                    MouseArea { id: tabMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: queuePanel.tab = index }
                                }
                            }
                        }
                    }
                    Item { Layout.fillWidth: true }
                    IconButton {
                        text: "Clear"
                        implicitHeight: 30
                        enabled: queuePanel.tab === 0 ? player.queue.length > 0 : player.recent.length > 0
                        onClicked: queuePanel.tab === 0 ? player.clearQueue() : player.clearRecent()
                    }
                }
                ListView {
                    id: lv
                    Layout.fillWidth: true; Layout.fillHeight: true
                    clip: true; spacing: 2
                    model: queuePanel.tab === 0 ? player.queue : player.recent
                    ScrollBar.vertical: ScrollBar { }
                    delegate: Rectangle {
                        id: row
                        readonly property bool current: queuePanel.tab === 0 && index === player.index
                        width: ListView.view.width
                        height: 50; radius: 8
                        color: rowHover.hovered ? "#1fffffff" : "transparent"
                        property real nudge: (UI.physics && rowHover.hovered) ? 5 : 0
                        Behavior on nudge { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.05 } }
                        HoverHandler { id: rowHover }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (queuePanel.tab === 0) {
                                    player.playIndex(index)
                                } else {
                                    player.openRecent(index)
                                }
                                win.queueOpen = false
                                win.wake()
                            }
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10; anchors.rightMargin: 6
                            spacing: 10
                            transform: Translate { x: row.nudge }
                            Item {
                                Layout.preferredWidth: 16; Layout.preferredHeight: 16
                                Icon { anchors.centerIn: parent; visible: row.current; name: "play"; size: 14; color: UI.accent }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 1
                                Text { Layout.fillWidth: true; text: modelData.title; elide: Text.ElideRight; color: row.current ? UI.accent : UI.text; font.pixelSize: 13; font.weight: Font.Medium }
                                Text { Layout.fillWidth: true; text: modelData.folder; elide: Text.ElideRight; color: UI.textFaint; font.pixelSize: 11 }
                            }
                            IconButton {
                                visible: queuePanel.tab === 0
                                icon: "close"; iconSize: 14
                                implicitWidth: 28; implicitHeight: 28
                                tip: "Remove"
                                onClicked: player.removeAt(index)
                            }
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: lv.count === 0
                        text: queuePanel.tab === 0 ? "The queue is empty" : "No recent files"
                        color: UI.textFaint; font.pixelSize: 13
                    }
                }
            }
        }

        Rectangle {
            id: bar
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom; anchors.bottomMargin: 18
            width: Math.min(parent.width - 32, 1000)
            height: col.implicitHeight + 28
            radius: 14; color: UI.panel; border.color: UI.hairline
            opacity: (win.showUi && !win.browserOpen) ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 200 } }
            transform: Translate { y: win.showUi ? 0 : 16; Behavior on y { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } } }
            SoftShadow { radius: 14 }
            HoverHandler { id: barHover }

            ColumnLayout {
                id: col
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 14 }
                spacing: 10

                Text {
                    Layout.fillWidth: true
                    visible: win.compact
                    text: player.hasMedia ? player.title : "Nothing playing"
                    elide: Text.ElideRight
                    color: UI.text; font.pixelSize: 13; font.weight: Font.DemiBold
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    Text {
                        Layout.preferredWidth: 64
                        horizontalAlignment: Text.AlignRight
                        text: win.fmt(win.scrubbing ? win.scrubFrac * player.duration : player.position)
                        color: UI.textDim; font.pixelSize: 12
                    }
                    SegBar {
                        id: seek
                        Layout.fillWidth: true
                        Layout.preferredHeight: 22
                        enabled: player.hasMedia && player.duration > 0
                        opacity: enabled ? 1 : 0.5
                        value: win.scrubbing ? win.scrubFrac : (player.duration > 0 ? player.position / player.duration : 0)
                        buffered: player.duration > 0 ? Math.min(1, (player.position + player.buffer * (player.duration - player.position)) / player.duration) : 0
                        previewText: player.duration > 0 && hoverValue >= 0 ? win.fmt(hoverValue * player.duration) : ""
                        onDragStarted: win.scrubbing = true
                        onSeekTo: frac => { win.scrubFrac = frac; if (!scrubTimer.running) scrubTimer.start() }
                        onDragEnded: { scrubTimer.stop(); player.seek(win.scrubFrac * player.duration); win.scrubbing = false }
                    }
                    Text {
                        Layout.preferredWidth: 70
                        text: cfg.showRemaining ? ("\u2212" + win.fmt(Math.max(0, player.duration - (win.scrubbing ? win.scrubFrac * player.duration : player.position)))) : win.fmt(player.duration)
                        color: UI.textDim; font.pixelSize: 12
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Rectangle {
                        Layout.preferredHeight: 38; Layout.preferredWidth: trRow.implicitWidth + 8
                        radius: 10; color: "#1affffff"
                        Row {
                            id: trRow
                            anchors.centerIn: parent
                            spacing: 2
                            IconButton { icon: "prev"; tip: "Previous  (P)"; enabled: player.hasMedia; onClicked: player.prev() }
                            IconButton {
                                icon: player.playing ? "pause" : "play"; iconSize: 20
                                implicitWidth: 42
                                tip: player.playing ? "Pause  (Space)" : "Play  (Space)"
                                onClicked: player.togglePlay()
                            }
                            IconButton { icon: "next"; tip: "Next  (N)"; enabled: player.hasMedia; onClicked: player.next() }
                        }
                    }
                    Rectangle {
                        Layout.preferredHeight: 38; Layout.preferredWidth: exRow.implicitWidth + 8
                        radius: 10; color: "#1affffff"
                        Row {
                            id: exRow
                            anchors.centerIn: parent
                            spacing: 2
                            IconButton { icon: "plus"; tip: "Add to queue"; onClicked: win.openDialog(true) }
                            IconButton { id: moreBtn; icon: "dots"; tip: "More"; onClicked: morePop.open() }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: !win.compact
                        spacing: 1
                        Text {
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            text: player.hasMedia ? player.title : "Nothing playing"
                            elide: Text.ElideRight
                            color: UI.text; font.pixelSize: 13; font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            visible: text !== ""
                            text: player.subtitle
                            elide: Text.ElideRight
                            color: UI.textFaint; font.pixelSize: 11
                        }
                    }
                    Item { Layout.fillWidth: true; visible: win.compact }

                    RowLayout {
                        spacing: 2
                        IconButton {
                            id: audioBtn
                            icon: "audio"; tip: "Audio track"
                            enabled: player.hasMedia
                            active: player.audioTracks.length > 1
                            onClicked: audioPop.open()
                        }
                        IconButton {
                            id: fxBtn
                            icon: "sliders"
                            tip: "Picture  (V)"
                            visible: player.hasVideo
                            enabled: player.hasMedia
                            active: cfg.fxPreset !== "off"
                            onClicked: fxPop.open()
                        }
                        IconButton {
                            id: subBtn
                            icon: "subtitle"
                            tip: player.subtitleTracks.length > 0 ? "Subtitles  (C)"
                                 : (player.subtitleLoading ? "Reading subtitles\u2026" : "Subtitles  \u00b7  none found, click to load a file")
                            enabled: player.hasMedia
                            active: player.activeSubtitle >= 0
                            onClicked: subPop.open()
                        }
                        IconButton {
                            id: speedBtn
                            text: player.speed + "\u00d7"
                            tip: "Playback speed  ( [ / ] )"
                            active: Math.abs(player.speed - 1) > 0.001
                            onClicked: speedPop.open()
                        }
                        IconButton {
                            visible: !win.compact
                            icon: "repeat"; tip: "Repeat"
                            badge: player.repeatMode === 2 ? "1" : ""
                            active: player.repeatMode > 0
                            onClicked: player.cycleRepeat()
                        }
                        IconButton {
                            visible: !win.compact
                            icon: "shuffle"; tip: "Shuffle"
                            active: player.shuffle
                            onClicked: player.toggleShuffle()
                        }
                        IconButton {
                            icon: win.fullscreen ? "exitfs" : "fullscreen"
                            tip: "Fullscreen  (F)"
                            onClicked: win.toggleFullscreen()
                        }
                        IconButton {
                            icon: win.volIcon(player.volume, player.muted)
                            tip: "Mute  (M)"
                            onClicked: win.toggleMute()
                        }
                        SegBar {
                            Layout.preferredWidth: win.compact ? 60 : 84
                            Layout.preferredHeight: 16
                            Layout.rightMargin: 4
                            value: player.muted ? 0 : player.volume
                            previewText: hoverValue >= 0 ? Math.round(Math.round(hoverValue * count) / count * 100) + "%" : ""
                            onSeekTo: frac => player.setVolume(Math.round(frac * count) / count)
                        }
                    }
                }
            }

            Pop {
                id: audioPop
                parent: audioBtn
                width: 300
                x: audioBtn.width - width
                y: -height - 12
                contentItem: Column {
                    spacing: 2
                    Text { text: "Audio"; color: UI.textDim; font.pixelSize: 11; leftPadding: 8; topPadding: 4; bottomPadding: 4 }
                    Text {
                        visible: player.audioTracks.length === 0
                        text: "No audio tracks found"
                        color: UI.textDim; font.pixelSize: 13; leftPadding: 8; bottomPadding: 6
                    }
                    Repeater {
                        model: player.audioTracks
                        PopRow {
                            width: parent.width
                            badge: modelData.tag
                            label: modelData.label
                            checked: index === player.activeTrack
                            onActivated: {
                                player.selectAudioTrack(modelData.index)
                                island.flash("audio", (modelData.tag !== "" ? modelData.tag + "  " : "") + modelData.label, -1, UI.accent, "")
                                audioPop.close()
                            }
                        }
                    }
                }
            }
            Pop {
                id: subPop
                parent: subBtn
                width: 330
                x: subBtn.width - width
                y: -height - 12
                contentItem: Column {
                    spacing: 2
                    Text { text: player.subtitleLoading ? "Subtitles  \u00b7  reading\u2026" : "Subtitles"; color: UI.textDim; font.pixelSize: 11; leftPadding: 8; topPadding: 4; bottomPadding: 4 }
                    PopRow {
                        width: parent.width
                        label: "Off"
                        checked: player.activeSubtitle < 0
                        onActivated: { player.selectSubtitle(-1); subPop.close() }
                    }
                    Repeater {
                        model: player.subtitleTracks
                        PopRow {
                            width: parent.width
                            badge: modelData.tag
                            label: modelData.label
                            dim: !modelData.usable
                            checked: index === player.activeSubtitle
                            onActivated: {
                                player.selectSubtitle(modelData.index)
                                if (modelData.usable) { island.flash("subtitle", modelData.label, -1, UI.accent, ""); subPop.close() }
                            }
                        }
                    }
                    Rectangle { width: parent.width; height: 1; color: UI.hairline }
                    PopRow { width: parent.width; icon: "open"; label: "Load subtitle file\u2026  (Shift+C)"; onActivated: { subPop.close(); win.openSubtitleDialog() } }
                    PopRow {
                        width: parent.width; icon: "back"; label: "Show earlier  (Z)"
                        sub: (player.subtitleDelay / 1000).toFixed(1) + " s"
                        onActivated: player.adjustSubtitleDelay(-100)
                    }
                    PopRow { width: parent.width; icon: "fwd"; label: "Show later  (X)"; onActivated: player.adjustSubtitleDelay(100) }
                    PopRow { width: parent.width; dim: true; visible: player.subtitleDelay !== 0; label: "Reset delay"; onActivated: player.resetSubtitleDelay() }
                }
            }
            Pop {
                id: fxPop
                parent: Overlay.overlay
                width: 346
                x: Math.round((parent.width - width) / 2)
                y: Math.round((parent.height - height) / 2)
                contentItem: Column {
                    spacing: 6
                    Text { text: cfg.fxPreset === "custom" ? "Picture  \u00b7  custom" : "Picture"; color: UI.textDim; font.pixelSize: 11; leftPadding: 8; topPadding: 4; bottomPadding: 2 }
                    Chips {
                        leftPadding: 4
                        options: [{ label: "Off", value: "off" }, { label: "HDR", value: "hdr" }, { label: "Cinematic", value: "cinematic" }, { label: "Vibrant", value: "vibrant" }]
                        current: cfg.fxPreset
                        onPicked: v => win.applyPreset(v)
                    }
                    Item { width: 1; height: 2 }
                    Row {
                        spacing: 6
                        Text { width: 78; anchors.verticalCenter: parent.verticalCenter; text: "Brightness"; color: UI.text; font.pixelSize: 12; leftPadding: 4 }
                        Slider2 { width: 236; from: -0.3; to: 0.3; step: 0.01; decimals: 2; value: cfg.fxBrightness; onMoved: v => { cfg.fxBrightness = v; cfg.fxPreset = "custom" } }
                    }
                    Row {
                        spacing: 6
                        Text { width: 78; anchors.verticalCenter: parent.verticalCenter; text: "Contrast"; color: UI.text; font.pixelSize: 12; leftPadding: 4 }
                        Slider2 { width: 236; from: -0.3; to: 0.5; step: 0.01; decimals: 2; value: cfg.fxContrast; onMoved: v => { cfg.fxContrast = v; cfg.fxPreset = "custom" } }
                    }
                    Row {
                        spacing: 6
                        Text { width: 78; anchors.verticalCenter: parent.verticalCenter; text: "Colour"; color: UI.text; font.pixelSize: 12; leftPadding: 4 }
                        Slider2 { width: 236; from: -0.6; to: 0.8; step: 0.01; decimals: 2; value: cfg.fxSaturation; onMoved: v => { cfg.fxSaturation = v; cfg.fxPreset = "custom" } }
                    }
                    Row {
                        spacing: 6
                        Text { width: 78; anchors.verticalCenter: parent.verticalCenter; text: "Warmth"; color: UI.text; font.pixelSize: 12; leftPadding: 4 }
                        Slider2 { width: 236; from: -1; to: 1; step: 0.05; decimals: 2; value: cfg.fxWarmth; onMoved: v => { cfg.fxWarmth = v; cfg.fxPreset = "custom" } }
                    }
                    Row {
                        spacing: 6
                        Text { width: 78; anchors.verticalCenter: parent.verticalCenter; text: "Vignette"; color: UI.text; font.pixelSize: 12; leftPadding: 4 }
                        Slider2 { width: 236; from: 0; to: 1; step: 0.05; decimals: 2; value: cfg.fxVignette; onMoved: v => { cfg.fxVignette = v; cfg.fxPreset = "custom" } }
                    }
                    Row {
                        spacing: 10
                        leftPadding: 4
                        Switch2 { checked: cfg.fxLetterbox; onToggled: v => cfg.fxLetterbox = v }
                        Text { anchors.verticalCenter: parent.verticalCenter; text: "Cinematic bars  (2.39:1)"; color: UI.text; font.pixelSize: 12 }
                    }
                    PopRow { width: parent.width; dim: true; label: "Reset picture  (V cycles presets)"; onActivated: { cfg.fxLetterbox = false; win.applyPreset("off") } }
                }
            }
            Pop {
                id: speedPop
                parent: speedBtn
                width: 170
                x: (speedBtn.width - width) / 2
                y: -height - 12
                contentItem: Column {
                    spacing: 2
                    Text { text: "Playback speed"; color: UI.textDim; font.pixelSize: 11; leftPadding: 8; topPadding: 4; bottomPadding: 4 }
                    Repeater {
                        model: win.speeds
                        PopRow {
                            width: parent.width
                            label: modelData === 1 ? "Normal" : modelData + "\u00d7"
                            checked: Math.abs(player.speed - modelData) < 0.001
                            onActivated: { win.setSpeed(modelData); speedPop.close() }
                        }
                    }
                }
            }
            Pop {
                id: morePop
                parent: moreBtn
                width: 270
                x: 0
                y: -height - 12
                contentItem: Column {
                    spacing: 2
                    PopRow { width: parent.width; icon: "tree"; label: "Browse library\u2026"; onActivated: { morePop.close(); win.browserOpen = true } }
                    PopRow { width: parent.width; icon: "gear"; label: "Settings"; onActivated: { morePop.close(); win.settingsOpen = true } }
                    PopRow { width: parent.width; icon: "open"; label: "Open file\u2026"; onActivated: { morePop.close(); win.openDialog(false) } }
                    PopRow { width: parent.width; icon: "plus"; label: "Add to queue\u2026"; onActivated: { morePop.close(); win.openDialog(true) } }
                    PopRow { width: parent.width; icon: "subtitle"; label: "Load subtitle file\u2026"; onActivated: { morePop.close(); win.openSubtitleDialog() } }
                    PopRow { width: parent.width; icon: "list"; label: win.queueOpen ? "Hide queue" : "Show queue"; onActivated: { morePop.close(); win.queueOpen = !win.queueOpen } }
                    Rectangle { width: parent.width; height: 1; color: UI.hairline; visible: player.recent.length > 0 }
                    Text { visible: player.recent.length > 0; text: "Recent"; color: UI.textDim; font.pixelSize: 11; leftPadding: 8; topPadding: 4; bottomPadding: 4 }
                    Repeater {
                        model: player.recent
                        PopRow {
                            width: parent.width
                            label: modelData.title
                            onActivated: { morePop.close(); player.openRecent(index) }
                        }
                    }
                    PopRow { width: parent.width; visible: player.recent.length > 0; dim: true; label: "Clear recent"; onActivated: { player.clearRecent(); morePop.close() } }
                }
            }
        }

        Island { id: island }

        DropArea {
            id: dz
            anchors.fill: parent
            onEntered: drag => { drag.accepted = drag.hasUrls }
            onDropped: drop => { if (drop.hasUrls) { player.openUrls(drop.urls); drop.acceptProposedAction() } }
        }
        Rectangle {
            anchors.fill: parent; anchors.margins: 12
            visible: dz.containsDrag
            radius: 16; color: "#33ffffff"; border.color: UI.accent; border.width: 2
            z: 30
            Text { anchors.centerIn: parent; text: "Drop to play"; color: "white"; font.pixelSize: 22; font.weight: Font.Medium }
        }

        Item {
            id: settingsLayer
            anchors.fill: parent
            z: 50
            opacity: win.settingsOpen ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: 180 } }

            Rectangle { anchors.fill: parent; color: "#a6000000" }
            MouseArea { anchors.fill: parent; hoverEnabled: true; onClicked: win.settingsOpen = false }

            Rectangle {
                id: card
                anchors.centerIn: parent
                width: Math.min(480, parent.width - 40)
                height: Math.min(680, parent.height - 40)
                radius: 16
                color: "#f2181818"
                border.color: UI.hairlineStrong; border.width: 1
                scale: win.settingsOpen ? 1 : 0.94
                Behavior on scale { SpringAnimation { spring: UI.sp; damping: UI.dp; epsilon: 0.0015 } }
                SoftShadow { radius: 16; lift: 8 }
                MouseArea { anchors.fill: parent; hoverEnabled: true }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 0

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.bottomMargin: 8
                        spacing: 10
                        Image { source: LogoUrl; sourceSize.width: 64; sourceSize.height: 64; Layout.preferredWidth: 28; Layout.preferredHeight: 28; fillMode: Image.PreserveAspectFit; smooth: true }
                        Text { text: "Settings"; color: UI.text; font.pixelSize: 18; font.weight: Font.DemiBold }
                        Item { Layout.fillWidth: true }
                        IconButton { icon: "close"; tip: "Close  (Esc)"; onClicked: win.settingsOpen = false }
                    }

                    Flickable {
                        id: setFlick
                        Layout.fillWidth: true; Layout.fillHeight: true
                        clip: true
                        contentWidth: width
                        contentHeight: setCol.implicitHeight + 12
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.vertical: ScrollBar { }

                        ColumnLayout {
                            id: setCol
                            width: setFlick.width - 14
                            spacing: 0

                            SectionTitle { text: "PLAYBACK"; Layout.topMargin: 6 }
                            SettingRow {
                                title: "Skip step"; desc: "Left / Right arrow keys"
                                Chips {
                                    options: [{ label: "5s", value: 5 }, { label: "10s", value: 10 }, { label: "30s", value: 30 }]
                                    current: cfg.seekSmall
                                    onPicked: v => cfg.seekSmall = v
                                }
                            }
                            SettingRow {
                                title: "Big skip step"; desc: "Shift + Left / Right"
                                Chips {
                                    options: [{ label: "15s", value: 15 }, { label: "30s", value: 30 }, { label: "60s", value: 60 }]
                                    current: cfg.seekLarge
                                    onPicked: v => cfg.seekLarge = v
                                }
                            }
                            SettingRow {
                                title: "Volume step"; desc: "Up / Down keys and mouse wheel"
                                Chips {
                                    options: [{ label: "2%", value: 2 }, { label: "5%", value: 5 }, { label: "10%", value: 10 }]
                                    current: cfg.volStep
                                    onPicked: v => cfg.volStep = v
                                }
                            }
                            SettingRow {
                                title: "Mouse wheel changes volume"
                                Switch2 { checked: cfg.wheelVolume; onToggled: v => cfg.wheelVolume = v }
                            }
                            SettingRow {
                                title: "Play next automatically"; desc: "Continue with the next file in the queue"
                                Switch2 { checked: cfg.autoAdvance; onToggled: v => cfg.autoAdvance = v }
                            }

                            SectionTitle { text: "APPEARANCE" }
                            SettingRow {
                                title: "Show remaining time"; desc: "Counts down instead of showing total length"
                                Switch2 { checked: cfg.showRemaining; onToggled: v => cfg.showRemaining = v }
                            }
                            SettingRow {
                                title: "Control bar opacity"
                                Slider2 { width: 190; from: 0.4; to: 1.0; step: 0.05; decimals: 2; value: cfg.panelOpacity; onMoved: v => cfg.panelOpacity = v }
                            }
                            SettingRow {
                                title: "Seek bar hover wave"; desc: "Bars rise near the mouse"
                                Switch2 { checked: cfg.waveBars; onToggled: v => cfg.waveBars = v }
                            }
                            SettingRow {
                                title: "Music visualizer"; desc: "Live spectrum and waveform of what is playing"
                                Chips {
                                    options: [{ label: "Bars", value: "bars" }, { label: "Wave", value: "wave" }, { label: "Both", value: "both" }]
                                    current: cfg.vizStyle
                                    onPicked: v => cfg.vizStyle = v
                                }
                            }
                            SettingRow {
                                title: "Tooltips"
                                Switch2 { checked: cfg.tooltips; onToggled: v => cfg.tooltips = v }
                            }
                            SettingRow {
                                title: "Pop-up messages"; desc: "Speed, track and error notices at the top"
                                Switch2 { checked: cfg.notifications; onToggled: v => cfg.notifications = v }
                            }

                            SectionTitle { text: "SUBTITLES" }
                            SettingRow {
                                title: "Show subtitles automatically"; desc: "Uses a subtitle file next to the video, or the file's default track"
                                Switch2 { checked: cfg.autoSubs; onToggled: v => cfg.autoSubs = v }
                            }
                            SettingRow {
                                title: "Subtitle size"
                                Slider2 { width: 190; from: 0.6; to: 2.0; step: 0.05; decimals: 2; suffix: "\u00d7"; value: cfg.subSize; onMoved: v => cfg.subSize = v }
                            }
                            SettingRow {
                                title: "Dark box behind subtitles"; desc: "Easier to read on bright scenes"
                                Switch2 { checked: cfg.subBox; onToggled: v => cfg.subBox = v }
                            }

                            SectionTitle { text: "PICTURE" }
                            SettingRow {
                                title: "Video look"; desc: "Fine-tune with the sliders button while a video plays (V cycles)"
                                Chips {
                                    options: [{ label: "Off", value: "off" }, { label: "HDR", value: "hdr" }, { label: "Cinema", value: "cinematic" }, { label: "Vibrant", value: "vibrant" }]
                                    current: cfg.fxPreset
                                    onPicked: v => win.applyPreset(v)
                                }
                            }

                            SectionTitle { text: "MOTION" }
                            SettingRow {
                                title: "Physics animations"; desc: "Springy hover and press effects"
                                Switch2 { checked: cfg.physics; onToggled: v => cfg.physics = v }
                            }
                            SettingRow {
                                title: "Bounce"; enabled: cfg.physics; opacity: enabled ? 1 : 0.4
                                Slider2 { width: 190; from: 0; to: 1; step: 0.05; decimals: 2; value: cfg.bounce; onMoved: v => cfg.bounce = v }
                            }
                            SettingRow {
                                title: "Stiffness"; enabled: cfg.physics; opacity: enabled ? 1 : 0.4
                                Slider2 { width: 190; from: 1; to: 6; step: 0.2; decimals: 1; value: cfg.stiffness; onMoved: v => cfg.stiffness = v }
                            }
                            SettingRow {
                                title: "Hover zoom"; enabled: cfg.physics; opacity: enabled ? 1 : 0.4
                                Slider2 { width: 190; from: 0; to: 0.3; step: 0.01; decimals: 2; value: cfg.hoverScale; onMoved: v => cfg.hoverScale = v }
                            }
                            SettingRow {
                                title: "Magnet pull"; desc: "Buttons lean toward the cursor"
                                enabled: cfg.physics; opacity: enabled ? 1 : 0.4
                                Slider2 { width: 190; from: 0; to: 0.6; step: 0.05; decimals: 2; value: cfg.magnet; onMoved: v => cfg.magnet = v }
                            }

                            SectionTitle { text: "WINDOW & LIBRARY" }
                            SettingRow {
                                title: "Hide controls after"; desc: "While a video is playing"
                                Slider2 { width: 190; from: 1; to: 10; step: 0.5; decimals: 1; suffix: "s"; value: cfg.hideDelay; onMoved: v => cfg.hideDelay = v }
                            }
                            SettingRow {
                                title: "Always on top"
                                Switch2 { checked: cfg.alwaysOnTop; onToggled: v => cfg.alwaysOnTop = v }
                            }
                            SettingRow {
                                title: "Open library on launch"
                                Switch2 { checked: cfg.openLibrary; onToggled: v => cfg.openLibrary = v }
                            }
                            SettingRow {
                                title: "Scan for media on launch"; desc: "Finds videos and music on your drives"
                                Switch2 { checked: cfg.scanOnLaunch; onToggled: v => cfg.scanOnLaunch = v }
                            }
                            SettingRow {
                                title: "Scan depth"; desc: "How many folder levels to search (next scan)"
                                Slider2 { width: 190; from: 2; to: 20; step: 1; decimals: 0; value: cfg.scanDepth; onMoved: v => cfg.scanDepth = v }
                            }

                            SectionTitle { text: "QUICK GUIDE" }
                            Text {
                                Layout.fillWidth: true; Layout.topMargin: 6; Layout.bottomMargin: 8
                                wrapMode: Text.WordWrap; lineHeight: 1.25
                                color: UI.textDim; font.pixelSize: 12
                                text: "Drop a video, song or whole folder onto the window to play it, or press O to browse. Flow~ also finds media on your computer by itself \u2014 double-click a file in the library to play it.\n\nControls hide while a video plays; move the mouse to bring them back. Stopped halfway through a movie? Open the library and press Continue next to it."
                            }
                            KeyRow { keys: "Space  /  K"; what: "Play or pause" }
                            KeyRow { keys: "\u2190  \u2192"; what: "Skip back / forward" }
                            KeyRow { keys: "Shift + \u2190 \u2192"; what: "Bigger skip" }
                            KeyRow { keys: "\u2191  \u2193"; what: "Volume up / down" }
                            KeyRow { keys: "M"; what: "Mute" }
                            KeyRow { keys: "C"; what: "Cycle subtitles" }
                            KeyRow { keys: "Shift + C"; what: "Load a subtitle file" }
                            KeyRow { keys: "Z  /  X"; what: "Subtitles earlier / later" }
                            KeyRow { keys: "V"; what: "Cycle picture look (HDR, Cinematic, Vibrant)" }
                            KeyRow { keys: "F  /  F11"; what: "Fullscreen (or double-click the video)" }
                            KeyRow { keys: "N  /  P"; what: "Next / previous" }
                            KeyRow { keys: "[  ]"; what: "Slower / faster playback" }
                            KeyRow { keys: "Ctrl + O"; what: "Open a file" }
                            KeyRow { keys: "Ctrl + B"; what: "Library" }
                            KeyRow { keys: "Ctrl + L"; what: "Queue" }
                            KeyRow { keys: "Ctrl + ,"; what: "Settings" }
                            KeyRow { keys: "Esc"; what: "Go back / close" }

                            SectionTitle { text: "ABOUT" }
                            Text {
                                Layout.fillWidth: true; Layout.topMargin: 6
                                wrapMode: Text.WordWrap; lineHeight: 1.25
                                color: UI.textDim; font.pixelSize: 12
                                text: "Flow~ is a small, minimal media player for video and audio.\nYour settings, recent files and resume points are saved on this computer only."
                            }
                            Text { Layout.topMargin: 10; text: "Made by xan"; color: UI.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; Layout.topMargin: 8; Layout.preferredHeight: 1; color: "#14ffffff" }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 10
                        Text { text: "Flow~ v" + AppVersion + "  \u00b7  made by xan"; color: UI.textFaint; font.pixelSize: 11 }
                        Item { Layout.fillWidth: true }
                        IconButton { text: "Reset all"; onClicked: win.resetAll() }
                    }
                }
            }
        }

    }
}
