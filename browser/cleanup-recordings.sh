#!/bin/bash
# Удаление записей старше 24 часов. Запускается раз в час.

while true; do
    find /recordings -name "chunk_*.mp3" -mmin +1440 -delete 2>/dev/null
    sleep 3600
done
