#!/bin/bash
# Непрерывная запись аудио, сегменты по 10 мин

RECORDING_DIR="${RECORDING_DIR:-/recordings}"
SEGMENT_TIME="${SEGMENT_TIME:-600}"

mkdir -p "$RECORDING_DIR"

# Ждём PulseAudio (проверяем что sink доступен)
for i in $(seq 1 30); do
    if pactl list sinks short 2>/dev/null | grep -q virtual_speaker; then
        break
    fi
    sleep 1
done

exec ffmpeg -y \
    -f pulse \
    -i virtual_speaker.monitor \
    -ac 1 -ar 16000 \
    -c:a libmp3lame -b:a 32k \
    -f segment -segment_time "$SEGMENT_TIME" \
    -strftime 1 \
    "${RECORDING_DIR}/chunk_%Y%m%d_%H%M%S.mp3"
