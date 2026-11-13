"""shop-miniapp-v4 display view for the 「下单入口」 page (Kimi 2026-11-14 04:10 UTC+8). Pure function, no I/O, no network.

1. Categories: 香烟 / 酒水 (白酒、洋酒、葡萄酒、啤酒、其他酒水 merged) / 重振雄风 (right after 酒水) / 槟榔, then every
   other mall category in the catalog's order. The page shows them as wrapping chips (2 rows, 3 if the screen is narrow).
2. Order: 香烟 = the mall's own order (v4.1, Kimi 04:51). 酒水 (per sub-category)、槟榔、重振雄风: brands together, brand groups by their highest price (high -> low),
   inside a brand price high -> low. 酒水 sub-categories: 白酒 -> 洋酒 -> 葡萄酒 -> 啤酒 -> 其他酒水. Other categories: price
   high -> low (then name, so same-brand names starting alike stay together). Items sold only by the 箱 (no single item)
   come after the single items of their category.
3. 单件 / 整箱: an item named "<X>（整箱）" (or "<X>×12瓶", unit 箱) in the same category as an item named exactly "<X>" is a
   PACK of it. The page lists only the single item (single price) and offers the pack inside its detail sheet. Both keep
   their own product codes, so the order the bot receives is unchanged (no bot change needed).

The view only REORDERS doc["items"] and adds doc["view"] = {"v":1,"groups":[...],"packs":[[single_idx, pack_idx, ...]]}
(indices into the reordered items: product codes are never repeated, so no new numeric-looking strings for the secret scan).
Item fields stay exactly ITEM_KEYS. Pages without view support simply ignore it."""
import re

VIEW_VERSION = 1
LIQUOR = ["baijiu", "spirits", "wine", "beer", "drink"]          # Kimi: 白酒先，再洋酒，再葡萄酒，再啤酒 (+ 劲酒/强爽 last)
# (group id, chip name, category ids, sub-headers). Groups with no items are dropped.
HEAD_GROUPS = [("cig", "香烟", ["cig"], False), ("liquor", "酒水", LIQUOR, True),
               ("adult", "重振雄风", ["adult"], False), ("betel", "槟榔", ["betel"], False)]
GROUP_ICON = {"liquor": "🍷"}
# short chip labels so 13+ chips fit in 2 rows on a 360-430 px phone; the section title keeps the full mall name
SHORT = {"休闲零食": "零食", "饮料乳品": "饮料", "方便速食": "速食", "粮油调味": "粮油", "冷冻食品": "冷冻",
         "个人洗护": "洗护", "家居日用": "日用"}
# v4.1 (Kimi 11-14 04:51「香烟的排序跟华润万家商城的排序一致」): 香烟 keeps the storefront's own order exactly as the mall
# returns it (catalog_live -> shop_cart.build_items -> export_catalog keep the row order). Checked 2026-11-14 04:5x UTC+8:
# the mall's 香烟 category list (category=香烟 / feed=KL:香烟) == the unfiltered storefront order, 102/102 items; every
# catalogCategories.position is unset, so the mall lists them by name. Rollback = remove "cig" from MALL_ORDER.
MALL_ORDER = {"cig"}
BRAND_SORT = {"betel", "adult"} | set(LIQUOR)
# brand keywords, first match wins (more specific first). Alias -> brand shown together.
BRANDS = [("1916", "黄鹤楼"), ("黄鹤楼", "黄鹤楼"), ("和天下", "和天下"), ("中华", "中华"), ("利群", "利群"),
          ("芙蓉王", "芙蓉王"), ("南京", "南京"), ("云烟", "云烟"), ("双喜", "双喜"), ("七匹狼", "七匹狼"), ("灰狼", "七匹狼"),
          ("白沙", "白沙"), ("牡丹", "牡丹"), ("贵烟", "贵烟"), ("好日子", "好日子"), ("七星", "七星"), ("卡比龙", "卡比龙"),
          ("玉溪", "玉溪"), ("爱喜", "爱喜"), ("红塔山", "红塔山"), ("荷花", "荷花"), ("黄金叶", "黄金叶"), ("阿里山", "阿里山"),
          ("苏烟", "苏烟"), ("长白山", "长白山"), ("真龙", "真龙"),
          ("茅台", "茅台"), ("五粮液", "五粮液"), ("洋河", "洋河"), ("汾酒", "汾酒"), ("郎酒", "郎酒"), ("江小白", "江小白"),
          ("牛栏山", "牛栏山"), ("二锅头", "红星"), ("老白干", "老白干"), ("轩尼诗", "轩尼诗"), ("马爹利", "马爹利"),
          ("麦凯伦", "麦卡伦"), ("麦卡伦", "麦卡伦"), ("奔富", "奔富"), ("乌苏", "乌苏"), ("哈尔滨", "哈尔滨"), ("嘉士伯", "嘉士伯"),
          ("百威", "百威"), ("老虎", "老虎"), ("雁荡山", "雁荡山"), ("雪花", "雪花"), ("青岛", "青岛"), ("劲酒", "劲酒"),
          ("强爽", "强爽"), ("和成天下", "和成天下"), ("新发", "新发"), ("湘潭铺子", "湘潭铺子"), ("枸杞槟榔", "湘潭铺子"),
          ("悍马", "悍马"), ("泰国果冻", "泰国果冻")]
_PACK_SUFFIX = re.compile(r"\s*(?:[（(]整箱[)）]|[×xX*]\s*\d+\s*(?:瓶|罐|盒|包|袋|桶|杯|支|条|听))\s*$")


def brand(name):
    n = name or ""
    for kw, b in BRANDS:
        if kw in n:
            return b
    n = re.sub(r"^[\s\d（()）]+张?", "", n)                    # "100张新发槟榔" -> "新发槟榔"
    m = re.match(r"[^\s\d（(·]+", n)
    return m.group(0) if m else n


def pack_base(it):
    """-> the single item's name if `it` looks like a 整箱 pack, else None."""
    n = it.get("n") or ""
    if not _PACK_SUFFIX.search(n):
        return None
    if "整箱" not in n and it.get("u") != "箱":
        return None
    b = _PACK_SUFFIX.sub("", n).strip()
    return b or None


def _price(it):
    p = it.get("p")
    return -float(p) if isinstance(p, (int, float)) and not isinstance(p, bool) else float("inf")


def _plain_sort(rows):
    return sorted(rows, key=lambda it: (_price(it), it.get("n") or "", it.get("k") or ""))


def _brand_sort(rows):
    by = {}
    for it in rows:
        by.setdefault(brand(it.get("n")), []).append(it)
    groups = [(_plain_sort(v), b) for b, v in by.items()]
    groups.sort(key=lambda g: (_price(g[0][0]), -len(g[0]), g[1]))
    return [it for g, _b in groups for it in g]


def cat_short(name):
    n = re.sub(r"^\S+\s", "", name or "")
    return SHORT.get(n, n)


def build_view(doc):
    """Reorders doc["items"] in place (display order) and sets doc["view"]. Returns doc."""
    items = list(doc.get("items") or [])
    cats = [c for c in (doc.get("cats") or []) if isinstance(c, dict)]
    cat_ids = [c["id"] for c in cats]
    # 1. packs: pack -> its single (same category, exact base name, single not a 箱 itself; prefer the same image)
    by_name = {}
    for it in items:
        if it.get("u") != "箱":
            by_name.setdefault((it.get("c"), it.get("n")), []).append(it)
    pack_of = {}                                  # pack k -> single k
    for it in items:
        b = pack_base(it)
        if not b:
            continue
        cand = [s for s in by_name.get((it.get("c"), b), []) if s["k"] != it["k"]]
        if not cand:
            continue
        same = [s for s in cand if s.get("img") and s.get("img") == it.get("img")]
        pack_of[it["k"]] = (same or cand)[0]["k"]
    packs = {}
    for it in items:
        if it["k"] in pack_of:
            packs.setdefault(pack_of[it["k"]], []).append(it)
    for v in packs.values():
        v.sort(key=lambda x: (-_price(x), x.get("n") or "", x["k"]))     # cheaper pack first
    heads = [it for it in items if it["k"] not in pack_of]
    # 2. groups
    used, groups = set(), []
    for gid, name, cs, sub in HEAD_GROUPS:
        cs = [c for c in cs if c in cat_ids]
        used.update(cs)
        if cs:
            groups.append({"id": gid, "name": name, "cats": cs, "sub": sub})
    for c in cats:
        if c["id"] not in used:
            n = re.sub(r"^\S+\s", "", c.get("name") or "")
            groups.append({"id": c["id"], "name": n, "cats": [c["id"]], "sub": False})
    # 3. order
    out = []
    for g in groups:
        for c in g["cats"]:
            rows = [it for it in heads if it.get("c") == c]
            srt = (lambda r: list(r)) if c in MALL_ORDER else _brand_sort if c in BRAND_SORT else _plain_sort
            # a 整箱 with no single item (unit 箱) goes after the single items, so the list reads in single prices
            for it in srt([x for x in rows if x.get("u") != "箱"]) + srt([x for x in rows if x.get("u") == "箱"]):
                out.append(it)
                out.extend(packs.get(it["k"], []))
    seen = {it["k"] for it in out}
    out.extend(it for it in items if it["k"] not in seen)         # categories missing from cats (should not happen)
    idx = {it["k"]: i for i, it in enumerate(out)}
    vg = []
    for g in groups:
        n = sum(1 for it in heads if it.get("c") in g["cats"])
        if not n:
            continue
        e = {"id": g["id"], "name": g["name"], "short": SHORT.get(g["name"], g["name"]), "cats": g["cats"]}
        if g["sub"]:
            e["sub"] = True
        if g["id"] in GROUP_ICON:
            e["icon"] = GROUP_ICON[g["id"]]
        vg.append(e)
    doc["items"] = out
    doc["view"] = {"v": VIEW_VERSION, "groups": vg,
                   "packs": [[idx[s]] + [idx[p["k"]] for p in ps] for s, ps in packs.items() if s in idx]}
    doc["view"]["packs"].sort()
    return doc
