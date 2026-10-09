const ORIGIN = "https://fda-released-vector-licensing.trycloudflare.com";
export default {
  async fetch(r) {
    const u = new URL(r.url);
    const res = await fetch(ORIGIN + u.pathname + u.search, r);
    return new Response(res.body, { status: res.status, headers: res.headers });
  }
};
