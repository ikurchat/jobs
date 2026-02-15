#!/bin/bash
# VNC server для доступа к экрану

# Ждём Xvfb
sleep 3

AUTH_ARGS="-nopw"
if [ -n "$VNC_PASSWORD" ]; then
    AUTH_ARGS="-passwd $VNC_PASSWORD"
fi

exec x11vnc \
    -display :99 \
    -forever \
    -shared \
    -rfbport 5900 \
    $AUTH_ARGS \
    -xkb \
    -noxrecord \
    -noxfixes \
    -noxdamage
