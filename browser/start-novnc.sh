#!/bin/bash
# noVNC web interface

# Ждём VNC
sleep 5

exec websockify \
    --web=/usr/share/novnc/ \
    6080 \
    localhost:5900
