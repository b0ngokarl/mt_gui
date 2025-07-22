#!/bin/bash
# Meshtastic GUI Launcher
# This script launches the GUI with X11 backend to avoid Wayland issues

cd "$(dirname "$0")"
export QT_QPA_PLATFORM=xcb
python3 meshtastic_gui.py
