#!/bin/bash
# VNC server для доступа к экрану

# Ждём Xvfb
sleep 3

exec x11vnc \
    -display :99 \
    -forever \
    -shared \
    -rfbport 5900 \
    -nopw \
    -xkb \
    -noxrecord \
    -noxfixes \
    -noxdamage
