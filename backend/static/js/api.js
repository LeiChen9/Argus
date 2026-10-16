// api.js —— 全站唯一的 fetch 出口，顺带管 access code。
//
// 之前每个模块各自 fetch("/api/…")，一个 access code 都不带——Worker 那边
// _authorized 查的是 header 或 ?code=，两者都没有，于是浏览器里每个请求都是
// 401。code 从地址栏的 ?code= 拿一次存进 localStorage（跟 chat.js 存 sid 一个
// 路数），之后每个请求带上它。用户身份走 HttpOnly cookie，浏览器自动带，JS 读不到。

const KEY = "argus_code";

export const accessCode = () => {
  let v = localStorage.getItem(KEY);
  if (!v) {
    v = new URLSearchParams(location.search).get("code") || "";
    if (v) localStorage.setItem(KEY, v);
  }
  return v;
};

// 没登录时（401 + detail「没登录」）各页面要能退回来。订阅方是 app.js 的登录闸门。
const onUnauthorized = new Set();
export const whenUnauthorized = (fn) => { onUnauthorized.add(fn); return () => onUnauthorized.delete(fn); };

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    ...opts,
    headers: { "X-Access-Code": accessCode(), ...(opts.headers || {}) },
  });
  if (res.status === 401) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch { /* 响应不是 JSON */ }
    // access code 不对是另一回事（换个 code 就行），只有「没登录」才弹登录闸门。
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