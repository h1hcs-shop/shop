/* shop-miniapp-v1 烟酒商城 Mini App. Static page; loads catalog.json (exported by the bot, NO stock), keeps the cart in
   localStorage, submits {v,items:[[key,qty,shownPrice]],cs,city,note} via Telegram.WebApp.sendData (keyboard-button launch).
   The bot re-prices everything server-side and shows a confirm page before an order is created. */
(function () {
  "use strict";
  var tg = (window.Telegram && window.Telegram.WebApp) || null;
  var CAT_ICON = {cig: "🚬", baijiu: "🥃", beer: "🍺", spirits: "🥂", wine: "🍷", drink: "🍶", betel: "🌰"};
  var LS = "h1h_shop_cart_v1", MAX_BYTES = 4096, IMG_HOSTS = ["h1hcs.com"];
  var S = {cat: "all", q: "", tab: "shop", cart: {}, city: "KL", cs: null, note: "", data: null, byKey: {}};

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function money(v) { if (v == null) return "价格待确认"; var s = (Math.round(v * 100) / 100).toFixed(2).replace(/\.00$/, ""); return s.replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
  function norm(s) { return (s || "").toLowerCase().replace(/[\s（）()【】\[\]·•\-_/]/g, ""); }
  function toast(t) { var x = $("toast"); x.textContent = t; x.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(function () { x.hidden = true; }, 1800); }
  function haptic(k) { try { tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred(k || "light"); } catch (e) {} }
  function safeImg(u) {
    try { var x = new URL(u); return x.protocol === "https:" && IMG_HOSTS.indexOf(x.hostname) >= 0 ? x.href : ""; }
    catch (e) { return /^(img|demo)\/[\w.\-]+$/.test(u || "") ? u : ""; }      // relative = locally hosted copies
  }

  function save() { try { localStorage.setItem(LS, JSON.stringify({c: S.cart, city: S.city, cs: S.cs, note: S.note})); } catch (e) {} }
  function load() {
    try {
      var o = JSON.parse(localStorage.getItem(LS) || "{}");
      if (o.c && typeof o.c === "object") Object.keys(o.c).forEach(function (k) {
        var q = o.c[k]; if (S.byKey[k] && Number.isInteger(q) && q > 0) S.cart[k] = Math.min(q, S.data.limits.qty);
      });
      if (o.city === "KL" || o.city === "JB") S.city = o.city;
      if (Number.isInteger(o.cs) && o.cs >= 0 && o.cs < S.data.cs.length) S.cs = o.cs;
      if (typeof o.note === "string") S.note = o.note.slice(0, S.data.limits.note);
    } catch (e) {}
  }

  function setQty(k, q) {
    var L = S.data.limits;
    if (q > L.qty) { toast("每款最多 " + L.qty); q = L.qty; }
    if (q <= 0) delete S.cart[k];
    else {
      if (!S.cart[k] && Object.keys(S.cart).length >= L.lines) { toast("一单最多 " + L.lines + " 款商品"); return; }
      S.cart[k] = q;
    }
    haptic(); save(); renderBar();
    if (S.tab === "shop") renderList(); else renderCart();
  }

  function stepper(k) {
    var q = S.cart[k] || 0;
    if (!q) { var b = el("button", "add", "+ 加入"); b.onclick = function () { setQty(k, 1); }; return b; }
    var w = el("div", "step"), m = el("button", null, "−"), n = el("span", null, String(q)), p = el("button", null, "+");
    m.onclick = function () { setQty(k, q - 1); }; p.onclick = function () { setQty(k, q + 1); };
    w.append(m, n, p); return w;
  }

  function priceNode(it) {
    var d = el("div", "money");
    if (it.p == null) { d.textContent = "价格待确认"; return d; }
    d.append(el("small", null, "RM"), el("b", null, money(it.p)), el("i", null, "/ " + it.u));
    if (it.o) d.append(el("s", null, "RM " + money(it.o)));
    return d;
  }

  function row(it) {
    var r = el("div", "row"), im = el("div", "img"), src = safeImg(it.img);
    var ph = el("span", null, CAT_ICON[it.c] || "🛒"); im.append(ph);
    if (src) {   // attached at once: a detached loading=lazy image never loads
      var i = document.createElement("img"); i.loading = "lazy"; i.decoding = "async"; i.referrerPolicy = "no-referrer"; i.alt = "";
      i.onload = function () { ph.remove(); im.classList.add("ok"); };   // hidden by opacity, not display:none (which blocks lazy load)
      i.onerror = function () { i.remove(); };
      i.src = src; im.append(i);
    }
    var info = el("div", "info");
    info.append(el("div", "nm", it.n), el("div", "sp", (it.s ? "规格：" + it.s + " · " : "") + "单位：" + it.u));
    var pr = el("div", "pr"); pr.append(priceNode(it), stepper(it.k)); info.append(pr);
    r.append(im, info); return r;
  }

  function visible() {
    var q = norm(S.q), items = S.data.items;
    if (q) return items.filter(function (it) { return norm(it.n + it.s).indexOf(q) >= 0; });
    return S.cat === "all" ? items : items.filter(function (it) { return it.c === S.cat; });
  }

  function renderChips() {
    var c = $("chips"); c.textContent = "";
    [{id: "all", name: "全部"}].concat(S.data.cats).forEach(function (x) {
      var b = el("button", S.cat === x.id && !S.q ? "on" : "", x.name.replace(/^\S+\s/, ""));
      b.onclick = function () { S.cat = x.id; S.q = ""; $("q").value = ""; renderChips(); renderList(); window.scrollTo(0, 0); };
      c.append(b);
    });
  }

  function renderList() {
    var v = visible(), l = $("list"); l.textContent = "";
    var cat = S.data.cats.filter(function (x) { return x.id === S.cat; })[0];
    $("sec-t").textContent = S.q ? "搜索「" + S.q + "」" : (cat ? cat.name.replace(/^\S+\s/, "") : "全部");
    $("sec-n").textContent = v.length + " 款商品";
    if (!v.length) l.append(el("div", "empty", S.q ? "没找到相关的烟酒槟榔商品，换个关键词试试" : "这个品类暂时没有商品"));
    var frag = document.createDocumentFragment(); v.slice(0, 300).forEach(function (it) { frag.append(row(it)); }); l.append(frag);
  }

  function totals() {
    var n = 0, kinds = 0, sub = 0, missing = false;
    Object.keys(S.cart).forEach(function (k) { var it = S.byKey[k]; if (!it) return; kinds++; n += S.cart[k]; if (it.p == null) missing = true; else sub += it.p * S.cart[k]; });
    return {n: n, kinds: kinds, sub: sub, missing: missing};
  }

  function renderBar() {
    var t = totals();
    $("tot").textContent = "RM " + money(t.sub) + (t.missing ? "+" : "");
    $("cnt").textContent = "已选 " + t.kinds + " 款，共 " + t.n + " 件";
    $("go").textContent = S.tab === "cart" ? "继续选购" : "购物车（" + t.kinds + "）";
    $("tabn").textContent = t.kinds ? "（" + t.kinds + "）" : "";
  }

  function seg(box, opts, cur, onpick) {
    box.textContent = "";
    opts.forEach(function (o) { var b = el("button", o.v === cur ? "on" : "", o.t); b.onclick = function () { onpick(o.v); }; box.append(b); });
  }

  function renderCart() {
    var keys = Object.keys(S.cart).filter(function (k) { return S.byKey[k]; }), L = $("lines"); L.textContent = "";
    $("empty").hidden = !!keys.length; $("checkout").hidden = !keys.length;
    keys.forEach(function (k) {
      var it = S.byKey[k], r = row(it), rm = el("button", "rm", "移除");
      rm.onclick = function () { setQty(k, 0); };
      var line = el("div", "sp", it.p == null ? "价格待确认" : "小计 RM " + money(it.p * S.cart[k]));
      line.append(document.createTextNode("　")); line.append(rm);
      r.querySelector(".info").append(line); L.append(r);
    });
    var t = totals(); $("sub").textContent = "RM " + money(t.sub) + (t.missing ? "（部分待确认）" : "");
    seg($("city"), S.data.cities.map(function (c) { return {v: c.id, t: c.name}; }), S.city, function (v) { S.city = v; save(); renderCart(); });
    seg($("cs"), S.data.cs.map(function (c, i) { return {v: i, t: c.icon + " 客服" + c.name}; }), S.cs, function (v) { S.cs = v; save(); renderCart(); });
    $("note").value = S.note; $("notec").textContent = S.note.length;
  }

  function showTab(t) {
    S.tab = t; $("v-shop").hidden = t !== "shop"; $("v-cart").hidden = t !== "cart";
    document.querySelectorAll(".tabs button").forEach(function (b) { b.classList.toggle("on", b.dataset.tab === t); });
    if (t === "cart") renderCart(); else renderList();
    renderBar(); window.scrollTo(0, 0);
    try { if (tg) { t === "cart" ? tg.BackButton.show() : tg.BackButton.hide(); } } catch (e) {}
  }

  function err(t) { var e = $("err"); e.textContent = t; e.hidden = !t; if (t) e.scrollIntoView({block: "center"}); }

  function payload() {
    var items = Object.keys(S.cart).filter(function (k) { return S.byKey[k]; }).map(function (k) { return [k, S.cart[k], S.byKey[k].p]; });
    return JSON.stringify({v: 1, items: items, cs: S.cs, city: S.city, note: S.note.trim()});
  }

  function submit() {
    err("");
    if (!Object.keys(S.cart).length) return err("购物车是空的");
    if (S.cs == null) return err("请选择为你服务的客服");
    if (/[\r\n]/.test(S.note) || S.note.length > S.data.limits.note) return err("备注需单行、最多 " + S.data.limits.note + " 字");
    var p = payload();
    if (new TextEncoder().encode(p).length > MAX_BYTES) return err("商品太多，请分开下单");
    if (!tg || typeof tg.sendData !== "function") return err("请在 Telegram 里从机器人底部键盘「🛒 烟酒商城（小程序）」打开");
    try { haptic("medium"); tg.sendData(p); }       // closes the Mini App; the bot replies with a server-priced confirm page
    catch (e) { err("请从机器人底部键盘「🛒 烟酒商城（小程序）」打开后再提交（菜单/链接打开的页面无法提交）"); }
  }

  function boot(data) {
    S.data = data; data.items.forEach(function (it) { S.byKey[it.k] = it; });
    load(); renderChips(); renderList(); renderBar();
    var u = (data.updated_at || "").replace("T", " ").slice(5, 16);
    $("upd").textContent = (u ? "🕒 价格更新：" + u + "（UTC+8）· " : "") + "价格以客服确认为准，不显示库存";
    $("q").oninput = function (e) { S.q = e.target.value.trim().slice(0, 20); renderChips(); renderList(); };
    $("note").oninput = function (e) { S.note = e.target.value.replace(/[\r\n]/g, " ").slice(0, S.data.limits.note); $("notec").textContent = S.note.length; save(); };
    $("go").onclick = function () { showTab(S.tab === "cart" ? "shop" : "cart"); };
    document.querySelectorAll(".tabs button").forEach(function (b) { b.onclick = function () { showTab(b.dataset.tab); }; });
    $("submit").onclick = submit;
    $("clear").onclick = function () { S.cart = {}; save(); renderCart(); renderBar(); };
    if (tg) { try { tg.BackButton.onClick(function () { showTab("shop"); }); } catch (e) {} }
    S.render = function () { save(); renderBar(); if (S.tab === "cart") renderCart(); else renderList(); };
    window.__shop = S;   // for the offline demo / screenshots
  }

  if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }
  var src = (document.querySelector("meta[name=catalog]") || {}).content || "catalog.json";
  fetch(src + (src.indexOf("?") < 0 ? "?t=" : "&t=") + Math.floor(Date.now() / 300000), {cache: "no-cache"})
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (d) { if (!d || d.v !== 1 || !Array.isArray(d.items)) throw new Error("bad"); boot(d); })
    .catch(function () { err("商品目录加载失败，请稍后重试，或回到机器人用「🛒 烟酒商城下单（购物车）」按钮下单。"); });
})();
