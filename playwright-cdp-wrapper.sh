#!/bin/bash
# Wrapper for @playwright/mcp — fixes WebSocket URL for Docker CDP connections.
# Chromium returns ws://127.0.0.1:PORT/... which is unreachable from other containers.
# This script fetches the WS URL, rewrites the hostname, and passes it to Playwright.

CDP_HTTP_URL="${1:?Usage: $0 <cdp-http-url>}"
shift

# Extract host from CDP URL (e.g., "browser" from "http://browser:9223")
CDP_HOST=$(echo "$CDP_HTTP_URL" | sed -E 's|https?://([^:/]+).*|\1|')

# Fetch /json/version and rewrite WS URL (retry up to 5 times)
FIXED_WS_URL=""
for i in 1 2 3 4 5; do
  FIXED_WS_URL=$(curl -sf "$CDP_HTTP_URL/json/version" 2>/dev/null | \
    python3 -c "
import sys, json
data = json.load(sys.stdin)
url = data['webSocketDebuggerUrl']
print(url.replace('ws://127.0.0.1', 'ws://$CDP_HOST'))
" 2>/dev/null)
  if [ -n "$FIXED_WS_URL" ]; then break; fi
  sleep 2
done

if [ -z "$FIXED_WS_URL" ]; then
  echo "Failed to get WebSocket URL from $CDP_HTTP_URL/json/version" >&2
  exit 1
fi

exec npx @playwright/mcp --cdp-endpoint "$FIXED_WS_URL" "$@"
