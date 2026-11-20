/* AstrBot 把 bridge-sdk.js 注入在 app.js **之后**（实测 56 行是本文件、57 行才是 SDK），
   所以脚本刚执行时 window.AstrBotPluginView 还不存在——只抓一次就会永远抓不到，
   面板会一直「读取失败」。这里每次调用都重新找，并给启动加一个等待桥接的重试。 */
let bridge = null;

/* AstrBot 的官方桥接有时候不注入（或者注入晚于本脚本），
   这时用 postMessage 自建一条同样的通道——跟终端面板里的 createInlineBridge 一致。 */
function createInlineBridge() {
  if (!window.parent || window.parent === window) return null;
  const pending = new Map();
  let counter = 0;
  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const message = event.data;
    if (!message || message.channel !== "astrbot-plugin-page") return;
    if (message.kind !== "response") return;
    const item = pending.get(message.requestId);
    if (!item) return;
    pending.delete(message.requestId);
    if (message.ok) item.resolve(message.data);
    else item.reject(new Error(message.error || "插件桥接请求失败"));
  });
  function request(action, payload) {
    return new Promise((resolve, reject) => {
      const requestId = "plugin_req_" + (++counter);
      const timer = setTimeout(() => {
        if (pending.delete(requestId)) reject(new Error("插件桥接超时"));
      }, 25000);
      pending.set(requestId, {
        resolve: (value) => { clearTimeout(timer); resolve(value); },
        reject: (error) => { clearTimeout(timer); reject(error); },
      });
      try {
        window.parent.postMessage({
          channel: "astrbot-plugin-page",
          kind: "request",
          requestId,
          action,
          ...(payload || {}),
        }, "*");
      } catch (error) {
        clearTimeout(timer);
        pending.delete(requestId);
        reject(error);
      }
    });
  }
  try { window.parent.postMessage({ channel: "astrbot-plugin-page", kind: "ready" }, "*"); } catch (error) {}
  return {
    apiGet: (endpoint, params) => request("api:get", { endpoint, params }),
    apiPost: (endpoint, body) => request("api:post", { endpoint, body }),
  };
}

function resolveBridge() {
  if (bridge) return bridge;
  const candidates = [];
  try { candidates.push(window.AstrBotPluginView, window.AstrBotPluginPage); } catch (err) {}
  try { candidates.push(window.parent.AstrBotPluginView, window.parent.AstrBotPluginPage); } catch (err) {}
  try { candidates.push(window.top.AstrBotPluginView, window.top.AstrBotPluginPage); } catch (err) {}
  bridge = candidates.find((item) => item && typeof item.apiGet === "function")
    || createInlineBridge();
  return bridge;
}
function waitForBridge(fn, tries) {
  const left = (typeof tries === "number") ? tries : 50;   // 默认最多等 6 秒
  if (resolveBridge()) { fn(); return; }
  if (left > 0) setTimeout(() => waitForBridge(fn, left - 1), 120);
}
const $ = (id) => document.getElementById(id);

function unwrap(res) {
  if (res == null) return null;
  let v = res;
  // 桥接会剥一层；有些版本还会把 {code,data} 原样给过来，最多剥两层
  for (let i = 0; i < 2; i += 1) {
    if (v && typeof v === "object" && "data" in v
        && (v.code === 0 || v.code === undefined) && !("balance" in v)
        && !("positions" in v) && !("items" in v) && !("link" in v)) {
      v = v.data;
      continue;
    }
    break;
  }
  return v;
}

let lastError = "";
async function get(path) {
  const b = resolveBridge();
  if (!b) { lastError = "找不到页面桥接（请从插件详情→查看页面重新打开）"; return null; }
  try {
    const raw = await b.apiGet(path);
    const v = unwrap(raw);
    if (!v) lastError = path + " 返回为空";
    return v;
  } catch (e) { lastError = path + " 请求失败：" + (e && e.message ? e.message : e); return null; }
}
async function post(path, body) {
  const b = resolveBridge();
  if (!b) { lastError = "找不到页面桥接"; return null; }
  try { return unwrap(await b.apiPost(path, body || {})); }
  catch (e) { lastError = path + " 请求失败：" + (e && e.message ? e.message : e); return null; }
}

function money(v) {
  const n = Number(v || 0);
  return "¥" + n.toFixed(2);
}

const BANKRUPT_TEXT = {
  losing: "她最近亏得有点多，嘴上还硬，心里已经开始发慌了。",
  ruined: "她已经亏到快破产了，会来找你哭「老公我好像有点破产了」。",
  broke: "她卡里基本没钱了，会来找你哭「老公我好像有点破产了」。",
};

async function loadStatus() {
  const d = await get("status");
  if (!d || typeof d !== "object") {
    // 把「哪一步失败」写出来，并给个重试入口，别只留一个「读取失败」
    ["balance", "savings", "investValue", "investCash"].forEach((id) => {
      const el = $(id); if (el) el.textContent = "读取失败";
    });
    const tip = $("investMeta");
    if (tip) {
      tip.innerHTML = '金融数据读取失败：' + (lastError || "桥接没返回 status")
        + '（<span style="text-decoration:underline;cursor:pointer" id="retryStatus">点这里重试</span>）';
      const btn = $("retryStatus");
      if (btn) btn.onclick = () => loadStatus();
    }
    return;
  }
  $("balance").textContent = money(d.balance);
  $("savings").textContent = money(d.savings);
  $("owed").textContent = d.owed_to_user ? money(d.owed_to_user) : "无";
  $("savingsRate").textContent = d.savings_rate ? ("年化 " + d.savings_rate + "%") : "不计息";
  $("spent").textContent = money(d.month_spent);
  $("earned").textContent = money(d.month_income);
  $("city").textContent = (d.city || "未配置") + " · " + d.city_level;
  const pay = d.salary || {};
  $("salaryGross").textContent = money(pay.gross);
  $("salaryNet").textContent = money(pay.net);
  $("salaryDay").textContent = pay.pay_day ? ("每月 " + pay.pay_day + " 号") : "—";
  $("salarySource").textContent = pay.source || "—";
  const houseKind = String(d.house_kind || "");
  const kindText = { own: "全款房", loan: "贷款房", rent: "租房" }[houseKind] || (d.own_house ? "全款房" : "租房");
  $("levelPill").textContent = kindText;
  const houseDesc = $("houseDesc");
  if (houseDesc) houseDesc.textContent = d.house_desc || "—";
  const carDesc = $("carDesc");
  if (carDesc) carDesc.textContent = d.car_desc || "—";
  $("fixedTotal").textContent = money(d.fixed_total) + "/月";
  const a = Number(d.anxiety || 0);
  $("anxietyHint").textContent = a >= 0.7 ? "她现在有点为钱发愁（" + a.toFixed(2) + "）"
    : a >= 0.3 ? "还算稳（" + a.toFixed(2) + "）" : "没什么压力";

  const bor = d.borrow || {};
  if ($("borrowHint")) {
    const owed = Number(bor.owed || 0);
    $("borrowHint").textContent = owed > 0
      ? ("她欠你 " + money(owed) + "；今天转账还可借 " + money(bor.transfer_left || 0) +
         "，红包剩 " + money(bor.red_left || 0))
      : ("私聊里发「[转账]500 元」或「[红包]200 元」（可带 USD / HKD）才算借款；转账每天最多一万，红包单个最多 200、累计一万。");
  }

  const inv = d.invest || {};
  const pnl = Number(inv.total_pnl || 0);
  const dayPnl = Number(inv.day_pnl || 0);
  $("investValue").textContent = money(inv.total_value);
  $("investPnl").textContent = (pnl >= 0 ? "+" : "") + money(pnl);
  $("investDay").textContent = (dayPnl >= 0 ? "+" : "") + money(dayPnl);
  $("investCash").textContent = money(inv.cash);
  if ($("investSavings")) $("investSavings").textContent = money(inv.savings);
  if ($("investPower")) $("investPower").textContent = money(inv.buying_power);
  $("investPill").textContent = (inv.aggressive ? "FX 战士 · " : "") + (inv.count || 0) + " 只持仓";
  const CUR = { CNY: "¥", USD: "$", HKD: "HK$" };
  $("positions").innerHTML = (inv.positions || []).map((i) => {
    const cur = CUR[i.currency] || "¥";
    const native = (i.currency && i.currency !== "CNY")
      ? " · " + cur + Number(i.last || 0).toFixed(2)
      : "";
    return '<li><span class="p">' + (i.name || i.symbol) + " · " + i.qty + " 股" + native + "</span>" +
      '<span class="s">' + money(i.market_value) + "（" +
      (i.pnl >= 0 ? "+" : "") + i.pnl_pct.toFixed(1) + "%）</span></li>";
  }).join("") || '<li class="empty">还没有持仓，等她自己去买</li>';

  const bk = inv.bankrupt || {};
  const bkText = BANKRUPT_TEXT[bk.level] || "";
  $("investMeta").textContent = (bkText ? bkText + " " : "") +
    "模拟盘：A 股行情来自同花顺，港美股与兜底走腾讯；期货走新浪。" +
    (inv.aggressive ? ("她现在开 " + (inv.leverage || 1) + " 倍杠杆、单只最多压 " +
      Number(inv.max_weight || 1).toFixed(2) + " 倍身家、最多 " + (inv.max_positions || 10) + " 只。" +
      (Number(inv.margin_debt || 0) > 0 ? " 保证金借款 " + money(inv.margin_debt) + "。" : "")) : "");

  $("fixed").innerHTML = (d.fixed || []).map((i) =>
    '<li><span class="p">' + i.name + '</span><span class="s">' + money(i.amount) + "</span></li>"
  ).join("") || '<li class="empty">无</li>';

  $("own_house").checked = !!d.own_house;
  $("own_car").checked = !!d.own_car;
}

async function loadHistory() {
  const d = await get("history");
  const items = (d && d.items) || [];
  const list = $("history");
  if (!items.length) { list.innerHTML = '<li class="empty">还没有账</li>'; return; }
  list.innerHTML = items.slice().reverse().slice(0, 40).map((it) => {
    const neg = ["expense", "fixed", "repay", "stock_buy"].includes(it.kind);
    const cls = it.kind === "expense_failed" ? "bad" : (neg ? "" : "ok");
    const sign = neg ? "-" : "+";
    return '<li><span class="t">' + (it.time || "") + '</span><span class="p">' +
      (it.reason || it.kind) + '</span><span class="s ' + cls + '">' +
      sign + money(it.amount).slice(1) + "</span></li>";
  }).join("");
}

async function openSubpage() {
  $("subpage").hidden = false;
  const d = await get("status");
  if (d) {
    $("subBalance").textContent = money(d.balance);
    $("subSavings").textContent = money(d.savings);
    $("subOwed").textContent = d.owed_to_user ? money(d.owed_to_user) : "无";
    const pay = d.salary || {};
    $("subGross").textContent = money(pay.gross);
    $("subNet").textContent = money(pay.net);
  }
  if (d) {
    const inv = d.invest || {};
    const pnl = Number(inv.total_pnl || 0);
    const day = Number(inv.day_pnl || 0);
    $("subInvestValue").textContent = money(inv.total_value);
    $("subInvestPnl").textContent = (pnl >= 0 ? "+" : "") + money(pnl);
    $("subInvestDay").textContent = (day >= 0 ? "+" : "") + money(day);
  }
  const m = await get("market");
  const prices = (m && m.prices) || {};
  const names = Object.keys(prices).sort();
  $("subMarket").innerHTML = names.length ? names.map((name) =>
    '<li><span class="p">' + name + '</span><span class="s">¥' +
    Number(prices[name] || 0).toFixed(2) + '</span></li>'
  ).join("") : '<li class="empty">菜价读取失败</li>';
  $("subMarketHint").textContent = m
    ? ((m.date || "") + (m.weather ? " · " + m.weather : "")) : "读取失败";

  const f = await get("food/quote");
  const ready = (f && f.ready) || [];
  $("subReady").innerHTML = ready.length ? ready.map((it) =>
    '<li><span class="p">' + (it.name || "") + " · 饱食 " + (it.satiety || 0) + '</span>' +
    '<span class="s">¥' + Number(it.price || 0).toFixed(2) + '</span></li>'
  ).join("") : '<li class="empty">外卖价读取失败</li>';
  $("subReadyHint").textContent = f
    ? ((f.city || "") + (f.level ? " · " + f.level : "")) : "读取失败";
}

$("brandTitle").addEventListener("dblclick", openSubpage);
let _lastBrandTap = 0;
$("brandTitle").addEventListener("touchend", (ev) => {
  const now = Date.now();
  if (now - _lastBrandTap < 360) {
    ev.preventDefault();
    _lastBrandTap = 0;
    openSubpage();
    return;
  }
  _lastBrandTap = now;
});
$("subClose").addEventListener("click", () => { $("subpage").hidden = true; });

$("saveAssets").addEventListener("click", async () => {
  const body = {
    own_house: $("own_house").checked,
    own_car: $("own_car").checked,
  };
  const res = await post("assets", body);
  $("assetsHint").textContent = res ? "已保存。" : "保存失败。";
  loadStatus();
});

waitForBridge(() => {
  loadStatus();
  loadHistory();
});
setInterval(loadStatus, 30000);

