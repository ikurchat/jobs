#!/bin/bash
# PulseAudio с virtual null-sink для захвата аудио Chromium

mkdir -p /tmp/pulse-browser
mkdir -p "$HOME/.config/pulse"

sleep 1

exec pulseaudio \
    --daemonize=no \
    --exit-idle-time=-1 \
    --disallow-exit \
    --no-cpu-limit \
    --load="module-null-sink sink_name=virtual_speaker sink_properties=device.description=Virtual_Speaker" \
    --load="module-native-protocol-unix" \
    --log-target=stderr
