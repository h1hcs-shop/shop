"""Offline test of the generator with a FICTIONAL storefront (no network). Run: python tools/test_build_catalog.py"""
import json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import build_catalog as B

AG = "agent_" + "0" * 8 + "-fake"      # fictional, not hex-only so the secret scan rule stays meaningful


def prod(name, cat, cents, unit="条", spec="", img="", orig=None, avail=True, code=""):
    return {"id": "fake-" + name, "name": name, "category": cat, "subcategory": "", "saleUnit": unit, "specification": spec, "code": code,
            "guidePriceCents": cents, "originalPriceCents": orig, "available": avail, "imageUrl": img}


def fake_store(products, per_page=3, fail=False):
    calls = []
    def get_json(params):
        calls.append(dict(params))
        if fail:
            raise RuntimeError("connection error for https://x/api?agent=%s" % params.get("agent"))
        assert params["warehouse"] == "KL"
        p = int(params["page"]); chunk = products[(p - 1) * per_page: p * per_page]
        return {"warehouse": "KL", "products": chunk, "items": chunk, "total": len(products), "page": p,
                "pageSize": per_page, "totalPages": max(1, -(-len(products) // per_page)), "hasMore": p * per_page < len(products)}
    return get_json, calls


PRODUCTS = [prod("虚构牌香烟（硬）", "香烟", 4500, spec="10包", img="/products/cigarettes/1.webp", orig=5000, avail=False),
            prod("虚构茅台", "酒水", 150000, unit="瓶"), prod("虚构青岛啤酒", "酒水", 6000, unit="箱"),
            prod("虚构槟榔", "槟榔", 2500, unit="包"), prod("虚构饼干", "休闲零食", 500, unit="包"),
            prod("虚构电子烟", "电子烟", 9000, unit="支")]   # Kimi 21:15: e-cigs are in too (removable via CAT_BLACKLIST)
# Kimi 21:05 / 21:15: EVERY KL mall category (fictional rows), incl. 重振雄风 and categories the code does not know yet
GOODS_PRODUCTS = [prod("虚构洗发水", "个人洗护", 1590, unit="瓶", img="/products/care/9.webp"),
                  prod("虚构方便面", "方便速食", 350, unit="包"), prod("虚构矿泉水", "饮料乳品", 120, unit="瓶"),
                  prod("虚构抽纸", "家居日用", 990, unit="提"), prod("虚构保健品", "重振雄风", 9900, unit="盒"),
                  prod("虚构一次性烟弹", "休闲零食", 3000, unit="盒"), prod("虚构新品类商品", "虚构新大类", 100, unit="件")]


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.out = os.path.join(self.d, "catalog.json")

    def run_b(self, products=PRODUCTS, **kw):
        g, calls = fake_store(products, **kw)
        return B.build(get_json=g, out=self.out, agent=AG, sleep=lambda s: None), calls

    def test_build_fields_no_stock_change_detection(self):
        rc, calls = self.run_b()
        self.assertEqual(rc, 0); self.assertTrue(calls); self.assertTrue(all(c["agent"] == AG for c in calls))
        raw = open(self.out, encoding="utf-8").read(); d = json.loads(raw)
        names = [i["n"] for i in d["items"]]
        self.assertIn("虚构牌香烟（硬）", names); self.assertIn("虚构槟榔", names)
        self.assertIn("虚构饼干", names)                                         # 21:05: snacks are in the 下单入口 too
        self.assertIn("虚构电子烟", names); self.assertEqual(len(names), 6)       # 21:15: all mall products
        for w in ("available", "库存", "stock", "t.me"):
            self.assertNotIn(w, raw)
        for it in d["items"]:
            self.assertFalse({"address", "lat", "lng", "phone", "stock"} & set(it))
        # v3: only the bot's PUBLIC 客服 usernames (for the pre-filled jump) + page switches; geocoding off by default
        self.assertEqual(d["cs"], [{"name": "阿霞", "icon": "👩", "user": "hycs1313"}])        # Kimi 21:03: CS_DROP = ["zycs7"]
        self.assertEqual({k: d["opts"][k] for k in ("location", "phone", "jump", "pay", "geocode")},
                         {"location": True, "phone": True, "jump": True, "pay": True, "geocode": False})
        self.assertTrue(d["opts"]["geocode_url"].startswith("https://"))
        hard = next(i for i in d["items"] if i["n"] == "虚构牌香烟（硬）")
        self.assertEqual((hard["p"], hard["o"], hard["img"]), (45, 50, "https://h1hcs.com/products/cigarettes/1.webp"))
        self.assertEqual(len(hard["k"]), 10)
        m = os.path.getmtime(self.out)
        rc, _ = self.run_b(); self.assertEqual(rc, 0); self.assertEqual(os.path.getmtime(self.out), m)   # unchanged
        p2 = [dict(x) for x in PRODUCTS]; p2[1]["guidePriceCents"] = 160000
        rc, _ = self.run_b(p2); self.assertEqual(rc, 0)
        self.assertEqual(next(i for i in json.load(open(self.out))["items"] if i["n"] == "虚构茅台")["p"], 1600)

    def test_failures_keep_old_file_and_hide_agent(self):
        self.run_b(); before = open(self.out).read()
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc, _ = self.run_b(fail=True)
        self.assertEqual(rc, 1); self.assertEqual(open(self.out).read(), before); self.assertNotIn(AG, buf.getvalue())
        import logging
        rec = logging.LogRecord("catalog_live", logging.WARNING, "", 0, "failed (%s)", ("url?agent=" + AG,), None)
        for f in logging.getLogger("catalog_live").filters:
            f.filter(rec)
        self.assertNotIn(AG, rec.getMessage())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(B.build(get_json=fake_store(PRODUCTS)[0], out=self.out, agent="", sleep=lambda s: None), 2)

    def test_cs_drop_only_axia_and_rollback(self):
        # Kimi 21:03 「客服阿东全部去掉，就只留一个客服阿霞」: config CS_DROP; 阿霞 stays index 0 (the page sends the index)
        self.assertEqual(B.CS_DROP, ["zycs7"]); self.assertEqual(B.CS_ALL[0]["user"], "hycs1313")
        self.assertEqual(B.CS, [c for c in B.CS_ALL if c["user"] not in B.CS_DROP])
        raw = (self.run_b(), open(self.out, encoding="utf-8").read())[1]
        self.assertNotIn("zycs7", raw); self.assertNotIn("阿东", raw)
        old = B.CS
        try:                                   # rollback = CS_DROP = [] -> both 客服 again, same order as before
            B.CS = [c for c in B.CS_ALL if c["user"] not in []]
            self.assertEqual(self.run_b()[0], 0)
            d = json.load(open(self.out, encoding="utf-8"))
            self.assertEqual([c["user"] for c in d["cs"]], ["hycs1313", "zycs7"])
        finally:
            B.CS = old

    def test_jump_off_exports_no_usernames(self):
        o = dict(B.OPTS)
        try:
            B.OPTS["jump"] = False
            self.assertEqual(self.run_b()[0], 0)
            d = json.load(open(self.out, encoding="utf-8"))
            self.assertEqual(d["cs"], [{"name": "阿霞", "icon": "👩"}])
            self.assertFalse(d["opts"]["jump"])
        finally:
            B.OPTS.clear(); B.OPTS.update(o)

    def test_shrink_guard(self):
        many = [prod("虚构烟%02d" % i, "香烟", 3000 + i) for i in range(40)]
        self.run_b(many, per_page=50)
        with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            rc, _ = self.run_b(many[:10], per_page=50)
        self.assertEqual(rc, 1); self.assertEqual(len(json.load(open(self.out))["items"]), 40)

    def test_secret_scan_clean(self):
        import secret_scan
        self.assertEqual(secret_scan.scan(), [])




class TGoods(unittest.TestCase):
    """Kimi 21:05: multi-category Mini App catalog (烟酒 first, then the mall's categories), same prices, no stock."""
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.out = os.path.join(self.d, "catalog.json")

    def build(self, products, goods=True, blacklist=()):
        old = B.GOODS, B.CAT_BLACKLIST; B.GOODS = goods; B.CAT_BLACKLIST = list(blacklist)
        try:
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                return B.build(get_json=fake_store(products)[0], out=self.out, agent=AG, sleep=lambda s: None)
        finally:
            B.GOODS, B.CAT_BLACKLIST = old

    def test_categories_order_exclusions_prices(self):
        self.assertEqual(self.build(PRODUCTS + GOODS_PRODUCTS), 0)
        d = json.load(open(self.out, encoding="utf-8"))
        ids = [c["id"] for c in d["cats"]]
        new = B.shop_cart.mall_cat_id("虚构新大类")
        self.assertEqual(ids, ["cig", "baijiu", "beer", "betel", "vape", "snack", "drinkm", "instant", "care", "home", "adult", new])
        self.assertEqual([c["name"] for c in d["cats"]][4:], ["💨 电子烟", "🍪 休闲零食", "🥤 饮料乳品", "🍜 方便速食", "🧴 个人洗护",
                                                             "🏠 家居日用", "💊 重振雄风", "🛒 虚构新大类"])      # 烟酒 first, all mall cats
        names = [i["n"] for i in d["items"]]
        for n in ("虚构电子烟", "虚构保健品", "虚构一次性烟弹", "虚构新品类商品"):
            self.assertIn(n, names)
        # v4: items follow the view groups (香烟 / 酒水 / 重振雄风 / 槟榔 first, Kimi 04:10), each group contiguous
        gorder = [c for g in d["view"]["groups"] for c in g["cats"]]
        self.assertEqual([i["c"] for i in d["items"]], sorted([i["c"] for i in d["items"]], key=gorder.index))
        self.assertEqual([g["id"] for g in d["view"]["groups"]][:4], ["cig", "liquor", "adult", "betel"])
        sh = next(i for i in d["items"] if i["n"] == "虚构洗发水")
        self.assertEqual((sh["p"], sh["c"], sh["img"]), (15.9, "care", "https://h1hcs.com/products/care/9.webp"))
        raw = open(self.out, encoding="utf-8").read()
        for w in ("available", "库存", "stock"):
            self.assertNotIn(w, raw)

    def test_category_blacklist_one_step(self):
        self.assertEqual(self.build(PRODUCTS + GOODS_PRODUCTS), 0)
        self.assertEqual(self.build(PRODUCTS + GOODS_PRODUCTS, blacklist=["电子烟", "重振雄风"]), 0)   # not refused as a shrink
        d = json.load(open(self.out, encoding="utf-8"))
        self.assertNotIn("vape", [c["id"] for c in d["cats"]]); self.assertNotIn("adult", [c["id"] for c in d["cats"]])
        names = [i["n"] for i in d["items"]]
        self.assertNotIn("虚构电子烟", names); self.assertNotIn("虚构保健品", names); self.assertIn("虚构一次性烟弹", names)
        self.assertEqual(self.build(PRODUCTS + GOODS_PRODUCTS, blacklist=["香烟"]), 0)
        self.assertNotIn("cig", [c["id"] for c in json.load(open(self.out))["cats"]])

    def test_rollback_goods_off_is_not_a_shrink(self):
        many = PRODUCTS + [prod("虚构零食%02d" % i, "休闲零食", 100 + i, unit="包") for i in range(40)]
        self.assertEqual(self.build(many), 0)
        self.assertEqual(len(json.load(open(self.out))["items"]), 46)
        self.assertEqual(self.build(many, goods=False), 0)          # 46 -> 4 items: allowed, the switch was turned off
        d = json.load(open(self.out))
        self.assertEqual(len(d["items"]), 4); self.assertNotIn("snack", [c["id"] for c in d["cats"]])   # 烟酒槟榔 only
        self.assertEqual(self.build(many), 0)
        self.assertEqual(self.build(PRODUCTS[:1]), 1)                 # a real hiccup (46 -> 1) is still refused


class TScan(unittest.TestCase):
    """secret_scan SANITIZE (fix1, Actions #11): only canonical UUIDs inside h1hcs.com "img" values and the "k" codes of
    site/catalog.json are neutralised; real ids / tokens are still found everywhere. All values below are FICTIONAL."""
    UUID_DIGITS = "fd10eaed-0241-4fab-af5d-" + "0" * 11 + "1"          # last group all digits (the #11 case), fictional
    def scan(self, catalog_line, rel="site/catalog.json"):
        import secret_scan
        d = tempfile.mkdtemp(); p = os.path.join(d, *rel.split("/")); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(catalog_line)
        return [n for _r, _i, n in secret_scan.scan(d)]

    def img(self, url):
        return '{"items":[{"k":"%s","n":"虚构零食","img":"%s"}]}' % ("12345" + "67890", url)    # all-digit k: sanitised

    def test_public_image_uuid_is_not_a_finding(self):
        for u in ("https://h1hcs.com/api/erp?resource=productImage&productId=pospal_product_%s&w=480&v=1v6t2l" % self.UUID_DIGITS,
                  "https://h1hcs.com/api/erp?resource=productImage&productId=%s&w=480&v=abc" % self.UUID_DIGITS,
                  "https://h1hcs.com/products/pospal/1234567890123456.webp?v=x1"):
            self.assertEqual(self.scan(self.img(u)), [], u)

    def test_real_ids_and_tokens_still_found(self):
        tid = "70000" + "01011"                                               # fictional telegram-style user id
        cases = {
            "id in img query": self.img("https://h1hcs.com/api/erp?resource=productImage&productId=pospal_product_%s&uid=%s" % (self.UUID_DIGITS, tid)),
            "id instead of uuid": self.img("https://h1hcs.com/api/erp?resource=productImage&productId=%s&w=480" % tid),
            "uuid in name": '{"items":[{"n":"虚构 %s","img":""}]}' % self.UUID_DIGITS,
            "uuid on other host": self.img("https://example.invalid/x?productId=%s&w=1" % self.UUID_DIGITS),
            "bare id": '{"items":[{"n":"虚构","owner":-100%s}]}' % tid,
            "13-digit k": '{"items":[{"k":"%s"}]}' % ("12345" + "67890" + "123"),
            "uppercase uuid": self.img("https://h1hcs.com/api/erp?productId=FD10EAED-0241-4FAB-AF5D-%s&w=1" % ("0" * 11 + "1")),
        }
        for why, line in cases.items():
            self.assertIn("long_numeric_id", self.scan(line), why)
        tok = "%s:%s" % (tid[:9] + "1", "A" * 35)                       # fictional bot-token shape
        self.assertIn("telegram_bot_token", self.scan(self.img("https://h1hcs.com/x?t=%s" % tok)))
        self.assertIn("storefront_agent_id", self.scan(self.img("https://h1hcs.com/api/erp?agent=" + "agent_" + "0123abcd&productId=%s" % self.UUID_DIGITS)))
        # the UUID exemption is for site/catalog.json only
        self.assertIn("long_numeric_id", self.scan(self.img("https://h1hcs.com/api/erp?productId=%s&w=1" % self.UUID_DIGITS), rel="site/other.json"))

class TView(unittest.TestCase):
    """shop-miniapp-v4 (Kimi 11-14 04:10): merged 酒水, 重振雄风 after 酒水, brand + price order, 整箱 inside the single item.
    FICTIONAL products only."""
    P = [prod("虚构利群 软", "香烟", 18000), prod("虚构中华 硬", "香烟", 32000), prod("虚构利群 铂金", "香烟", 50000),
         prod("虚构中华 软", "香烟", 50000), prod("虚构杂牌烟", "香烟", 90000),
         prod("虚构青岛啤酒 330ML", "酒水", 700, unit="瓶"), prod("虚构青岛啤酒 330ML（整箱）", "酒水", 13000, unit="箱"),
         prod("虚构茅台 53度", "酒水", 168000, unit="瓶"), prod("虚构轩尼诗XO", "酒水", 120000, unit="瓶"),
         prod("虚构奔富 750ML", "酒水", 49000, unit="瓶"), prod("虚构强爽柠檬", "酒水", 1800, unit="瓶"),
         prod("虚构100和成天下槟榔", "槟榔", 8500, unit="包"), prod("虚构200和成天下槟榔", "槟榔", 17000, unit="包"),
         prod("虚构50新发槟榔", "槟榔", 3500, unit="包"),
         prod("虚构可乐330ml", "饮料乳品", 300, unit="罐", spec="330ml", img="/p/cola.webp"),
         prod("虚构可乐330ml（整箱）", "饮料乳品", 6800, unit="箱", spec="24罐", img="/p/cola.webp"),
         prod("虚构矿泉水", "饮料乳品", 100, unit="瓶"), prod("虚构矿泉水×12瓶", "饮料乳品", 1100, unit="箱"),
         prod("虚构椰汁1L", "饮料乳品", 1500, unit="盒"), prod("虚构只有整箱的水（整箱）", "饮料乳品", 4500, unit="箱"),
         prod("虚构保健品", "重振雄风", 9900, unit="盒"), prod("虚构饼干", "休闲零食", 500, unit="包"),
         prod("虚构饼干（整箱）", "方便速食", 4000, unit="箱")]       # other category: NOT a pack of 虚构饼干

    def setUp(self):
        self.d = tempfile.mkdtemp(); self.out = os.path.join(self.d, "catalog.json")

    def build(self, products=None, view=True):
        old = B.VIEW; B.VIEW = view
        try:
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                rc = B.build(get_json=fake_store(products or self.P, per_page=50)[0], out=self.out, agent=AG, sleep=lambda s: None)
        finally:
            B.VIEW = old
        self.assertEqual(rc, 0)
        return json.load(open(self.out, encoding="utf-8"))

    def names(self, d, cats, heads_only=True):
        hidden = {i for p in d["view"]["packs"] for i in p[1:]}
        return [it["n"] for i, it in enumerate(d["items"]) if it["c"] in cats and not (heads_only and i in hidden)]

    def test_groups_chips(self):
        d = self.build()
        g = d["view"]["groups"]
        self.assertEqual([x["id"] for x in g], ["cig", "liquor", "adult", "betel", "snack", "drinkm", "instant"])
        liq = g[1]
        self.assertEqual((liq["name"], liq["cats"], liq.get("sub")), ("酒水", ["baijiu", "spirits", "wine", "beer", "drink"], True))
        self.assertEqual({x["id"]: x["short"] for x in g}["drinkm"], "饮料")                 # short chip labels
        self.assertEqual({x["id"]: x["name"] for x in g}["drinkm"], "饮料乳品")
        for it in d["items"]:
            self.assertEqual(set(it), B.ITEM_KEYS)                                            # item fields unchanged

    def test_cigarettes_brand_then_price(self):
        d = self.build()
        # 杂牌 900 first (its own brand group), then 中华 (top 500, 2 items) before 利群 (top 500, 2 items) by name tie-break
        self.assertEqual(self.names(d, ["cig"]), ["虚构杂牌烟", "虚构中华 软", "虚构中华 硬", "虚构利群 铂金", "虚构利群 软"])

    def test_liquor_order_baijiu_spirits_wine_beer_other(self):
        d = self.build()
        self.assertEqual(self.names(d, ["baijiu", "spirits", "wine", "beer", "drink"]),
                         ["虚构茅台 53度", "虚构轩尼诗XO", "虚构奔富 750ML", "虚构青岛啤酒 330ML", "虚构强爽柠檬"])
        self.assertEqual(self.names(d, ["betel"]), ["虚构200和成天下槟榔", "虚构100和成天下槟榔", "虚构50新发槟榔"])

    def test_packs_inside_single_and_price_order(self):
        d = self.build()
        it = d["items"]
        packs = {it[p[0]]["n"]: [it[i]["n"] for i in p[1:]] for p in d["view"]["packs"]}
        self.assertEqual(packs, {"虚构青岛啤酒 330ML": ["虚构青岛啤酒 330ML（整箱）"], "虚构可乐330ml": ["虚构可乐330ml（整箱）"],
                                 "虚构矿泉水": ["虚构矿泉水×12瓶"]})
        for p in d["view"]["packs"]:
            self.assertEqual(p[1:], list(range(p[0] + 1, p[0] + len(p))))      # packs right after their single
            self.assertTrue(all(it[i]["c"] == it[p[0]]["c"] for i in p))
        # list = singles only, price high -> low; a pack with no single (and a 箱 of another category) stays a normal item,
        # after the single items
        self.assertEqual(self.names(d, ["drinkm"]), ["虚构椰汁1L", "虚构可乐330ml", "虚构矿泉水", "虚构只有整箱的水（整箱）"])
        self.assertIn("虚构饼干（整箱）", self.names(d, ["instant"]))
        raw = json.dumps(d["view"])
        for x in it:
            self.assertNotIn(x["k"], raw)              # the view never repeats product codes (secret scan / size)

    def test_rollback_view_off(self):
        d = self.build(view=False)
        self.assertNotIn("view", d)
        self.assertEqual(len(d["items"]), len(self.P))
        d2 = self.build()
        self.assertEqual(sorted(i["k"] for i in d["items"]), sorted(i["k"] for i in d2["items"]))   # same products, reordered

    def test_duplicate_single_names_prefer_same_image(self):
        import catalog_view as V
        doc = {"cats": [{"id": "drinkm", "name": "🥤 饮料乳品"}], "items": [
            {"k": "a" * 10, "n": "虚构凉茶（罐）", "u": "罐", "s": "罐", "c": "drinkm", "p": 3.5, "o": None, "img": "https://h1hcs.com/a.webp"},
            {"k": "b" * 10, "n": "虚构凉茶（罐）", "u": "罐", "s": "310ml", "c": "drinkm", "p": 3.5, "o": None, "img": "https://h1hcs.com/b.webp"},
            {"k": "c" * 10, "n": "虚构凉茶（罐）（整箱）", "u": "箱", "s": "24罐", "c": "drinkm", "p": 79.0, "o": None, "img": "https://h1hcs.com/b.webp"}]}
        V.build_view(doc)
        p = doc["view"]["packs"]
        self.assertEqual(len(p), 1); self.assertEqual(doc["items"][p[0][0]]["k"], "b" * 10)
        self.assertEqual(V.brand("100张新发槟榔（八方来财）"), "新发"); self.assertEqual(V.brand("1916 细支"), "黄鹤楼")
        self.assertIsNone(V.pack_base({"n": "虚构天地壹号苹果醋（箱）", "u": "瓶"}))


if __name__ == "__main__":
    unittest.main(verbosity=1)
