"""Hourly catalog builder for the 「下单入口」 Mini App (GitHub Actions): 烟酒槟榔 + (GOODS) the mall's other KL categories.

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
# same order as the bot's 客服 list (index 0 / 1). "user" = the PUBLIC usernames the bot already shows in its 客服 buttons;
# exported only when OPTS["jump"] is on (the page needs them to open the 客服 chat with the order pre-filled).
CS_ALL = [{"name": "阿霞", "icon": "👩", "user": "hycs1313"}, {"name": "阿东", "icon": "👨", "user": "zycs7"}]
# Kimi 21:03 「客服阿东全部去掉，就只留一个客服阿霞」. Rollback = CS_DROP = [] and push (page shows both again; pair it with
# the bot switch cs_only_axia: false). Only trailing entries may be dropped: the page sends the index, 阿霞 must stay 0.
# With ONE 客服 left the page shows no 「选择客服」 and every order goes to 阿霞.
CS_DROP = ["zycs7"]
CS = [c for c in CS_ALL if c["user"] not in CS_DROP]
# Page switches (shop-miniapp-v3). Rollback = set to False and push: the next build changes catalog.json and redeploys.
#   location: 📍 定位 + manual address   phone: 📱 requestContact + manual phone   jump: open the 客服 chat pre-filled on submit
#   geocode: reverse geocoding of the coordinates via geocode_url. OFF: the public OSM Nominatim API may only be used after
#   a deliberate, informed decision by the operator (usage policy: <= 1 req/s, attribution, switchable without an app
#   update, no autocomplete/bulk). Turn on only after reading https://operations.osmfoundation.org/policies/nominatim/ .
#   pay: 「付款方式：货到付款」 required choice (现金 / TNG / USDT / 微信 / 支付宝), Kimi 20:49
OPTS = {"location": True, "phone": True, "jump": True, "pay": True, "geocode": False,
        "geocode_url": "https://nominatim.openstreetmap.org/reverse"}
# Kimi 21:05 / 21:15「是商城里面的所有品，都上」: EVERY category of the KL storefront (shop_cart.GOODS_CATS + any new one),
# same prices, no stock. Rollback = GOODS False and push: the next build is 烟酒槟榔 only (as in v2).
GOODS = True
# One-step removal of whole mall categories (mall names as shown in the storefront), e.g. ["电子烟"] or ["电子烟", "重振雄风"].
# Push -> the next hourly build drops them. Keep the bot's config.json "shop_app_cat_blacklist" the same.
CAT_BLACKLIST = []
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
    items, by_cat = shop_cart.build_items(rows, goods=GOODS, blacklist=CAT_BLACKLIST)
    upd = (data.get("wh_updated") or {}).get("KL") or data.get("updated_at") or ""
    doc = shop_miniapp.export_catalog(items, by_cat, upd if isinstance(upd, str) else "", CS, opts=OPTS, cs_user=bool(OPTS.get("jump")))
    for it in doc["items"]:
        if set(it) != ITEM_KEYS:
            print("unexpected item fields"); return 1
    prev = None
    try:
        prev = json.load(open(out, encoding="utf-8"))
    except Exception:
        pass
    # shrink guard only over the categories this build is meant to contain (switching GOODS off is not a "hiccup")
    bl_ids = {shop_cart.mall_cat_id(m) for m in CAT_BLACKLIST if m not in ("香烟", "酒水", "槟榔")} | \
             {c for c, m in shop_cart.MALL_OF.items() if m in CAT_BLACKLIST}
    if GOODS:   # any category except blacklisted ones (new mall categories have dynamic ids)
        n_prev = sum(1 for it in ((prev or {}).get("items") or []) if isinstance(it, dict) and it.get("c") not in bl_ids)
    else:
        allowed = {c for c, _n in shop_cart.CATS}
        n_prev = sum(1 for it in ((prev or {}).get("items") or []) if isinstance(it, dict) and it.get("c") in allowed)
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
    per = {}
    for it in doc["items"]:
        per[it["c"]] = per.get(it["c"], 0) + 1
    print("updated: %d items (was %d) | %s" % (len(doc["items"]), n_prev, " ".join("%s=%d" % (c, per[c]) for c in per)))
    return 0


if __name__ == "__main__":
    sys.exit(build())
