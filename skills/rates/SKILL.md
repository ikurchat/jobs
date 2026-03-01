---
name: rates
description: >
  Use when user asks about exchange rates, currency rates, crypto prices,
  "курс валют", "курс доллара", "курс биткоина", "сколько стоит биткоин",
  "курс крипты", "rates", "price of BTC", "курс USDT", "курс ETH",
  "сколько стоит эфир", "курс рубля".
tools:
  - Bash
---

# Rates — Exchange & Crypto Rates via Binance

Get current exchange rates and crypto prices from Binance API.

## Default pairs

| Pair       | Description              |
|------------|--------------------------|
| USDTRUB    | Доллар (USDT) к рублю   |
| BTCUSDT    | Биткоин к доллару        |
| ETHUSDT    | Эфириум к доллару        |
| SOLUSDT    | Солана к доллару         |
| TONUSDT    | Тонкоин к доллару        |
| XRPUSDT    | Рипл к доллару           |
| BTCRUB     | Биткоин к рублю          |

## Algorithm

### Step 1 — Determine requested pairs

- If user asks for a specific coin/currency — find the matching Binance symbol(s).
  Examples: "курс биткоина" → BTCUSDT + BTCRUB, "курс доллара" → USDTRUB, "ETH" → ETHUSDT.
- If user asks generically ("курсы", "rates", "что по рынку") — use ALL default pairs.
- User can ask for ANY Binance pair — just uppercase it and query.

### Step 2 — Fetch data from Binance

Run a single curl command to get 24h ticker data for the selected symbols:

```bash
curl -s "https://api.binance.com/api/v3/ticker/24hr?symbols=$(python3 -c "import json; print(json.dumps(['BTCUSDT','ETHUSDT','USDTRUB']))")" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for t in data:
    sym = t['symbol']
    price = float(t['lastPrice'])
    change = float(t['priceChangePercent'])
    arrow = '+' if change >= 0 else ''
    # Format price: no decimals for large numbers, 2 for small, 4 for tiny
    if price >= 100:
        p = f'{price:,.0f}'
    elif price >= 1:
        p = f'{price:,.2f}'
    else:
        p = f'{price:,.4f}'
    print(f'{sym:<12} {p:>14}   {arrow}{change:.2f}%')
"
```

Replace the symbols list with the actual pairs determined in Step 1.

**IMPORTANT:** Always use the `symbols` (plural) parameter with a JSON array, even for a single pair.

### Step 3 — Format and present

Present results as a clean table. Example output:

```
Курсы на 01.03.2026 (Binance)

Пара           Цена            24ч
─────────────────────────────────────
USDTRUB          91.10       +0.15%
BTCUSDT      66,425.57       -1.23%
ETHUSDT       1,982.28       +2.45%
SOLUSDT         142.30       +3.10%
TONUSDT           3.82       -0.55%
XRPUSDT           0.62       +1.80%
BTCRUB     3,900,027.00      -1.10%
```

Rules:
- Always show the date.
- Positive change: prefix with `+`. Negative: the minus is already there.
- RUB pairs: note that USDTRUB is essentially the dollar rate via USDT.
- If a pair is not found on Binance, say so — do not guess.
- Keep the response concise. No lengthy explanations unless asked.
- If user asks "сколько стоит X в рублях" and there is no direct RUB pair, calculate: price_in_USDT * USDTRUB rate.

### Step 4 — Handle errors

- If Binance API is unreachable: report "Binance API unavailable, try again later."
- If a symbol is invalid: report which symbol was not found.
- Do NOT fall back to other sources. Only Binance.
