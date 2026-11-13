"""features-1235-v1: in-process read-only catalog sync (logic of catalog_sync.py, made injectable/testable).

Replays the PUBLIC h1hcs.com storefront pagination (GET only, no login, ~0.7s between pages) and keeps only
public product fields. Atomic write (tempfile + os.replace); a failing warehouse keeps its previous rows; a
suspicious shrink (<50% of last) is refused for that warehouse. Never raises out of sync_once()."""
import json, logging, os, tempfile, time
from datetime import datetime, timezone, timedelta

BASE = "https://h1hcs.com/api/erp"
AGENT = ""   # pages-repo: set at run time from the STOREFRONT_AGENT secret (never committed)
WAREHOUSES = ["KL", "JB"]
DELAY = 0.7
MAX_PAGES = 400
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
MYT = timezone(timedelta(hours=8))
log = logging.getLogger("catalog_live")


def _cents(v):
    return None if v is None else round(int(v) / 100.0, 2)


def _row(p):
    return {
        "name": (p.get("name") or "").strip(),
        "code": p.get("code") or "",
        "category": p.get("category") or "",
        "subcategory": p.get("subcategory") or "",
        "saleUnit": p.get("saleUnit") or "",
        "spec": p.get("specification") or "",
        "price": _cents(p.get("guidePriceCents")),
        "originalPrice": _cents(p.get("originalPriceCents")),
        "available": bool(p.get("available")),
        "image": p.get("imageUrl") or "",   # shop-cart-v1: public product image path (mall's own); never shown as stock
    }


def fetch_warehouse(get_json, wh, sleep=time.sleep, stop=None):
    """get_json(params) -> dict. Raises RuntimeError on failure."""
    items, seen, total, page = [], set(), None, 0
    for page in range(1, MAX_PAGES + 1):
        if stop is not None and stop.is_set():
            raise RuntimeError("stopped")
        params = {"resource": "storefront", "agent": AGENT, "warehouse": wh, "page": str(page),
                  "q": "", "category": "", "subcategory": "", "feed": "", "layout": "1"}
        d = None
        for attempt in range(3):
            try:
                d = get_json(params)
                break
            except Exception as e:
                if attempt == 2:
                    raise RuntimeError("%s page %d failed: %s" % (wh, page, type(e).__name__))
                sleep(3 * (attempt + 1))
        if not isinstance(d, dict) or d.get("warehouse") != wh:
            raise RuntimeError("%s page %d: warehouse mismatch" % (wh, page))
        total = d.get("total", total)
        prods = d.get("products") or []
        new = 0
        for p in prods:
            cands = [p] + [v for v in (p.get("variants") or []) if isinstance(v, dict) and v.get("name")]
            for c in cands:
                key = c.get("id") or c.get("code")
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(_row(c))
                new += 1
        if not d.get("hasMore") or not prods or new == 0:
            break
        sleep(DELAY)
    return items, total, page


def requests_get_json(timeout=(10, 40)):
    import requests
    s = requests.Session()
    s.trust_env = True
    s.headers.update({"User-Agent": UA, "Accept": "application/json"})

    def _get(params):
        r = s.get(BASE, params=params, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError("HTTP %s" % r.status_code)
        return r.json()
    return _get


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def sync_once(path, get_json=None, sleep=time.sleep, now=None, stop=None):
    """Returns {"ok": bool, "counts": {wh: n}, "kept": [wh...], "error": str|None}. Never raises."""
    try:
        get_json = get_json or requests_get_json()
        prev = load(path)
        out = {"updated_at": None, "source": "h1hcs.com storefront (public)", "warehouses": {}}
        kept, fresh = [], 0
        for wh in WAREHOUSES:
            prev_items = ((prev or {}).get("warehouses") or {}).get(wh) or []
            try:
                items, total, pages = fetch_warehouse(get_json, wh, sleep=sleep, stop=stop)
                if not items:
                    raise RuntimeError("%s returned 0 items" % wh)
                if prev_items and len(items) < 0.5 * len(prev_items):
                    raise RuntimeError("%s suspiciously few items: %d vs last %d" % (wh, len(items), len(prev_items)))
                fresh += 1
                log.info("catalog sync %s items=%d pages=%d", wh, len(items), pages)
            except Exception as e:
                if not prev_items:
                    raise
                log.warning("catalog sync %s failed (%s); keeping previous %d rows", wh, str(e)[:80], len(prev_items))
                items = prev_items
                kept.append(wh)
            out["warehouses"][wh] = items
        if not fresh:
            return {"ok": False, "counts": {}, "kept": kept, "error": "all warehouses failed; file untouched"}
        stamp = (now or datetime.now(MYT)).isoformat(timespec="seconds")
        prev_wh = (prev or {}).get("wh_updated") or {}
        # per-warehouse freshness: a kept (failed) warehouse keeps its OLD time so the staleness hint stays honest
        out["wh_updated"] = {wh: (prev_wh.get(wh) or (prev or {}).get("updated_at") or stamp) if wh in kept else stamp
                             for wh in WAREHOUSES}
        out["updated_at"] = min(out["wh_updated"].values()) if kept else stamp
        if kept:
            out["partial"] = {"kept": kept, "at": stamp}
        d = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(prefix=".catalog.", suffix=".tmp", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return {"ok": True, "counts": {k: len(v) for k, v in out["warehouses"].items()}, "kept": kept, "error": None}
    except Exception as e:
        log.warning("catalog sync failed, previous catalog kept: %s", type(e).__name__)
        return {"ok": False, "counts": {}, "kept": [], "error": type(e).__name__}
