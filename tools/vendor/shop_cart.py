"""shop-cart-v1: 烟酒商城 (cigarettes / liquor / betel only) — catalog view, persistent cart, cart orders.
No payment, no stock, no name/phone/address. Store: private/shop/shop_v1.sqlite (dir 700, file 600)."""
import hashlib, json, os, re, sqlite3, threading, time
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))
IMAGE_BASE = "https://h1hcs.com"
CATS = [("cig", "🚬 香烟"), ("baijiu", "🥃 白酒"), ("beer", "🍺 啤酒"), ("spirits", "🥂 洋酒"),
        ("wine", "🍷 葡萄酒"), ("drink", "🍶 其他酒水"), ("betel", "🌰 槟榔")]
CAT_NAME = dict(CATS)
# 酒水细分：mall `subcategory` is empty for every product, so the split uses an EXPLICIT map keyed by the mall product
# code (bottle and 整箱 share one code), audited item-by-item against the live KL storefront on 2026-11-13 (82 酒水 rows /
# 47 codes). Codes not in the map (new products) fall back to the ordered name rules below.
LIQUOR_CODE_MAP = {
    # 白酒
    "DRINK-001": "baijiu", "DRINK-002": "baijiu", "DRINK-003": "baijiu", "DRINK-004": "baijiu", "DRINK-005": "baijiu",
    "DRINK-006": "baijiu", "DRINK-007": "baijiu", "DRINK-008": "baijiu", "DRINK-010": "baijiu", "DRINK-011": "baijiu",
    "DRINK-012": "baijiu", "DRINK-013": "baijiu", "DRINK-014": "baijiu", "DRINK-015": "baijiu", "DRINK-016": "baijiu",
    "DRINK-017": "baijiu",
    # 啤酒（含精酿/原浆）
    "DRINK-018": "beer", "DRINK-019": "beer", "DRINK-020": "beer", "DRINK-021": "beer", "DRINK-022": "beer",
    "DRINK-023": "beer", "DRINK-024": "beer", "DRINK-025": "beer", "DRINK-026": "beer", "DRINK-027": "beer",
    "DRINK-028": "beer", "DRINK-029": "beer", "DRINK-036": "beer", "DRINK-037": "beer", "DRINK-038": "beer",
    "DRINK-039": "beer", "DRINK-040": "beer", "XH02": "beer",
    # 洋酒
    "DRINK-041": "spirits", "DRINK-042": "spirits", "DRINK-043": "spirits", "DRINK-044": "spirits", "DRINK-046": "spirits",
    # 葡萄酒
    "DRINK-045": "wine",
    # 其他酒水：劲酒（保健/配制酒）、强爽系列（预调鸡尾酒，虽名含「伏特加」但不是洋酒）
    "DRINK-009": "drink", "DRINK-030": "drink", "DRINK-031": "drink", "DRINK-032": "drink", "DRINK-033": "drink",
    "DRINK-034": "drink", "DRINK-035": "drink",
}
# fallback rules for unmapped codes; ORDER MATTERS (ready-to-drink / 配制酒 first so "伏特加xx味" RTDs are not 洋酒)
_LIQ = [
    ("drink", r"强爽|rio|锐澳|预调|鸡尾酒|劲酒|果酒|梅酒|米酒|黄酒|料酒"),
    ("spirits", r"威士忌|白兰地|干邑|轩尼诗|人头马|马爹利|xo|vsop|伏特加|朗姆|龙舌兰|金酒|芝华士|尊尼获加|黑方|红方|杰克丹尼|百龄坛|麦卡伦|麦凯伦|格兰|hennessy|martell|remy|johnnie|chivas|absolut|whisky|whiskey|brandy|vodka|rum|gin|利口酒|百利"),
    ("baijiu", r"茅台|五粮液|汾酒|泸州|国窖|剑南春|洋河|梦之蓝|郎酒|二锅头|锅头|牛栏山|老白干|习酒|酱香|浓香|清香|白酒|西凤|古井|董酒|舍得|水井坊|江小白|红星"),
    ("beer", r"啤酒|啤|精酿|原浆|青岛|雪花|百威|喜力|乌苏|嘉士伯|老虎|tiger|carlsberg|heineken|guinness|哈尔滨|燕京|科罗娜|corona|1664"),
    ("wine", r"葡萄酒|红酒|干红|干白|wine|张裕|长城|奔富|拉菲"),
]
_LIQ = [(k, re.compile(p, re.I)) for k, p in _LIQ]
PAGE = 8
MAX_LINES = 20
QTY_MAX = 99
NOTE_MAX = 100
MAX_PER_HOUR = 5
MAX_PER_DAY = 20
DUP_WINDOW = 600
RECENT = 10
CART_TTL_DAYS = 14
RETENTION_DAYS = 90
STATUS_TEXT = {"pending": "待客服确认", "confirmed": "已确认", "cancelled": "已取消"}
CITY = {"KL": "吉隆坡", "JB": "新山"}


def order_no(city, n):
    """KLTG001 … KLTG999, KLTG1000 …; JBTG001 …"""
    return "%sTG%03d" % (city, int(n))


class ShopError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def norm(s):
    return re.sub(r"\s+", "", (s or "").lower())


def classify(row):
    c = row.get("category") or ""
    if c == "香烟":
        return "cig"
    if c == "槟榔":
        return "betel"
    if c == "酒水":
        mapped = LIQUOR_CODE_MAP.get((row.get("code") or "").strip())
        if mapped:
            return mapped
        n = row.get("name") or ""
        for k, rx in _LIQ:
            if rx.search(n):
                return k
        return "drink"
    return None


def image_url(u):
    """Only the mall's own images: relative paths are joined to https://h1hcs.com; other hosts are ignored."""
    if not isinstance(u, str) or not u:
        return None
    if u.startswith("/") and not u.startswith("//"):
        return IMAGE_BASE + u
    if u.startswith(IMAGE_BASE + "/"):
        return u
    return None


def item_key(name, unit, spec):
    return hashlib.sha1(("%s|%s|%s" % (norm(name), unit or "", spec or "")).encode()).hexdigest()[:10]


def build_items(rows):
    """rows: catalog rows with 'wh'. Returns (items_by_key, keys_by_cat) for shop categories only."""
    items = {}
    for r in rows:
        cat = classify(r)
        if not cat:
            continue
        k = item_key(r.get("name"), r.get("saleUnit"), r.get("spec"))
        it = items.get(k)
        if it is None:
            it = items[k] = {"key": k, "name": (r.get("name") or "").strip(), "unit": r.get("saleUnit") or "件",
                             "spec": r.get("spec") or "", "cat": cat, "wh": {}, "image": None, "_n": norm(r.get("name"))}
        it["wh"].setdefault(r.get("wh"), {"price": r.get("price"), "orig": r.get("originalPrice")})
        if not it["image"]:
            it["image"] = image_url(r.get("image"))
    by_cat = {c: [] for c, _ in CATS}
    for k, it in items.items():          # mall order (catalog row order = storefront order) is kept
        by_cat[it["cat"]].append(k)
    return items, by_cat


def price_for(it, city):
    """Kimi 11-13 14:42「新山跟吉隆坡同步」: every city uses the 吉隆坡 price (JB row only if KL has none).
    Returns (price, is_kl_price_for_jb)."""
    p = it["wh"].get("KL") or it["wh"].get("JB") or {}
    return p.get("price"), city == "JB"


def search(items, q, limit=40):
    qn = norm(q)
    if not qn:
        return []
    toks = [norm(t) for t in re.split(r"\s+", q.strip()) if t]
    hits = []
    for k, it in items.items():
        n = it["_n"]
        if all(t in n for t in toks):
            hits.append((0, len(n), n, k))
            continue
        grams = {qn[i:i + 2] for i in range(len(qn) - 1)} if len(qn) >= 2 else {qn}
        sc = sum(1 for g in grams if g in n)
        if grams and sc >= max(1, (len(grams) + 1) // 2):
            hits.append((1 + len(grams) - sc, len(n), n, k))
    hits.sort()
    return [k for *_x, k in hits[:limit]]


def cart_lines(cart_items, items, city):
    """-> (lines[{key,it,qty,price,line,fallback}], subtotal, missing_price, gone_keys)."""
    out, sub, missing, gone = [], 0.0, False, []
    for k, q in cart_items.items():
        it = items.get(k)
        if not it:
            gone.append(k)
            continue
        p, fb = price_for(it, city)
        line = round(p * q, 2) if p is not None else None
        if line is None:
            missing = True
        else:
            sub += line
        out.append({"key": k, "it": it, "qty": q, "price": p, "line": line, "fallback": fb})
    return out, round(sub, 2), missing, gone


class ShopStore:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        d = os.path.dirname(path)
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
        c = self._conn()
        try:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS carts(user_id INTEGER PRIMARY KEY, items TEXT NOT NULL DEFAULT '{}',
                    city TEXT NOT NULL DEFAULT 'KL', cs INTEGER, note TEXT, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, no TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, username TEXT, name TEXT,
                    city TEXT NOT NULL, cs INTEGER NOT NULL, note TEXT, items TEXT NOT NULL, subtotal REAL,
                    price_missing INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, created_at REAL NOT NULL,
                    decided_at REAL, purged INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS idx_shop_orders_user ON orders(user_id, created_at);
                CREATE TABLE IF NOT EXISTS seq(city TEXT PRIMARY KEY, n INTEGER NOT NULL);
            """)
            c.execute("PRAGMA user_version=1")
            c.commit()
        finally:
            c.close()
        os.chmod(path, 0o600)

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=2)
        c.execute("PRAGMA busy_timeout=2000")
        c.row_factory = sqlite3.Row
        return c

    # ---- cart
    def cart(self, uid):
        c = self._conn()
        try:
            r = c.execute("SELECT * FROM carts WHERE user_id=?", (uid,)).fetchone()
        finally:
            c.close()
        if not r:
            return {"items": {}, "city": "KL", "cs": None, "note": None}
        try:
            items = {k: int(v) for k, v in json.loads(r["items"]).items() if isinstance(v, int) and v > 0}
        except Exception:
            items = {}
        return {"items": items, "city": r["city"] if r["city"] in CITY else "KL", "cs": r["cs"], "note": r["note"]}

    def _save(self, uid, cart):
        with self._lock:
            c = self._conn()
            try:
                c.execute("INSERT INTO carts(user_id, items, city, cs, note, updated_at) VALUES(?,?,?,?,?,?) "
                          "ON CONFLICT(user_id) DO UPDATE SET items=excluded.items, city=excluded.city, cs=excluded.cs, "
                          "note=excluded.note, updated_at=excluded.updated_at",
                          (uid, json.dumps(cart["items"]), cart["city"], cart["cs"], cart["note"], time.time()))
                c.commit()
            finally:
                c.close()
        return cart

    def add(self, uid, key, delta):
        cart = self.cart(uid)
        q = cart["items"].get(key, 0) + int(delta)
        if q <= 0:
            cart["items"].pop(key, None)
        else:
            if key not in cart["items"] and len(cart["items"]) >= MAX_LINES:
                raise ShopError("full")
            cart["items"][key] = min(q, QTY_MAX)
        return self._save(uid, cart)

    def remove(self, uid, key):
        cart = self.cart(uid)
        cart["items"].pop(key, None)
        return self._save(uid, cart)

    def clear(self, uid):
        cart = self.cart(uid)
        cart.update(items={}, cs=None, note=None)
        return self._save(uid, cart)

    def set(self, uid, **kw):
        cart = self.cart(uid)
        for k in ("city", "cs", "note"):
            if k in kw:
                cart[k] = kw[k]
        if cart["city"] not in CITY:
            raise ShopError("invalid")
        return self._save(uid, cart)

    # ---- orders
    def create_order(self, uid, chat_id, username, name, city, cs, note, lines, subtotal, missing, now=None):
        now = now or time.time()
        if not (isinstance(uid, int) and uid > 0 and chat_id == uid):
            raise ShopError("not_private")
        if not lines or city not in CITY or not isinstance(cs, int):
            raise ShopError("invalid")
        snap = [{"name": l["it"]["name"], "spec": l["it"]["spec"], "unit": l["it"]["unit"], "qty": l["qty"],
                 "price": l["price"], "line": l["line"], "key": l["key"]} for l in lines]
        sig = json.dumps(sorted((s["key"], s["qty"]) for s in snap))
        with self._lock:
            c = self._conn()
            try:
                c.execute("BEGIN IMMEDIATE")
                nh = c.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND created_at>?", (uid, now - 3600)).fetchone()[0]
                nd = c.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND created_at>?", (uid, now - 86400)).fetchone()[0]
                if nh >= MAX_PER_HOUR or nd >= MAX_PER_DAY:
                    raise ShopError("rate")
                for r in c.execute("SELECT items FROM orders WHERE user_id=? AND city=? AND status='pending' AND created_at>?",
                                   (uid, city, now - DUP_WINDOW)):
                    if json.dumps(sorted((s["key"], s["qty"]) for s in json.loads(r["items"]))) == sig:
                        raise ShopError("dup")
                # per-city persistent counter inside the same IMMEDIATE transaction: no reuse after restart, race-free
                c.execute("INSERT OR IGNORE INTO seq(city, n) VALUES(?, 0)", (city,))
                while True:
                    c.execute("UPDATE seq SET n=n+1 WHERE city=?", (city,))
                    n = c.execute("SELECT n FROM seq WHERE city=?", (city,)).fetchone()[0]
                    no = order_no(city, n)
                    if not c.execute("SELECT 1 FROM orders WHERE no=?", (no,)).fetchone():
                        break
                cur = c.execute("INSERT INTO orders(no,user_id,chat_id,username,name,city,cs,note,items,subtotal,price_missing,"
                                "status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'pending',?)",
                                (no, uid, chat_id, username, name, city, cs, note, json.dumps(snap, ensure_ascii=False),
                                 subtotal, 1 if missing else 0, now))
                c.commit()
                return {"id": cur.lastrowid, "no": no}
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()

    def order(self, oid):
        c = self._conn()
        try:
            r = c.execute("SELECT * FROM orders WHERE id=?", (int(oid),)).fetchone()
        finally:
            c.close()
        if not r:
            return None
        o = dict(r)
        o["items"] = json.loads(o["items"])
        return o

    def recent(self, uid, n=RECENT):
        c = self._conn()
        try:
            ids = [r[0] for r in c.execute("SELECT id FROM orders WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
                                           (uid, n))]
        finally:
            c.close()
        return [self.order(i) for i in ids]

    def add_note(self, oid, uid, note, now=None):
        """shop-cart-v1-fix1: add a note to the user's OWN still-pending order (after 「跳过」 or a stale button).
        Returns the updated order, or None if not theirs / not pending / already has a note."""
        note = (note or "").strip()
        if not note or "\n" in note or "\r" in note or len(note) > NOTE_MAX:
            raise ShopError("invalid")
        with self._lock:
            c = self._conn()
            try:
                cur = c.execute("UPDATE orders SET note=? WHERE id=? AND user_id=? AND status='pending' AND (note IS NULL OR note='')",
                                (note, int(oid), int(uid)))
                c.commit()
                ok = cur.rowcount == 1
            finally:
                c.close()
        return self.order(oid) if ok else None

    def replace_cart(self, uid, items, city, cs, note):
        """shop-miniapp-v2: the Mini App's validated cart replaces the stored cart in one write."""
        if city not in CITY or not isinstance(items, dict) or len(items) > MAX_LINES:
            raise ShopError("invalid")
        for k, q in items.items():
            if not isinstance(k, str) or type(q) is not int or not (1 <= q <= QTY_MAX):
                raise ShopError("invalid")
        return self._save(uid, {"items": dict(items), "city": city, "cs": cs, "note": note})

    def decide(self, oid, status, now=None):
        if status not in ("confirmed", "cancelled"):
            raise ShopError("invalid")
        with self._lock:
            c = self._conn()
            try:
                cur = c.execute("UPDATE orders SET status=?, decided_at=? WHERE id=? AND status='pending'",
                                (status, now or time.time(), int(oid)))
                c.commit()
                if cur.rowcount != 1:
                    return None
            finally:
                c.close()
        return self.order(oid)

    def purge(self, now=None):
        now = now or time.time()
        with self._lock:
            c = self._conn()
            try:
                c.execute("DELETE FROM carts WHERE updated_at<?", (now - CART_TTL_DAYS * 86400,))
                cur = c.execute("UPDATE orders SET username=NULL, name=NULL, note=NULL, purged=1 WHERE created_at<? AND purged=0",
                                (now - RETENTION_DAYS * 86400,))
                c.commit()
                return cur.rowcount
            finally:
                c.close()


# ---------------- product images: mall webp -> cached JPEG (Kimi 14:42「转」) ----------------
IMG_MAX_BYTES = 3 * 1024 * 1024
IMG_MAX_PIXELS = 25_000_000
IMG_MAX_SIDE = 1280
IMG_MAX_FILES = 400
IMG_FAIL_TTL = 3600
IMG_TIMEOUT = (4, 8)


def pillow_ok():
    """True only if Pillow is importable AND has WebP decode support."""
    try:
        from PIL import Image, features  # noqa: F401
        return bool(features.check("webp"))
    except Exception:
        return False


class ImageCache:
    """Never raises from get_or_convert(); returns a JPEG path or None (caller falls back to text)."""
    def __init__(self, d, fetch=None):
        self.dir = d
        self._fetch = fetch or self._http_fetch
        self._fail = {}
        self._lock = threading.Lock()

    def _ensure_dir(self):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        os.chmod(self.dir, 0o700)

    def path_for(self, url):
        return os.path.join(self.dir, hashlib.sha1(url.encode()).hexdigest()[:24] + ".jpg")

    def cached(self, url):
        if image_url(url) != url:
            return None
        p = self.path_for(url)
        if os.path.exists(p):
            try:
                os.utime(p, None)
            except OSError:
                pass
            return p
        return None

    @staticmethod
    def _http_fetch(url):
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (h1hcsbot image cache)"})
        with s.get(url, timeout=IMG_TIMEOUT, stream=True, allow_redirects=False) as r:
            if r.status_code != 200:
                raise RuntimeError("HTTP %s" % r.status_code)
            ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            if not ct.startswith("image/"):
                raise RuntimeError("not an image")
            cl = r.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > IMG_MAX_BYTES:
                raise RuntimeError("too large")
            buf = bytearray()
            for chunk in r.iter_content(65536):
                buf += chunk
                if len(buf) > IMG_MAX_BYTES:
                    raise RuntimeError("too large")
            return bytes(buf)

    def get_or_convert(self, url):
        if image_url(url) != url:              # only https://h1hcs.com/... (already normalised)
            return None
        p = self.cached(url)
        if p:
            return p
        with self._lock:
            t = self._fail.get(url)
            if t and time.time() - t < IMG_FAIL_TTL:
                return None
        try:
            if not pillow_ok():
                raise RuntimeError("pillow/webp unavailable")
            import io
            from PIL import Image
            data = self._fetch(url)
            if not data or len(data) > IMG_MAX_BYTES:
                raise RuntimeError("bad size")
            im = Image.open(io.BytesIO(data))
            if im.width * im.height > IMG_MAX_PIXELS:
                raise RuntimeError("too many pixels")
            im.load()
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            im.thumbnail((IMG_MAX_SIDE, IMG_MAX_SIDE))
            self._ensure_dir()
            import tempfile
            fd, tmp = tempfile.mkstemp(prefix=".img.", suffix=".tmp", dir=self.dir)
            with os.fdopen(fd, "wb") as f:
                im.save(f, "JPEG", quality=85, optimize=True)
            os.chmod(tmp, 0o600)
            dst = self.path_for(url)
            os.replace(tmp, dst)
            self._prune()
            return dst
        except Exception as e:
            with self._lock:
                self._fail[url] = time.time()
            self.last_error = "%s: %s" % (type(e).__name__, str(e)[:120])
            return None

    def _prune(self):
        try:
            fs = [os.path.join(self.dir, f) for f in os.listdir(self.dir) if f.endswith(".jpg")]
            if len(fs) > IMG_MAX_FILES:
                fs.sort(key=lambda f: os.path.getmtime(f))
                for f in fs[:len(fs) - IMG_MAX_FILES]:
                    os.unlink(f)
        except OSError:
            pass
