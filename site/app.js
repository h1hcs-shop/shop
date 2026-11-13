/* shop-miniapp-v3 「下单入口」 Mini App (烟酒槟榔 + the mall's 零食/饮料/速食/粮油/冷冻/洗护/日用, Kimi 21:02 / 21:05). Static page; loads catalog.json (built hourly by GitHub Actions, NO stock), keeps the
   cart in localStorage, submits {v:2,items:[[key,qty,shownPrice]],cs,city,note,addr,ph,pc,j} via Telegram.WebApp.sendData
   (keyboard-button launch only). The bot re-prices everything server-side. Page switches come from catalog.json "opts":
   location / geocode / phone / jump (all off when missing). No personal data ever leaves the device except:
   sendData -> the bot; the optional prefilled message the user sends to 客服; and (only with opts.geocode) the coordinates
   to the reverse-geocoding endpoint named in opts.geocode_url. */
(function () {
  "use strict";
  var tg = (window.Telegram && window.Telegram.WebApp) || null;
  var CAT_ICON = {cig: "🚬", baijiu: "🥃", beer: "🍺", spirits: "🥂", wine: "🍷", drink: "🍶", betel: "🌰",
                  vape: "💨", snack: "🍪", drinkm: "🥤", instant: "🍜", grain: "🍚", frozen: "🧊", care: "🧴", home: "🏠", adult: "💊"};
  var ENTRY = "🛍 下单入口", PAGE_N = 60;   // tiles rendered per batch; more are appended while scrolling (images lazy)
  // keyboard-button launches carry NO initData; menu-button / inline-button launches do (and cannot use sendData)
  var KB_LAUNCH = !!(tg && typeof tg.initData === "string" && tg.initData === "");
  var LS = "h1h_shop_cart_v1", MAX_BYTES = 4096, IMG_HOSTS = ["h1hcs.com"], ADDR_MAX = 120, PREFILL_MAX = 900;
  var PHONE_RX = /^\+?[0-9][0-9 ()\-]{5,22}$/;
  // 货到付款 methods (Kimi 20:49). Codes must match shop_cart.PAY_METHODS; the bot rejects anything else.
  var PAY = [["cash", "现金"], ["tng", "TNG"], ["usdt", "USDT"], ["wechat", "微信"], ["alipay", "支付宝"]];
  function payLabel(c) { var x = PAY.filter(function (p) { return p[0] === c; })[0]; return x ? x[1] : ""; }
  var S = {cat: "all", q: "", tab: "shop", cart: {}, city: "KL", cs: null, note: "", addr: "", ph: "", pc: false, loc: null, pay: null,
           locMsg: "", data: null, byKey: {}, opts: {}};

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function money(v) { if (v == null) return "价格待确认"; var s = (Math.round(v * 100) / 100).toFixed(2).replace(/\.00$/, ""); return s.replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
  function norm(s) { return (s || "").toLowerCase().replace(/[\s（）()【】\[\]·•\-_/]/g, ""); }
  function toast(t) { var x = $("toast"); x.textContent = t; x.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(function () { x.hidden = true; }, 1800); }
  function haptic(k) { try { tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred(k || "light"); } catch (e) {} }
  function ver(v) { try { return !!(tg && tg.isVersionAtLeast && tg.isVersionAtLeast(v)); } catch (e) { return false; } }
  function one(s) { return (s || "").replace(/[\r\n]+/g, " ").replace(/\s+/g, " "); }
  function mapLink(l) { return "https://maps.google.com/?q=" + l.lat.toFixed(6) + "," + l.lng.toFixed(6); }
  function safeImg(u) {
    try { var x = new URL(u); return x.protocol === "https:" && IMG_HOSTS.indexOf(x.hostname) >= 0 ? x.href : ""; }
    catch (e) { return /^(img|demo)\/[\w.\-]+$/.test(u || "") ? u : ""; }      // relative = locally hosted copies
  }
  function csUser(i) { var c = S.data.cs[i] || {}; return /^[A-Za-z0-9_]{5,32}$/.test(c.user || "") ? c.user : ""; }

  function save() { try { localStorage.setItem(LS, JSON.stringify({c: S.cart, city: S.city, cs: S.cs, note: S.note, addr: S.addr, ph: S.ph, pay: S.pay})); } catch (e) {} }
  function load() {
    try {
      var o = JSON.parse(localStorage.getItem(LS) || "{}");
      if (o.c && typeof o.c === "object") Object.keys(o.c).forEach(function (k) {
        var q = o.c[k]; if (S.byKey[k] && Number.isInteger(q) && q > 0) S.cart[k] = Math.min(q, S.data.limits.qty);
      });
      if (o.city === "KL" || o.city === "JB") S.city = o.city;
      if (Number.isInteger(o.cs) && o.cs >= 0 && o.cs < S.data.cs.length) S.cs = o.cs;
      if (typeof o.note === "string") S.note = o.note.slice(0, S.data.limits.note);
      if (typeof o.addr === "string") S.addr = one(o.addr).slice(0, ADDR_MAX);
      if (typeof o.ph === "string") S.ph = o.ph.slice(0, 23);
      if (payLabel(o.pay)) S.pay = o.pay;
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
    if (S.sheetKey === k) renderSheet();
  }

  function stepper(k, big) {
    var q = S.cart[k] || 0;
    if (!q) { var b = el("button", big ? "primary wide" : "add", big ? "加入购物车" : "+ 加入"); b.onclick = function () { setQty(k, 1); }; return b; }
    var w = el("div", big ? "step big" : "step"), m = el("button", null, "−"), n = el("span", null, String(q)), p = el("button", null, "+");
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

  function imgBox(it) {
    var im = el("div", "img"), src = safeImg(it.img), ph = el("span", null, CAT_ICON[it.c] || "🛒"); im.append(ph);
    if (src) {   // attached at once: a detached loading=lazy image never loads
      var i = document.createElement("img"); i.loading = "lazy"; i.decoding = "async"; i.referrerPolicy = "no-referrer"; i.alt = "";
      i.onload = function () { ph.remove(); im.classList.add("ok"); };   // hidden by opacity, not display:none (which blocks lazy load)
      i.onerror = function () { i.remove(); };
      i.src = src; im.append(i);
    }
    return im;
  }

  function tile(it) {      // v3: 5 per row; tap = detail sheet with the − / + buttons
    var t = el("button", "tile"); t.type = "button";
    t.append(imgBox(it), el("div", "tn", it.n), el("div", "tp", it.p == null ? "待确认" : "RM" + money(it.p)));
    var q = S.cart[it.k]; if (q) t.append(el("span", "badge", String(q)));
    t.onclick = function () { openSheet(it.k); };
    return t;
  }

  function row(it) {       // cart lines keep the roomy row layout
    var r = el("div", "row"), info = el("div", "info");
    info.append(el("div", "nm", it.n), el("div", "sp", (it.s ? "规格：" + it.s + " · " : "") + "单位：" + it.u));
    var pr = el("div", "pr"); pr.append(priceNode(it), stepper(it.k)); info.append(pr);
    r.append(imgBox(it), info); return r;
  }

  function openSheet(k) { S.sheetKey = k; renderSheet(); $("sheet").hidden = false; try { tg && tg.BackButton.show(); } catch (e) {} }
  function closeSheet() { S.sheetKey = null; $("sheet").hidden = true; try { if (tg && S.tab !== "cart") tg.BackButton.hide(); } catch (e) {} }
  function renderSheet() {
    var it = S.byKey[S.sheetKey], c = $("sheet-card"); c.textContent = ""; if (!it) return closeSheet();
    var top = el("div", "sh-top"), info = el("div", "info");
    info.append(el("div", "nm", it.n), el("div", "sp", (it.s ? "规格：" + it.s + " · " : "") + "单位：" + it.u), priceNode(it));
    top.append(imgBox(it), info);
    var done = el("button", "link", "完成"); done.onclick = closeSheet;
    c.append(top, stepper(it.k, true), done);
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
    $("sec-n").textContent = v.length + " 款商品 · 点商品选数量";
    if (!v.length) l.append(el("div", "empty", S.q ? "没找到相关商品，换个关键词试试" : "这个品类暂时没有商品"));
    S.listV = v; S.listN = 0; moreTiles();
  }
  // render in batches (1000+ goods): only PAGE_N tiles at a time, the next batch when the sentinel scrolls into view;
  // every <img> is loading=lazy, so only images near the viewport are fetched
  function moreTiles() {
    var l = $("list"), v = S.listV || [], old = $("more"); if (old) old.remove();
    var frag = document.createDocumentFragment(), end = Math.min(v.length, S.listN + PAGE_N);
    for (var i = S.listN; i < end; i++) frag.append(tile(v[i]));
    S.listN = end; l.append(frag);
    if (end < v.length) {
      var m = el("button", "more", "加载更多（还有 " + (v.length - end) + " 款）"); m.id = "more"; m.onclick = moreTiles; l.append(m);
      if (window.IntersectionObserver) {
        if (S.io) S.io.disconnect();
        S.io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) { S.io.disconnect(); moreTiles(); } }, {rootMargin: "600px"});
        S.io.observe(m);
      }
    }
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

  /* ---------- v3: address (Telegram LocationManager -> browser geolocation -> manual) ---------- */
  function renderAddr() {
    $("addr-box").hidden = !S.opts.location;
    var st = $("loc-st"); st.textContent = "";
    if (S.loc) {
      st.append(document.createTextNode("✅ 已定位" + (S.loc.acc ? "（精度约 " + S.loc.acc + " 米）" : "") + " · "));
      var a = el("a", null, "在地图上查看"); a.href = mapLink(S.loc); a.target = "_blank"; a.rel = "noopener";
      a.onclick = function (e) { if (tg && tg.openLink) { e.preventDefault(); try { tg.openLink(a.href); } catch (x) {} } };
      st.append(a, document.createTextNode("　"));
      var x = el("button", "rm", "清除定位"); x.onclick = function () { S.loc = null; renderAddr(); }; st.append(x);
    } else if (S.locMsg) st.textContent = S.locMsg;
    if (S.locSettings) {
      var b = el("button", "rm", "去开启定位权限");
      b.onclick = function () { try { tg.LocationManager.openSettings(); } catch (e) {} };
      st.append(document.createTextNode(" "), b);
    }
    $("loc").textContent = S.loc ? "📍 重新定位" : "📍 定位我的位置";
    if (document.activeElement !== $("addr")) $("addr").value = S.addr;
  }
  function gotLoc(lat, lng, acc) {
    if (typeof lat !== "number" || typeof lng !== "number" || !isFinite(lat) || !isFinite(lng)) return locFail("定位失败，请重试或手动填写地址");
    S.loc = {lat: +lat.toFixed(6), lng: +lng.toFixed(6), acc: acc && isFinite(acc) ? Math.min(Math.round(acc), 99999) : null};
    S.locMsg = ""; S.locSettings = false; haptic("medium"); renderAddr();
    if (S.opts.geocode) reverse(S.loc);
  }
  function locFail(msg, settings) { S.locMsg = msg; S.locSettings = !!settings; renderAddr(); }
  function browserLoc() {
    if (!navigator.geolocation) return locFail("此设备不支持定位，请手动填写地址");
    navigator.geolocation.getCurrentPosition(function (p) { gotLoc(p.coords.latitude, p.coords.longitude, p.coords.accuracy); },
      function (e) { locFail(e && e.code === 1 ? "没有定位权限，请在系统设置里允许 Telegram 定位，或手动填写地址" : "定位失败，请重试或手动填写地址"); },
      {enableHighAccuracy: true, timeout: 12000, maximumAge: 60000});
  }
  function locate() {
    S.locMsg = "定位中…"; S.locSettings = false; renderAddr();
    var LM = tg && tg.LocationManager;
    if (!LM || !ver("8.0")) return browserLoc();
    var go = function () {
      if (!LM.isLocationAvailable) return browserLoc();
      LM.getLocation(function (d) {
        if (d && typeof d.latitude === "number") return gotLoc(d.latitude, d.longitude, d.horizontal_accuracy);
        locFail("没有定位权限，可以手动填写地址", !!(LM.isAccessRequested && !LM.isAccessGranted));
      });
    };
    try { LM.isInited ? go() : LM.init(go); } catch (e) { browserLoc(); }
  }
  /* Optional reverse geocoding (opts.geocode, default OFF). One request per tap, cached per ~10 m, never automatic,
     endpoint switchable via opts.geocode_url without a page update. Failure = coordinates only. */
  function reverse(l) {
    var base = S.opts.geocode_url || "";
    try { if (new URL(base).protocol !== "https:") return; } catch (e) { return; }
    var key = "h1h_geo_" + l.lat.toFixed(4) + "," + l.lng.toFixed(4), hit = null;
    try { hit = sessionStorage.getItem(key); } catch (e) {}
    var use = function (name) { if (name && !S.addr.trim()) { S.addr = one(name).slice(0, ADDR_MAX); save(); } $("osm").hidden = !name; renderAddr(); };
    if (hit) return use(hit);
    if (Date.now() - (reverse.t || 0) < 1100) return;     // ≤ 1 request per second
    reverse.t = Date.now();
    var u = base + (base.indexOf("?") < 0 ? "?" : "&") + "format=jsonv2&zoom=18&addressdetails=0&accept-language=zh-CN,en&lat=" +
            l.lat.toFixed(6) + "&lon=" + l.lng.toFixed(6);
    var ctl = window.AbortController ? new AbortController() : null; if (ctl) setTimeout(function () { ctl.abort(); }, 6000);
    fetch(u, {referrerPolicy: "strict-origin-when-cross-origin", signal: ctl ? ctl.signal : undefined})
      .then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (j) { var n = j && typeof j.display_name === "string" ? j.display_name : ""; if (n) { try { sessionStorage.setItem(key, n); } catch (e) {} } use(n); })
      .catch(function () {});
  }

  /* ---------- v3: phone (Telegram.WebApp.requestContact -> the bot gets the verified contact message) ---------- */
  function renderPh() {
    $("ph-box").hidden = !S.opts.phone;
    $("tgph").hidden = !ver("6.9") || typeof (tg || {}).requestContact !== "function";
    $("ph-st").textContent = S.pc ? "✅ 已通过 Telegram 提供号码（机器人已收到，会写进订单）" : ($("tgph").hidden ? "" : "推荐：一键提供，不用手动输入");
    if (document.activeElement !== $("ph")) $("ph").value = S.ph;
  }
  function tgPhone() {
    try { tg.requestContact(function (ok) { S.pc = !!ok; if (!ok) toast("没有提供号码，也可以手动填写"); renderPh(); }); }
    catch (e) { toast("当前 Telegram 版本不支持，请手动填写"); }
  }

  function renderPay() {
    $("pay-box").hidden = !S.opts.pay;
    seg($("pay"), PAY.map(function (p) { return {v: p[0], t: p[1]}; }), S.pay, function (v) { S.pay = v; $("pay-box").classList.remove("need"); save(); renderPay(); });
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
    // Kimi 21:03: only 客服阿霞 left -> no choice shown, the order simply goes to her (index 0)
    var oneCs = S.data.cs.length === 1;
    $("cs").parentNode.style.display = oneCs ? "none" : "";
    if (oneCs) S.cs = 0;
    else seg($("cs"), S.data.cs.map(function (c, i) { return {v: i, t: c.icon + " 客服" + c.name}; }), S.cs, function (v) { S.cs = v; save(); renderCart(); });
    $("note").value = S.note; $("notec").textContent = S.note.length;
    renderAddr(); renderPh(); renderPay();
  }

  function showTab(t) {
    closeSheet();
    S.tab = t; $("v-shop").hidden = t !== "shop"; $("v-cart").hidden = t !== "cart";
    document.querySelectorAll(".tabs button").forEach(function (b) { b.classList.toggle("on", b.dataset.tab === t); });
    if (t === "cart") renderCart(); else renderList();
    renderBar(); window.scrollTo(0, 0);
    try { if (tg) { t === "cart" ? tg.BackButton.show() : tg.BackButton.hide(); } } catch (e) {}
  }

  function err(t) { var e = $("err"); e.textContent = t; e.hidden = !t; if (t) e.scrollIntoView({block: "center"}); }

  function lines() { return Object.keys(S.cart).filter(function (k) { return S.byKey[k]; }); }
  function payload(jump) {
    var d = {v: 2, items: lines().map(function (k) { return [k, S.cart[k], S.byKey[k].p]; }), cs: S.cs, city: S.city,
             note: S.note.trim(), pc: S.pc, j: !!jump};
    if (S.opts.location && (S.loc || S.addr.trim())) d.addr = {t: S.addr.trim(), lat: S.loc ? S.loc.lat : null, lng: S.loc ? S.loc.lng : null, acc: S.loc ? S.loc.acc : null};
    if (S.opts.phone && S.ph.trim()) d.ph = S.ph.trim();
    if (S.opts.pay && S.pay) d.pay = S.pay;
    return JSON.stringify(d);
  }
  function summary() {     // the text pre-filled into the 客服 chat (the user presses 发送 themselves)
    var cs = S.data.cs[S.cs] || {}, city = (S.data.cities.filter(function (c) { return c.id === S.city; })[0] || {}).name || S.city, t = totals();
    var L = [KB_LAUNCH ? "商城订单（订单号见机器人消息，价格以机器人订单为准）" : "商城订单（从菜单打开提交，价格以客服确认为准）", "城市：" + city + " · 客服：" + (cs.name || "")];
    lines().forEach(function (k, i) { var it = S.byKey[k]; L.push((i + 1) + ". " + it.n + " × " + S.cart[k] + it.u + (it.p == null ? "" : " ≈ RM " + money(it.p * S.cart[k]))); });
    L.push("商品合计约：RM " + money(t.sub) + " · 运费待确认");
    if (S.opts.location && S.addr.trim()) L.push("地址：" + S.addr.trim());
    if (S.opts.location && S.loc) L.push("定位：" + mapLink(S.loc));
    if (S.opts.phone && S.ph.trim()) L.push("电话：" + S.ph.trim()); else if (S.pc) L.push("电话：已通过 Telegram 提供给机器人");
    if (S.opts.pay && S.pay) L.push("付款：货到付款 · " + payLabel(S.pay));
    if (S.note.trim()) L.push("备注：" + S.note.trim());
    var s = L.join("\n"); return s.length > PREFILL_MAX ? s.slice(0, PREFILL_MAX - 1) + "…" : s;
  }

  function submit() {
    err("");
    if (!lines().length) return err("购物车是空的");
    if (S.data.cs.length === 1) S.cs = 0;                 // single 客服 (阿霞): never ask
    if (S.cs == null) return err("请选择为你服务的客服");
    if (/[\r\n]/.test(S.note) || S.note.length > S.data.limits.note) return err("备注需单行、最多 " + S.data.limits.note + " 字");
    if (S.opts.location && S.addr.length > ADDR_MAX) return err("地址最多 " + ADDR_MAX + " 字");
    if (S.opts.pay && !payLabel(S.pay)) {     // required: highlight the section instead of a silently disabled button
      $("pay-box").classList.add("need"); $("pay-box").scrollIntoView({block: "center"}); haptic("medium");
      return toast("请选择付款方式（货到付款）");
    }
    if (S.opts.phone && S.ph.trim() && !(PHONE_RX.test(S.ph.trim()) && S.ph.replace(/\D/g, "").length >= 6)) return err("电话号码格式不对（只填数字，可带 + 和区号）");
    var user = csUser(S.cs), jump = !!(S.opts.jump && user && ver("7.0") && tg && typeof tg.openTelegramLink === "function");
    var p = payload(jump);
    if (new TextEncoder().encode(p).length > MAX_BYTES) return err("商品太多，请分开下单");
    var menuMode = !!(tg && !KB_LAUNCH);   // menu / inline launch: sendData is unavailable -> straight to the 客服 chat, pre-filled
    if (menuMode && !jump) return err("请从机器人底部键盘「" + ENTRY + "」打开后再提交");
    if (!tg || (!menuMode && typeof tg.sendData !== "function")) return err("请在 Telegram 里从机器人底部键盘「" + ENTRY + "」打开后再提交");
    haptic("medium");
    // v3 one tap: open the chosen 客服's chat with the order pre-filled (Bot API 7.0+: the Mini App stays open), then hand
    // the order to the bot (sendData closes the Mini App). If the jump is not supported the bot's reply carries the same link.
    if (jump) { try { tg.openTelegramLink("https://t.me/" + user + "?text=" + encodeURIComponent(summary())); } catch (e) {} }
    if (menuMode) return toast("已打开客服对话，点「发送」即可；要在机器人里留订单号，请用底部键盘「" + ENTRY + "」");
    try { tg.sendData(p); }
    catch (e) { err("请从机器人底部键盘「" + ENTRY + "」打开后再提交（菜单/链接打开的页面无法提交给机器人）"); }
  }

  function boot(data) {
    S.data = data; S.opts = data.opts && typeof data.opts === "object" ? data.opts : {};
    data.items.forEach(function (it) { S.byKey[it.k] = it; });
    load(); renderChips(); renderList(); renderBar();
    if (tg && !KB_LAUNCH) $("mode").hidden = false;   // opened from the menu button: say what 提交 will do
    var u = (data.updated_at || "").replace("T", " ").slice(5, 16);
    $("upd").textContent = (u ? "🕒 价格更新：" + u + "（UTC+8）· " : "") + "价格以客服确认为准，不显示库存";
    $("q").oninput = function (e) { S.q = e.target.value.trim().slice(0, 20); renderChips(); renderList(); };
    $("note").oninput = function (e) { S.note = e.target.value.replace(/[\r\n]/g, " ").slice(0, S.data.limits.note); $("notec").textContent = S.note.length; save(); };
    $("addr").oninput = function (e) { S.addr = one(e.target.value).slice(0, ADDR_MAX); save(); };
    $("ph").oninput = function (e) { S.ph = e.target.value.slice(0, 23); save(); };
    $("loc").onclick = locate; $("tgph").onclick = tgPhone;
    $("go").onclick = function () { showTab(S.tab === "cart" ? "shop" : "cart"); };
    document.querySelectorAll(".tabs button").forEach(function (b) { b.onclick = function () { showTab(b.dataset.tab); }; });
    $("submit").onclick = submit; $("sheet-bg").onclick = closeSheet;
    $("clear").onclick = function () { S.cart = {}; save(); renderCart(); renderBar(); };
    if (tg) { try { tg.BackButton.onClick(function () { if (S.sheetKey) closeSheet(); else showTab("shop"); }); } catch (e) {} }
    S.render = function () { save(); renderBar(); if (S.tab === "cart") renderCart(); else renderList(); };
    S.gotLoc = gotLoc; S.openSheet = openSheet; S.summary = summary; S.payload = payload;
    window.__shop = S;   // for the offline demo / screenshots
  }

  if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }
  var src = (document.querySelector("meta[name=catalog]") || {}).content || "catalog.json";
  fetch(src + (src.indexOf("?") < 0 ? "?t=" : "&t=") + Math.floor(Date.now() / 300000), {cache: "no-cache"})
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (d) { if (!d || d.v !== 1 || !Array.isArray(d.items)) throw new Error("bad"); boot(d); })
    .catch(function () { err("商品目录加载失败，请稍后重试，或回到机器人点「👩‍💼 客服」直接下单。"); });
})();
