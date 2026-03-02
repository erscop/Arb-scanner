import requests, json, os
from difflib import SequenceMatcher
from datetime import datetime

NTFY_TOPIC      = os.environ.get("NTFY_TOPIC", "")
MIN_EDGE        = 0.04        # Edge minimo netto dopo fee (4%)
MIN_LIQUIDITY   = 200         # $ minimi di liquidità
POLY_FEE        = 0.02        # 2% fee Polymarket
KALSHI_FEE      = 0.02        # ~2% fee Kalshi
MATCH_THRESHOLD = 0.65        # Soglia similarità titoli (0-1)

def get_polymarket_markets():
    try:
        r = requests.get("https://gamma-api.polymarket.com/markets",
                         params={"active": "true", "closed": "false", "limit": 200},
                         timeout=10)
        result = []
        for m in r.json():
            try:
                prices    = json.loads(m.get("outcomePrices", "[]"))
                yes, no   = float(prices[0]), float(prices[1])
                liquidity = float(m.get("liquidity", 0))
                if liquidity >= MIN_LIQUIDITY:
                    result.append({"title": m.get("question", ""),
                                   "yes": yes, "no": no, "liquidity": liquidity,
                                   "url": f"https://polymarket.com/event/{m.get('slug','')}"})
            except: continue
        return result
    except Exception as e:
        print(f"[Polymarket ERROR] {e}")
        return []

def get_kalshi_markets():
    try:
        r = requests.get(
            "https://api.elections.kalshi.com/trade-api/v2/markets",
            params={"status": "open", "limit": 200},
            headers={"accept": "application/json"},
            timeout=10
        )
        result = []
        for m in r.json().get("markets", []):
            yes_ask  = m.get("yes_ask")    # prezzo ask YES in centesimi (0-100)
            no_ask   = m.get("no_ask")     # prezzo ask NO in centesimi (0-100)
            liquidity = m.get("liquidity", 0)
            if yes_ask and no_ask and liquidity >= MIN_LIQUIDITY:
                result.append({
                    "title":     m.get("title", ""),
                    "yes":       yes_ask / 100,
                    "no":        no_ask  / 100,
                    "liquidity": liquidity,
                    "url":       f"https://kalshi.com/markets/{m.get('ticker', '')}"
                })
        return result
    except Exception as e:
        print(f"[Kalshi ERROR] {e}")
        return []

def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def find_arb(poly_list, kalshi_list):
    found, seen = [], set()
    net_fee = POLY_FEE + KALSHI_FEE
    for p in poly_list:
        for k in kalshi_list:
            if similarity(p["title"], k["title"]) < MATCH_THRESHOLD: continue
            key = p["title"][:30] + k["title"][:30]
            if key in seen: continue
            seen.add(key)
            for label, cost, sA, sB in [
                ("YES Poly + NO Kalshi", p["yes"] + k["no"],
                 f"BUY YES @ {p['yes']:.2f} su Polymarket",
                 f"BUY NO  @ {k['no']:.2f} su Kalshi"),
                ("NO Poly + YES Kalshi", p["no"] + k["yes"],
                 f"BUY NO  @ {p['no']:.2f} su Polymarket",
                 f"BUY YES @ {k['yes']:.2f} su Kalshi"),
            ]:
                edge = (1 - cost) - net_fee
                if edge > MIN_EDGE:
                    found.append({
                        "label": label, "edge": round(edge * 100, 2),
                        "cost": round(cost, 4),
                        "profit_per_dollar": round(1 - cost, 4),
                        "sA": sA, "sB": sB,
                        "poly_title": p["title"][:55],
                        "kalshi_title": k["title"][:55],
                        "poly_url": p["url"],
                        "kalshi_url": k["url"]
                    })
    return found

def send_ntfy(arbs):
    for a in arbs:
        msg = (f"━━━━━━━━━━━━━━━━━━━━\n"
               f"📊 {a['sA']}\n"
               f"📊 {a['sB']}\n"
               f"━━━━━━━━━━━━━━━━━━━━\n"
               f"💰 Costo: ${a['cost']} → Profitto: ${a['profit_per_dollar']} per $1\n"
               f"━━━━━━━━━━━━━━━━━━━━\n"
               f"🟣 {a['poly_title']}\n"
               f"🔵 {a['kalshi_title']}\n"
               f"━━━━━━━━━━━━━━━━━━━━\n"
               f"🔗 {a['poly_url']}\n"
               f"🔗 {a['kalshi_url']}")
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=msg.encode("utf-8"),
            headers={
                "Title":    f"🚨 ARB +{a['edge']}% | {a['label']}",
                "Priority": "urgent",
                "Tags":     "money_with_wings,rotating_light"
            }
        )
        print(f"  ✅ Alert: {a['label']} | Edge: {a['edge']}% | Costo: ${a['cost']}")

if __name__ == "__main__":
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')} UTC] Scansione in corso...")
    poly   = get_polymarket_markets()
    kalshi = get_kalshi_markets()
    print(f"  → Polymarket: {len(poly)} mercati | Kalshi: {len(kalshi)} mercati")
    arbs = find_arb(poly, kalshi)
    print(f"  → Arbitraggi trovati: {len(arbs)}")
    if arbs:
        send_ntfy(arbs)
    else:
        print("  → Nessuna opportunità sopra soglia.")
