#!/bin/bash
# Локальный прокси: localhost:8888
# Режим определяется файлом /browser-control/proxy_enabled:
#   "1" → upstream через внешний прокси (HTTP_PROXY)
#   "0" или отсутствует → прямое соединение (без upstream)

CONTROL_FILE="/browser-control/proxy_enabled"

# Читаем режим
PROXY_MODE="0"
if [ -f "$CONTROL_FILE" ]; then
    PROXY_MODE=$(cat "$CONTROL_FILE" 2>/dev/null)
fi

# Базовый конфиг
cat > /tmp/tinyproxy.conf << EOF
Port 8888
Listen 127.0.0.1
Timeout 600
MaxClients 100
LogLevel Error
EOF

# Если прокси включён и HTTP_PROXY задан — добавляем upstream
if [ "$PROXY_MODE" = "1" ] && [ -n "$HTTP_PROXY" ]; then
    PROXY_PARTS=$(echo "$HTTP_PROXY" | sed -E 's|https?://||')

    if echo "$PROXY_PARTS" | grep -q '@'; then
        USERPASS=$(echo "$PROXY_PARTS" | cut -d'@' -f1)
        HOSTPORT=$(echo "$PROXY_PARTS" | cut -d'@' -f2)
        echo "Upstream http ${USERPASS}@${HOSTPORT}" >> /tmp/tinyproxy.conf
    else
        echo "Upstream http ${PROXY_PARTS}" >> /tmp/tinyproxy.conf
    fi
    echo "tinyproxy: upstream proxy mode"
else
    echo "tinyproxy: direct mode"
fi

exec tinyproxy -d -c /tmp/tinyproxy.conf
