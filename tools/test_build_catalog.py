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
            prod("虚构电子烟", "电子烟", 9000, unit="支")]   # mall files e-cigs under their own category -> excluded


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
        self.assertNotIn("虚构饼干", names)                                      # snacks are not in the 烟酒 shop
        self.assertNotIn("虚构电子烟", names); self.assertEqual(len(names), 4)
        for w in ("available", "库存", "stock", "t.me", "\"user\""):
            self.assertNotIn(w, raw)
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

    def test_shrink_guard(self):
        many = [prod("虚构烟%02d" % i, "香烟", 3000 + i) for i in range(40)]
        self.run_b(many, per_page=50)
        with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            rc, _ = self.run_b(many[:10], per_page=50)
        self.assertEqual(rc, 1); self.assertEqual(len(json.load(open(self.out))["items"]), 40)

    def test_secret_scan_clean(self):
        import secret_scan
        self.assertEqual(secret_scan.scan(), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
