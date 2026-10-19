// api.js —— 全站唯一的 fetch 出口，顺带管登录态。
//
// 之前每个模块各自 fetch("/api/…")，没有统一的地方挂东西。现在只做两件事：
// 带上同源 cookie（登录身份），以及在会话失效时通知外面弹登录闸门。
//
// **没有访问码**：用户要求去掉了，网址本身就是唯一的秘密。

// 会话失效（401「没登录」）时各页面要能退回来。订阅方是 app.js 的登录闸门。
const onUnauthorized = new Set();
export const whenUnauthorized = (fn) => { onUnauthorized.add(fn); return () => onUnauthorized.delete(fn); };

// 冷启动的隔离实例偶发 5xx（Pyodide 初始化被打断，回 text/plain 的 "error code: 1101"）。
// GET 幂等，失败后退 400ms 重试一次，多半能落到已暖的实例上。
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function api(path, opts = {}) {
  const retriable = (opts.method || "GET").toUpperCase() === "GET";
  let res;
  for (let attempt = 0; ; attempt++) {
    try {
      res = await fetch(path, { credentials: "same-origin", ...opts });
    } catch (err) {
      if (retriable && !attempt && err.name !== "AbortError") { await sleep(400); continue; }
      throw err;
    }
    if (retriable && !attempt && res.status >= 500) { await sleep(400); continue; }
    break;
  }
  if (res.status === 401) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch { /* 响应不是 JSON */ }
    if (detail === "没登录") for (const fn of onUnauthorized) fn();
    throw Object.assign(new Error(detail || "未登录"), { status: 401, detail });
  }
  return res;
}

export const apiJson = async (path, opts) => {
  const res = await api(path, opts);
  if (!res.ok) throw Object.assign(new Error((await res.text()) || `HTTP ${res.status}`), { status: res.status });
  return res.json();
};

/** 安全读响应体。冷启动/边缘故障会回非 JSON（text/plain 的 "error code: 1101"），
 *  直接 res.json() 在 Safari 上会抛 "The string did not match the expected pattern"。
 *  先读文本再解析，非 JSON 一律折成人话的 { detail }。 */
export const readJson = async (res) => {
  const text = await res.text().catch(() => "");
  try { return JSON.parse(text); }
  catch { return { detail: res.ok ? "" : text.trim().replace(/^error code:\s*/, "服务暂时不可用：") || `HTTP ${res.status}` }; }
};

/** 把失败说成人话显示在页面上。
 *
 * 没有它的时候，任何一次取数失败都变成「空白页」或一句误导的「后端可能没
 * 重启」——会话过期、真的 500，看起来一模一样，排查全靠猜。三个页面的加载
 * 失败都走这里。
 */
export const errNote = (err, what) => {
  const p = document.createElement("p");
  p.className = "placeholder__note";
  p.textContent = `${what}失败（${err?.status || "?"}）：${err?.detail || err?.message || String(err)}`;
  return p;
};