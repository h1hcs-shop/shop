"""shop-admin-v1: validates site/overrides.json (the PUBLIC copy of the owner's 🛠 商品管理 overrides, written by the bot).
Shape: {"v":1,"rev":int>=0,"at":str,"hide":[key],"price":{key: 0<number<=99999},"order":{cat:[key]}} with key = 10 lowercase
hex chars (shop_cart.item_key) and cat in cig / baijiu / spirits / wine / beer / drink. Nothing else is allowed (no names,
no ids, no personal data). Exit 0 ok / 1 invalid (prints the reason only). A missing file is ok (= no overrides)."""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "site", "overrides.json")
KEY = re.compile(r"^[0-9a-f]{10}$")
CATS = {"cig", "baijiu", "spirits", "wine", "beer", "drink"}


def check(d):
    if not isinstance(d, dict) or set(d) != {"v", "rev", "at", "hide", "price", "order"}:
        return "fields"
    if d["v"] != 1 or not isinstance(d["rev"], int) or isinstance(d["rev"], bool) or d["rev"] < 0 or not isinstance(d["at"], str) or len(d["at"]) > 40:
        return "header"
    if not isinstance(d["hide"], list) or len(d["hide"]) > 2000 or not all(isinstance(k, str) and KEY.match(k) for k in d["hide"]):
        return "hide"
    p = d["price"]
    if not isinstance(p, dict) or len(p) > 2000 or not all(KEY.match(k) and isinstance(v, (int, float)) and not isinstance(v, bool)
                                                            and 0 < v <= 99999 for k, v in p.items()):
        return "price"
    o = d["order"]
    if not isinstance(o, dict) or not set(o) <= CATS:
        return "order"
    for v in o.values():
        if not isinstance(v, list) or len(v) > 500 or len(set(v)) != len(v) or not all(isinstance(k, str) and KEY.match(k) for k in v):
            return "order"
    return None


def main(path=PATH):
    if not os.path.exists(path):
        print("overrides: none"); return 0
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        print("overrides: invalid json"); return 1
    e = check(d)
    print("overrides: %s" % ("ok rev=%d hide=%d price=%d order=%s" % (d["rev"], len(d["hide"]), len(d["price"]), ",".join(d["order"]) or "-")
                              if not e else "INVALID (%s)" % e))
    return 1 if e else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
