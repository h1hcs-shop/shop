"""Hourly catalog builder for the 烟酒商城 Mini App (GitHub Actions).

Fetches the PUBLIC h1hcs.com storefront (吉隆坡 warehouse only) with the bot's own catalog_live.py, classifies and keys
products with the bot's own shop_cart.py (same 7 categories, same item_key = sha1(name|unit|spec)[:10]) and writes
site/catalog.json with shop_miniapp.export_catalog(): name, unit, spec, KL price, original price, image URL. No stock.
Writes ONLY when the product data changed (updated_at alone does not count), so the workflow commits only on change.

Exit codes: 0 ok (changed or unchanged), 1 fetch/sanity failure (old file kept), 2 configuration missing.
The storefront agent id comes from the STOREFRONT_AGENT environment variable (GitHub secret) and is never printed."""
import json, logging, os, re, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vendor"))
import catalog_live, shop_cart, shop_miniapp

OUT = os.path.join(os.path.dirname(HERE), "site", "catalog.json")
CS = [{"name": "阿霞", "icon": "👩"}, {"name": "阿东", "icon": "👨"}]   # same order as the bot's 客服 list (index 0 / 1)
ITEM_KEYS = {"k", "n", "u", "s", "c", "p", "o", "img"}
MIN_KEEP = 0.5          # refuse a result with < 50% of the previous items (storefront hiccup)


def _clean(msg, agent):
    msg = str(msg or "")
    if agent:
        msg = msg.replace(agent, "***")
    return re.sub(r"agent_[0-9A-Za-z-]+", "***", msg)[:200]


def build(get_json=None, out=OUT, agent=None, sleep=None):
    agent = (agent if agent is not None else os.environ.get("STOREFRONT_AGENT", "")).strip()
    if not re.fullmatch(r"agent_[0-9A-Za-z-]{6,80}", agent):
        print("STOREFRONT_AGENT is not set (GitHub secret)"); return 2
    catalog_live.AGENT = agent
    catalog_live.WAREHOUSES = ["KL"]

    class _Redact(logging.Filter):   # catalog_live logs str(e)[:80]; a requests error can contain the request URL
        def filter(self, rec):
            rec.msg = _clean(rec.getMessage(), agent); rec.args = ()
            return True
    lg = logging.getLogger("catalog_live")
    if not any(isinstance(f, _Redact) for f in lg.filters):
        lg.addFilter(_Redact())
    with tempfile.TemporaryDirectory() as td:
        raw = os.path.join(td, "raw.json")
        kw = {"get_json": get_json}
        if sleep is not None:
            kw["sleep"] = sleep
        r = catalog_live.sync_once(raw, **kw)
        if not r.get("ok"):
            print("fetch failed: %s" % _clean(r.get("error"), agent)); return 1
        data = json.load(open(raw, encoding="utf-8"))
    rows = []
    for wh, lst in (data.get("warehouses") or {}).items():
        for x in lst or []:
            x = dict(x); x["wh"] = wh; rows.append(x)
    items, by_cat = shop_cart.build_items(rows)
    upd = (data.get("wh_updated") or {}).get("KL") or data.get("updated_at") or ""
    doc = shop_miniapp.export_catalog(items, by_cat, upd if isinstance(upd, str) else "", CS)
    for it in doc["items"]:
        if set(it) != ITEM_KEYS:
            print("unexpected item fields"); return 1
    prev = None
    try:
        prev = json.load(open(out, encoding="utf-8"))
    except Exception:
        pass
    n_prev = len((prev or {}).get("items") or [])
    if n_prev >= 20 and len(doc["items"]) < n_prev * MIN_KEEP:
        print("refused: %d items vs %d before (kept old file)" % (len(doc["items"]), n_prev)); return 1
    if not doc["items"]:
        print("refused: 0 items"); return 1
    strip = lambda d: {k: v for k, v in (d or {}).items() if k != "updated_at"}
    if prev and strip(prev) == strip(doc):
        print("unchanged: %d items" % len(doc["items"])); return 0
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, out)
    print("updated: %d items (was %d)" % (len(doc["items"]), n_prev))
    return 0


if __name__ == "__main__":
    sys.exit(build())
