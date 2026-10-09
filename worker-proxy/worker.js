// 公网入口：稳定域名 → 本机。
//
// ORIGIN 不写死在这里，而是每次 quick tunnel 起来后由 scripts/restart.sh 写进 KV。
// 之前它是指向 trycloudflare 随机域名的硬编码字符串，于是每次重启都要 wrangler
// deploy；限流或部署失败时会把 ORIGIN 洗成空串并推上线，公网入口直接瘫。
// 改成 KV 后，改上游只是一次 KV 写入，不需要重新部署，失败也不会污染线上代码。
const FALLBACK = "http://127.0.0.1:7800";

export default {
  async fetch(r, env) {
    let origin = await env.ORIGIN_KV.get("origin");
    if (!origin) origin = FALLBACK;
    const u = new URL(r.url);
    const res = await fetch(origin + u.pathname + u.search, r);
    return new Response(res.body, { status: res.status, headers: res.headers });
  },
};
