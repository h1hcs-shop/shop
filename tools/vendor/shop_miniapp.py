"""shop-miniapp-v1: Telegram Mini App front end for the 烟酒商城 (shop_cart).

The Mini App is a static page opened from a reply-keyboard KeyboardButton(web_app). It posts the cart back with
Telegram.WebApp.sendData() -> the bot receives message.web_app_data in the user's private chat.

Trust model: keyboard-button launches carry NO initData, so the payload is untrusted input from message.from.
Only product keys + quantities + 客服 index + city + note are accepted; every price is recomputed here from the
same catalog the inline shop uses (catalog.json via shop_cart.build_items). Client prices are ignored.
No stock is ever exported or shown. Pure module: no network, no Telegram calls, no file writes.
"""
import json
import shop_cart

VERSION = 1
PAYLOAD_MAX = 4096          # Telegram's sendData limit; anything larger is rejected before json parsing
KEY_LEN = 10                # shop_cart.item_key -> sha1(...)[:10]


class MiniAppError(Exception):
    def __init__(self, code, msg):
        super().__init__(code)
        self.code, self.msg = code, msg


def _err(code, msg):
    raise MiniAppError(code, msg)


def parse(data, items, n_cs):
    """Validate a sendData payload against the live shop items.

    Returns dict(items={key: qty}, city, cs, note, warnings=[...]). Raises MiniAppError on anything that is not a
    well-formed order (the bot then shows a friendly message and does NOT touch the stored cart)."""
    if not isinstance(data, str) or not data:
        _err("empty", "没有收到购物车数据，请在商城里重新提交。")
    if len(data.encode("utf-8")) > PAYLOAD_MAX:
        _err("too_big", "购物车数据过大，请减少商品后再提交。")
    try:
        p = json.loads(data)
    except Exception:
        _err("bad_json", "购物车数据无法识别，请在商城里重新提交。")
    if not isinstance(p, dict) or p.get("v") != VERSION:
        _err("bad_version", "商城页面版本过旧，请关闭后重新打开商城。")
    raw = p.get("items")
    if not isinstance(raw, list) or not raw:
        _err("no_items", "购物车是空的，请先在商城里选商品。")
    if len(raw) > shop_cart.MAX_LINES:
        _err("too_many_lines", "一单最多 %d 款商品，请分开下单。" % shop_cart.MAX_LINES)
    cart, warnings, unknown = {}, [], 0
    for e in raw:
        if not isinstance(e, list) or len(e) < 2 or not isinstance(e[0], str) or type(e[1]) is not int:
            _err("bad_item", "购物车数据无法识别，请在商城里重新提交。")
        k, q = e[0], e[1]
        if q < 1 or q > shop_cart.QTY_MAX:
            _err("bad_qty", "每款商品数量需在 1~%d 之间。" % shop_cart.QTY_MAX)
        if len(k) != KEY_LEN or k not in items:
            unknown += 1
            continue
        if k in cart:
            _err("dup_item", "购物车数据重复，请在商城里重新提交。")
        cart[k] = q
        # e[2] (client unit price) is accepted for display only and compared below; never used for the order
        if len(e) >= 3:
            cp = e[2]
            sp, _ = shop_cart.price_for(items[k], "KL")
            if not isinstance(cp, (int, float)) or sp is None or abs(float(cp) - float(sp)) > 0.004:
                if "price_changed" not in warnings:
                    warnings.append("price_changed")
    if unknown:
        warnings.append("unknown:%d" % unknown)
    if not cart:
        _err("all_unknown", "所选商品已下架或已更新，请重新打开商城选购。")
    city = p.get("city")
    if city not in shop_cart.CITY:
        _err("bad_city", "请选择配送城市（吉隆坡 / 新山）。")
    cs = p.get("cs")
    if type(cs) is not int or not (0 <= cs < n_cs):
        _err("bad_cs", "请选择客服。")
    note = p.get("note")
    if note is None:
        note = ""
    if not isinstance(note, str):
        _err("bad_note", "备注格式不对。")
    note = note.strip()
    if "\n" in note or "\r" in note or len(note) > shop_cart.NOTE_MAX:
        _err("bad_note", "备注需单行、最多 %d 字。" % shop_cart.NOTE_MAX)
    return {"items": cart, "city": city, "cs": cs, "note": note or None, "warnings": warnings}


def export_catalog(items, by_cat, updated_at, cs_list):
    """JSON the Mini App loads (static hosting). Prices are KL prices (新山 = 吉隆坡价). NO stock / availability."""
    out_items = []
    for cat, _name in shop_cart.CATS:
        for k in by_cat.get(cat, []):
            it = items[k]
            p = it["wh"].get("KL") or it["wh"].get("JB") or {}
            out_items.append({"k": k, "n": it["name"], "u": it["unit"], "s": it["spec"] or "", "c": cat,
                              "p": p.get("price"), "o": p.get("orig") if (p.get("orig") or 0) > (p.get("price") or 0) else None,
                              "img": it.get("image") or ""})
    return {"v": VERSION, "updated_at": updated_at or "",
            "cats": [{"id": c, "name": n} for c, n in shop_cart.CATS if by_cat.get(c)],
            "cs": [{"name": c["name"], "icon": c["icon"]} for c in cs_list],     # display only; no usernames/links
            "cities": [{"id": k, "name": v} for k, v in shop_cart.CITY.items()],
            "limits": {"lines": shop_cart.MAX_LINES, "qty": shop_cart.QTY_MAX, "note": shop_cart.NOTE_MAX},
            "items": out_items}
