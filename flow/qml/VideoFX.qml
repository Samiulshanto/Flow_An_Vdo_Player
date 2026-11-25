import QtQuick
import QtQuick.Effects

// Picture tools for video: brightness / contrast / saturation / warmth, applied on the GPU.
// Loaded through a Loader from main.qml so that a Qt without QtQuick.Effects only loses this
// feature instead of failing to start.
Item {
    id: fx
    property Item source: null
    property real brightness: 0
    property real contrast: 0
    property real saturation: 0
    property real warmth: 0          // -1 cool ... +1 warm
    readonly property bool needed: Math.abs(brightness) + Math.abs(contrast)
                                   + Math.abs(saturation) + Math.abs(warmth) > 0.001

    visible: needed && source !== null

    MultiEffect {
        anchors.fill: parent
        source: fx.source
        autoPaddingEnabled: false
        brightness: fx.brightness
        contrast: fx.contrast
        saturation: fx.saturation
        colorization: Math.abs(fx.warmth) * 0.22
        colorizationColor: fx.warmth >= 0 ? "#ffb066" : "#66b0ff"
    }
}
