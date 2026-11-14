/* shop-admin-v1 (Kimi 11-14 15:05 「香烟和酒区域，可以给我一个调整板块吗？我可以调整他的排序，上架下架，以及调整价格等」).
   Owner-only 商品管理 page for 香烟 + 酒水. Static page: it reads the PUBLIC catalog.json + overrides.json and posts the
   owner's changes to the bot with Telegram.WebApp.sendData (only possible from the bot's keyboard key, which the bot shows
   to the owner alone). The bot accepts the save ONLY from the owner's own account (message.from) in the private chat, so
   this page grants nothing by itself: anyone else who opens it can look but never change anything. No personal data. */
(function () {
  "use strict";
  var tg = (window.Telegram && window.Telegram.WebApp) || null;
  var KB_LAUNCH = !!(tg && typeof tg.initData === "string" && tg.initData === "");
  var CATS = [["cig", "香烟", "🚬"], ["baijiu", "白酒", "🥃"], ["spirits", "洋酒", "🥂"], ["wine", "葡萄酒", "🍷"], ["beer", "啤酒", "🍺"], ["drink", "其他酒水", "🍶"]];
  var MANAGED = {}; CATS.forEach(function (c) { MANAGED[c[0]] = c; });
  var MAX_BYTES = 4096, IMG_HOSTS = ["h1hcs.com"], PRICE_RX = /^\d{1,5}(\.\d{1,2})?$/, own = Object.prototype.hasOwnProperty;
  var S = {cat: "cig", q: "", flt: "all", byKey: {}, packs: {}, packOf: {}, heads: {}, def: {}, rev: null, botRev: null,
           base: {hide: {}, price: {}, ord: {}}, hide: {}, price: {}, ord: {}, ordSt: {}, sheet: null};

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function money(v) { if (v == null) return "—"; var s = (Math.round(v * 100) / 100).toFixed(2).replace(/\.00$/, ""); return s.replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
  function toast(t) { var x = $("toast"); x.textContent = t; x.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(function () { x.hidden = true; }, 1900); }
  function haptic(k) { try { tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred(k || "light"); } catch (e) {} }
  function norm(s) { return (s || "").toLowerCase().replace(/[\s（）()【】\[\]·•\-_/]/g, ""); }
  function safeImg(u) {
    try { var x = new URL(u); return x.protocol === "https:" && IMG_HOSTS.indexOf(x.hostname) >= 0 ? x.href : ""; }
    catch (e) { return /^(img|demo)\/[\w.\-]+$/.test(u || "") ? u : ""; }
  }
  function imgBox(it) {
    var im = el("div", "img"), src = safeImg(it.img), ph = el("span", null, (MANAGED[it.c] || [0, 0, "🛒"])[2]); im.append(ph);
    if (src) { var i = document.createElement("img"); i.loading = "lazy"; i.decoding = "async"; i.referrerPolicy = "no-referrer"; i.alt = "";
      i.onload = function () { ph.remove(); im.classList.add("ok"); }; i.onerror = function () { i.remove(); }; i.src = src; im.append(i); }
    return im;
  }
  function specOf(it) { return (it.s && it.s !== it.u ? it.s + " · " : "") + "单位：" + it.u; }
  function priceOf(k) { return own.call(S.price, k) ? S.price[k] : S.byKey[k].p; }
  function sameArr(a, b) { if (a.length !== b.length) return false; for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false; return true; }

  /* ---------- model ---------- */
  function setup(data, ov) {
    var items = data.items;
    items.forEach(function (it) { S.byKey[it.k] = it; });
    if (data.view && Array.isArray(data.view.packs)) data.view.packs.forEach(function (p) {
      if (!Array.isArray(p) || p.length < 2 || !items[p[0]]) return; var h = items[p[0]].k;
      p.slice(1).forEach(function (i) { var x = items[i]; if (x && x.k !== h && !S.packOf[x.k]) { S.packOf[x.k] = h; (S.packs[h] = S.packs[h] || []).push(x.k); } });
    });
    ov = ov && ov.v === 1 ? ov : {hide: [], price: {}, order: {}};
    S.rev = typeof ov.rev === "number" ? ov.rev : null;
    (Array.isArray(ov.hide) ? ov.hide : []).forEach(function (k) { if (S.byKey[k]) S.base.hide[k] = true; });
    if (ov.price && typeof ov.price === "object") Object.keys(ov.price).forEach(function (k) { if (S.byKey[k] && typeof ov.price[k] === "number") S.base.price[k] = ov.price[k]; });
    CATS.forEach(function (c) {
      var id = c[0], heads = items.filter(function (it) { return it.c === id && !S.packOf[it.k]; }).map(function (it) { return it.k; });
      S.def[id] = heads.slice();
      var lst = ov.order && Array.isArray(ov.order[id]) ? ov.order[id] : null, cur = heads;
      if (lst && lst.length) {
        var pos = {}; lst.forEach(function (k, i) { if (!own.call(pos, k)) pos[k] = i; });
        cur = heads.map(function (k, j) { return [own.call(pos, k) ? pos[k] : 1e6 + j, k]; }).sort(function (a, b) { return a[0] - b[0]; }).map(function (a) { return a[1]; });
        S.base.ord[id] = true;
      }
      S.heads[id] = cur;
    });
    S.ord0 = {}; CATS.forEach(function (c) { S.ord0[c[0]] = S.heads[c[0]].slice(); });
    resetEdits();
  }
  function resetEdits() {
    S.hide = {}; Object.keys(S.base.hide).forEach(function (k) { S.hide[k] = true; });
    S.price = {}; Object.keys(S.base.price).forEach(function (k) { S.price[k] = S.base.price[k]; });
    CATS.forEach(function (c) { S.heads[c[0]] = S.ord0[c[0]].slice(); S.ordSt[c[0]] = "same"; });
  }
  function changes() {
    var hide = [], show = [], price = {}, order = {}, n = 0;
    Object.keys(S.byKey).forEach(function (k) {
      if (!MANAGED[S.byKey[k].c]) return;
      var h = !!S.hide[k], h0 = !!S.base.hide[k];
      if (h !== h0) { (h ? hide : show).push(k); n++; }
      var p = own.call(S.price, k) ? S.price[k] : null, p0 = own.call(S.base.price, k) ? S.base.price[k] : null;
      if (p !== p0) { price[k] = p; n++; }
    });
    CATS.forEach(function (c) {
      var id = c[0];
      if (S.ordSt[id] === "custom" && !sameArr(S.heads[id], S.ord0[id])) {
        var full = []; S.heads[id].forEach(function (k) { full.push(k); (S.packs[k] || []).forEach(function (p) { full.push(p); }); });
        order[id] = full; n++;
      } else if (S.ordSt[id] === "reset") { order[id] = []; n++; }
    });
    return {hide: hide, show: show, price: price, order: order, n: n};
  }
  function moveTo(k, i) {
    var a = S.heads[S.cat], j = a.indexOf(k); if (j < 0) return;
    i = Math.max(0, Math.min(a.length - 1, i)); if (i === j) return;
    a.splice(j, 1); a.splice(i, 0, k); S.ordSt[S.cat] = "custom"; haptic();
  }

  /* ---------- render ---------- */
  function renderStatus() {
    var st = $("st"); st.textContent = "";
    st.append(document.createTextNode("小程序当前："), el("b", null, S.rev == null ? "版本未知" : "第 " + S.rev + " 版"));
    if (S.botRev != null) st.append(document.createTextNode(" · 机器人：第 " + S.botRev + " 版"));
    var w = $("warn"), msg = "";
    if (!KB_LAUNCH) msg = "只能查看：请在机器人里点底部键盘「🛠 打开商品管理」打开，才能保存改动。";
    else if (S.botRev != null && S.rev != null && S.botRev > S.rev) msg = "机器人里已经是第 " + S.botRev + " 版，小程序还停在第 " + S.rev + " 版（发布中或待发布），这里显示的是第 " + S.rev + " 版。现在保存的改动会合并到最新版上。";
    w.textContent = msg; w.hidden = !msg;
  }
  function renderChips() {
    var c = $("chips"); c.textContent = "";
    var row = el("div", "crow"), row2 = el("div", "crow");
    CATS.forEach(function (x, i) {
      var n = S.heads[x[0]].length; if (!n) return;
      var b = el("button", S.cat === x[0] ? "on" : "", x[1] + " " + n);
      b.onclick = function () { S.cat = x[0]; S.q = ""; $("q").value = ""; S.flt = "all"; render(); window.scrollTo(0, 0); };
      (i < 3 ? row : row2).append(b);
    });
    c.append(row, row2);
  }
  function renderFilter() {
    var f = $("flt"); f.textContent = "";
    var all = S.heads[S.cat], nOff = 0, nPr = 0;
    all.forEach(function (k) { [k].concat(S.packs[k] || []).forEach(function (x) { if (S.hide[x]) nOff++; if (own.call(S.price, x)) nPr++; }); });
    [["all", "全部"], ["off", "已下架 " + nOff], ["pr", "已改价 " + nPr]].forEach(function (x) {
      var b = el("button", S.flt === x[0] ? "on" : "", x[1]); b.onclick = function () { S.flt = x[0]; renderList(); renderFilter(); }; f.append(b);
    });
  }
  function canDrag() { return !S.q && S.flt === "all"; }
  function visibleKeys() {
    var q = norm(S.q);
    return S.heads[S.cat].filter(function (k) {
      var vs = [k].concat(S.packs[k] || []);
      if (q && !vs.some(function (x) { return norm(S.byKey[x].n + S.byKey[x].s).indexOf(q) >= 0; })) return false;
      if (S.flt === "off") return vs.some(function (x) { return S.hide[x]; });
      if (S.flt === "pr") return vs.some(function (x) { return own.call(S.price, x); });
      return true;
    });
  }
  function row(k, i) {
    var it = S.byKey[k], r = el("div", "arow" + (S.hide[k] ? " off" : "")); r.dataset.k = k;
    var d = el("span", "drag", "≡"); d.title = "按住拖动排序";
    d.addEventListener("pointerdown", function (e) { if (!canDrag()) { toast("搜索或筛选时不能拖动，请先回到「全部」"); return; } startDrag(r, e); });
    var info = el("div", "ainfo"), nm = el("div", "nm", it.n), sp = el("div", "sp", specOf(it));
    if (S.packs[k]) sp.append(el("i", "tag pk2", "可整箱"));
    var pr = el("div", "apr"), p = priceOf(k);
    pr.append(el("small", null, "RM "), el("b", null, money(p)));
    if (own.call(S.price, k)) { pr.append(el("s", null, "商城 " + money(it.p)), el("i", "tag pr", "改价")); }
    if (S.hide[k]) pr.append(el("i", "tag off", "已下架"));
    var ph = (S.packs[k] || []).filter(function (x) { return S.hide[x] || own.call(S.price, x); }).length;
    if (ph) pr.append(el("i", "tag pk2", "整箱有改动"));
    info.append(nm, sp, pr);
    info.onclick = function () { openSheet(k); };
    var sw = el("button", "sw" + (S.hide[k] ? " off" : ""), S.hide[k] ? "已下架" : "上架中");
    sw.onclick = function () { setHide(k, !S.hide[k]); };
    var no = el("span", "no", String(S.heads[S.cat].indexOf(k) + 1));
    var im = imgBox(it); im.onclick = function () { openSheet(k); };
    r.append(d, no, im, info, sw);
    var c = changes(); if (c.hide.concat(c.show).indexOf(k) >= 0 || own.call(c.price, k)) r.classList.add("chg");
    return r;
  }
  function renderList() {
    var l = $("alist"); l.textContent = "";
    var ks = visibleKeys(), name = MANAGED[S.cat][1];
    $("sec-t").textContent = S.q ? name + " · 搜索「" + S.q + "」" : name;
    $("sec-n").textContent = ks.length + " 款" + (S.ordSt[S.cat] !== "same" ? " · 顺序已改" : S.base.ord[S.cat] ? " · 自定义顺序" : "");
    $("tip").textContent = canDrag() ? "按住左边「≡」上下拖动排序；点商品改价格、置顶 / 上移 / 下移；右边按钮上架 / 下架。" : "筛选中：可以改价格和上架下架；要拖动排序请回到「全部」。";
    var frag = document.createDocumentFragment();
    ks.forEach(function (k, i) { frag.append(row(k, i)); });
    l.append(frag);
    if (!ks.length) l.append(el("div", "empty", "没有符合条件的商品"));
    if (canDrag() && (S.base.ord[S.cat] || S.ordSt[S.cat] === "custom")) {
      var rs = el("button", "reset", "恢复默认顺序（" + (S.cat === "cig" ? "与华润万家商城一致" : "按价格从高到低") + "）");
      rs.onclick = function () { S.heads[S.cat] = S.def[S.cat].slice(); S.ordSt[S.cat] = S.base.ord[S.cat] ? "reset" : "same"; render(); toast("已恢复默认顺序，保存后生效"); };
      l.append(rs);
    }
  }
  function renderBar() {
    var c = changes();
    $("chg").textContent = c.n ? "已改 " + c.n + " 项，未保存" : "没有改动";
    $("chg2").textContent = c.n ? "点「保存」后机器人马上生效，小程序随后更新" : "改完点「保存」，机器人和小程序都会更新";
    $("save").disabled = !c.n || !KB_LAUNCH; $("save").textContent = c.n ? "保存（" + c.n + "）" : "保存";
    $("undo").hidden = !c.n;
  }
  function render() { renderStatus(); renderChips(); renderFilter(); renderList(); renderBar(); if (S.sheet) renderSheet(); }
  function setHide(k, v) { if (v) S.hide[k] = true; else delete S.hide[k]; haptic(); render(); toast(v ? "已设为下架（保存后生效）" : "已设为上架（保存后生效）"); }

  /* ---------- drag to reorder (pointer events; works with touch) ---------- */
  function startDrag(r, e) {
    e.preventDefault(); var l = $("alist"); r.classList.add("dragging"); haptic("medium");
    try { e.target.setPointerCapture(e.pointerId); } catch (x) {}
    var scr = 0, lastY = e.clientY, t = setInterval(function () { if (scr) window.scrollBy(0, scr); }, 30);
    function over(y) {
      var rows = [].slice.call(l.querySelectorAll(".arow"));
      for (var i = 0; i < rows.length; i++) { var b = rows[i].getBoundingClientRect(); if (y >= b.top && y <= b.bottom) return rows[i]; }
      return null;
    }
    function mv(ev) {
      lastY = ev.clientY; var o = over(lastY);
      if (o && o !== r) { var b = o.getBoundingClientRect(); if (lastY > b.top + b.height / 2) o.after(r); else o.before(r); }
      scr = lastY < 90 ? -12 : lastY > innerHeight - 110 ? 12 : 0;
    }
    function up() {
      clearInterval(t); document.removeEventListener("pointermove", mv); document.removeEventListener("pointerup", up); document.removeEventListener("pointercancel", up);
      r.classList.remove("dragging");
      var keys = [].slice.call(l.querySelectorAll(".arow")).map(function (x) { return x.dataset.k; });
      if (!sameArr(keys, S.heads[S.cat])) { S.heads[S.cat] = keys; S.ordSt[S.cat] = "custom"; }
      render();
    }
    document.addEventListener("pointermove", mv); document.addEventListener("pointerup", up); document.addEventListener("pointercancel", up);
  }
  S.dragTo = function (k, i) { moveTo(k, i); render(); };     // demo / tests

  /* ---------- detail sheet: price, 上架/下架, position, 整箱 ---------- */
  function openSheet(k) { S.sheet = k; renderSheet(); $("sheet").hidden = false; try { tg && tg.BackButton.show(); } catch (e) {} }
  function closeSheet() { S.sheet = null; $("sheet").hidden = true; try { tg && tg.BackButton.hide(); } catch (e) {} render(); }
  function priceBox(k) {
    var it = S.byKey[k], w = el("div", "asec");
    w.append(el("div", "lbl", "价格（商城价 RM " + money(it.p) + " / " + it.u + "）"));
    var pr = el("div", "prow"), inp = el("input"); inp.type = "text"; inp.inputMode = "decimal"; inp.maxLength = 8;
    inp.placeholder = "不填 = 用商城价 " + money(it.p); inp.value = own.call(S.price, k) ? String(S.price[k]) : "";
    var hint = el("div", "hint", own.call(S.price, k) ? "已改价：客户看到 RM " + money(S.price[k]) + "，以后商城同步也不会覆盖，直到你恢复商城价" : "现在用商城价");
    inp.oninput = function () {
      var v = inp.value.trim().replace(/^rm\s*/i, "");
      if (!v) { delete S.price[k]; inp.classList.remove("bad"); hint.textContent = "现在用商城价"; renderBar(); return; }
      if (!PRICE_RX.test(v) || +v <= 0) { inp.classList.add("bad"); hint.textContent = "只填数字，最多两位小数"; return; }
      inp.classList.remove("bad"); S.price[k] = Math.round(+v * 100) / 100; hint.textContent = "客户将看到 RM " + money(S.price[k]) + "（保存后生效）"; renderBar();
    };
    var rs = el("button", null, "恢复商城价"); rs.onclick = function () { delete S.price[k]; renderSheet(); renderBar(); };
    pr.append(inp, rs); w.append(pr, hint);
    return w;
  }
  function hideSeg(k) {
    var s = el("div", "seg");
    [[false, "上架"], [true, "下架"]].forEach(function (x) {
      var b = el("button", !!S.hide[k] === x[0] ? "on" : "", x[1]); b.onclick = function () { if (x[0]) S.hide[k] = true; else delete S.hide[k]; renderSheet(); renderBar(); }; s.append(b);
    });
    return s;
  }
  function renderSheet() {
    var k = S.sheet, it = S.byKey[k], c = $("sheet-card"); c.textContent = ""; if (!it) return;
    var top = el("div", "sh-top"), info = el("div", "info");
    info.append(el("div", "nm", it.n), el("div", "sp", specOf(it)));
    top.append(imgBox(it), info); c.append(top, priceBox(k));
    var hs = el("div", "asec"); hs.append(el("div", "lbl", "上架 / 下架（下架后客户看不到，也不能下单）"), hideSeg(k)); c.append(hs);
    var a = S.heads[S.cat], i = a.indexOf(k);
    if (i >= 0) {
      var ps = el("div", "asec"); ps.append(el("div", "lbl", "位置：第 " + (i + 1) + " / " + a.length + " 位" + (canDrag() ? "" : "（筛选中也可以调整）")));
      var g = el("div", "mvb");
      [["⏫ 置顶", 0], ["⬆ 上移", i - 1], ["⬇ 下移", i + 1], ["⏬ 置底", a.length - 1]].forEach(function (x) {
        var b = el("button", null, x[0]); b.disabled = x[1] < 0 || x[1] >= a.length || x[1] === i;
        b.onclick = function () { moveTo(k, x[1]); renderSheet(); renderBar(); }; g.append(b);
      });
      var pr = el("div", "prow"); pr.style.marginTop = "8px";
      var inp = el("input"); inp.type = "number"; inp.min = 1; inp.max = a.length; inp.placeholder = "移到第几位（1-" + a.length + "）";
      var go = el("button", null, "移动"); go.onclick = function () { var n = parseInt(inp.value, 10); if (n >= 1 && n <= a.length) { moveTo(k, n - 1); renderSheet(); renderBar(); toast("已移到第 " + n + " 位"); } else toast("请输入 1-" + a.length); };
      pr.append(inp, go); ps.append(g, pr); c.append(ps);
    }
    (S.packs[k] || []).forEach(function (pk) {
      var p = S.byKey[pk], b = el("div", "pkb"), t = el("div", "t");
      t.append(el("span", null, "整箱：" + p.n + (p.s && p.s !== p.u ? "（" + p.s + "）" : "")), hideSeg(pk));
      b.append(t, priceBox(pk)); c.append(b);
    });
    var done = el("button", "primary wide", "完成"); done.style.marginTop = "16px"; done.onclick = closeSheet; c.append(done);
  }

  /* ---------- save ---------- */
  function payload() {
    var c = changes(), d = {t: "adm", v: 1, base: S.rev == null ? 0 : S.rev};
    if (c.hide.length) d.hide = c.hide; if (c.show.length) d.show = c.show;
    if (Object.keys(c.price).length) d.price = c.price; if (Object.keys(c.order).length) d.order = c.order;
    return JSON.stringify(d);
  }
  function save() {
    var e = $("err"); e.hidden = true;
    if (!changes().n) return;
    if (!KB_LAUNCH || !tg || typeof tg.sendData !== "function") { e.textContent = "请在机器人里点底部键盘「🛠 打开商品管理」打开后再保存。"; e.hidden = false; return; }
    var p = payload();
    if (new TextEncoder().encode(p).length > MAX_BYTES) { e.textContent = "一次改动太多，请先保存一部分（例如先只保存一个分类的排序），再打开继续改。"; e.hidden = false; return; }
    haptic("medium");
    try { tg.sendData(p); } catch (x) { e.textContent = "保存失败，请从机器人底部键盘重新打开。"; e.hidden = false; }
  }

  function boot(data, ov) {
    var m = /[?&]rev=(\d{1,7})/.exec(location.search); S.botRev = m ? +m[1] : null;
    setup(data, ov);
    $("q").oninput = function (e) { S.q = e.target.value.trim().slice(0, 20); renderList(); renderFilter(); };
    $("save").onclick = save; $("sheet-bg").onclick = closeSheet;
    $("undo").onclick = function () { resetEdits(); render(); toast("已撤销本页所有未保存的改动"); };
    if (tg) { try { tg.BackButton.onClick(function () { if (S.sheet) closeSheet(); }); tg.disableVerticalSwipes && tg.disableVerticalSwipes(); } catch (e) {} }
    render();
    S.changes = changes; S.payload = payload; S.openSheet = openSheet; S.setHide = setHide; S.render = render;
    window.__adm = S;
  }

  if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }
  var bust = function (u, n) { return u + "?t=" + Math.floor(Date.now() / n); };
  Promise.all([
    fetch(bust("catalog.json", 60000), {cache: "no-cache"}).then(function (r) { if (!r.ok) throw 0; return r.json(); }),
    fetch(bust("overrides.json", 10000), {cache: "no-cache"}).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
  ]).then(function (a) { if (!a[0] || a[0].v !== 1 || !Array.isArray(a[0].items)) throw 0; boot(a[0], a[1]); })
    .catch(function () { var e = $("err"); e.textContent = "商品目录加载失败，请稍后重试。"; e.hidden = false; });
})();
