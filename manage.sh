#!/bin/bash

# --- CONFIGURATION (Edit these if needed) ---
APP_NAME="Flow"
DESKTOP_FILE_NAME="my-flow-app.desktop"
ICON_NAME="logo.png" # File in this folder, or a system icon name like "utilities-terminal"
# --------------------------------------------

APP_DIR="$(cd "$(dirname "${BASH_SOURCE}")" && pwd)"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/$DESKTOP_FILE_NAME"

install_app() {
    echo "Installing $APP_NAME from $APP_DIR..."

    # 1. Create .venv if missing
    if [ ! -d "$APP_DIR/.venv" ]; then
        echo "Creating virtual environment (.venv)..."
        python3 -m venv "$APP_DIR/.venv"
        if [ -f "$APP_DIR/requirements.txt" ]; then
            echo "Installing dependencies from requirements.txt..."
            "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
        fi
    fi

    # 2. Ensure run.sh is executable
    if [ -f "$APP_DIR/run.sh" ]; then
        chmod +x "$APP_DIR/run.sh"
    else
        echo "Warning: run.sh not found in $APP_DIR"
    fi

    # 3. Resolve icon path
    if [ -f "$APP_DIR/$ICON_NAME" ]; then
        ICON_PATH="$APP_DIR/$ICON_NAME"
    else
        ICON_PATH="$ICON_NAME"
    fi

    # 4. Create the .desktop shortcut
    mkdir -p "$DESKTOP_DIR"
    cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Version=1.0
Type=Application
Name=$APP_NAME
Exec="$APP_DIR/run.sh"
Icon=$ICON_PATH
Path=$APP_DIR
Terminal=false
Categories=Utility;
EOF

    chmod +x "$DESKTOP_FILE"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR"
    echo "Success! '$APP_NAME' added to your applications menu."
}

uninstall_app() {
    if [ -f "$DESKTOP_FILE" ]; then
        rm "$DESKTOP_FILE"
        command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR"
        echo "Success! '$APP_NAME' shortcut removed from your applications menu."
    else
        echo "Nothing to remove: '$APP_NAME' is not currently installed."
    fi
}

# Handle terminal arguments OR show interactive menu if none given
case "$1" in
    install)
        install_app
        ;;
    uninstall)
        uninstall_app
        ;;
    *)
        echo "==============================="
        echo "  $APP_NAME - Setup Manager"
        echo "==============================="
        echo "1) Install (Setup .venv & Add App Icon)"
        echo "2) Uninstall (Remove App Icon)"
        echo "3) Exit"
        read -rp "Choose an option [1-3]: " choice
        case "$choice" in
            1) install_app ;;
            2) uninstall_app ;;
            3) exit 0 ;;
            *) echo "Invalid option." && exit 1 ;;
        esac
        ;;
esac
