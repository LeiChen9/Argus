import { jobCards } from "./cards.js";
import { resumeCard } from "./resume.js";
import { api, readJson } from "./api.js";

// 当前会话 id 存 localStorage。列表不从这里来——列表是 R2 上真实存在的
// 会话（发过第一条消息才有），这里只记「正在看哪个」。空会话不落 R2。
const storedSid = () => {
  let v = localStorage.getItem("argus_sid");
  if (!v) { v = crypto.randomUUID(); localStorage.setItem("argus_sid", v); }
  return v;
};
let sid = storedSid();
const msgs = document.getElementById("msgs");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const file = document.getElementById("file");
const attach = document.getElementById("attach");
const chip = document.getElementById("chip");
const send = document.getElementById("send");

// ── 会话侧栏 ──
const app = document.querySelector(".app");
const sideList = document.getElementById("side-list");

// ── 一轮的进行状态 ──
// busy：有一轮在跑（决定了发送键是箭头还是方块）。
// awaiting：用户那句话已经发出、**还没等到回答**——只有这个窗口里那条气泡
//          才可以点开改。「AI 已经回答过」就不给改：那种情况要去改会话历史，
//          代价和收益不成比例，用户要改就重新开一轮。
let busy = false;
let awaiting = false;
// 用户是否主动按了停止。用来在收尾时区分「这一轮被取消了」和「它自己答完了」——
// 被取消的那一句仍然该可改（AI 还没回答），答完的就不给了。
let stoppedByUser = false;
let controller = null;
let lastUserNode = null;

const setBusy = (on) => {
  busy = on;
  send.classList.toggle("icon-btn--busy", on);
  send.setAttribute("aria-label", on ? "停止生成" : "发送");
  if (on) controller = new AbortController();
};

const stop = () => {
  controller?.abort();
  stoppedByUser = true;
  // awaiting 保持 true：停下来就等于「AI 还没回答」，那句话仍然该能改。
  setBusy(false);
  markEditable();
  // 「已停止」的记号落在最后一个 Argus 气泡上。模型还在想的时候只有打字气泡，
  // 那就直接收掉——说「已停止」不如什么都不说，反正用户那句话还摆着、能改。
  const lastThem = msgs.querySelector(".msg--them:last-of-type");
  if (lastThem?.querySelector(".typing")) lastThem.remove();
  else if (lastThem) lastThem.classList.add("msg--stopped");
};

// 返回 node：showTyping() 靠它拿回挂载后的节点，之后才能 pending.remove()
const show = (node) => {
  msgs.appendChild(node);
  msgs.scrollTop = msgs.scrollHeight;
  return node;
};

// 流式过程中那个正在长大的气泡：停止时要给它留个「已停止」的记号。
let pendingBubble = null;

const row = (who, text, bubble) => {
  const el = document.createElement("div");
  el.className = `msg msg--${who}`;
  if (who === "them") {
    const avatar = document.createElement("img");
    avatar.className = "avatar";
    avatar.src = "assets/argus-anime.webp";
    avatar.alt = "";
    el.appendChild(avatar);
  }
  bubble ??= document.createElement("p");
  bubble.classList.add("bubble");
  if (text !== null) bubble.textContent = text;
  el.appendChild(bubble);
  return el;
};

// Argus 的回复是后端渲染好的 markdown HTML。div 而非 p：回复里有 h3/ul/hr
// 等块级元素，放进 p 会被浏览器拆散、DOM 结构坏掉。
// 只给这个函数用 innerHTML —— 用户自己的消息和错误文案仍走 row() 的 textContent。
// assistant 回复下的来源模型灰字。挂了才有——加载中的打字气泡不带。
const appendModel = (el, model) => {
  if (!model) return;
  const tag = document.createElement("div");
  tag.className = "msg__model";
  tag.textContent = model;
  el.appendChild(tag);
};

const showReply = (html, model) => {
  const bubble = document.createElement("div");
  bubble.className = "bubble md";
  bubble.innerHTML = html;
  appendModel(show(row("them", null, bubble)), model);
};

// 还没上传过简历时，Argus 先开口。放在页面加载时做：chat 视图此刻是隐藏的，
// 用户切过去时这句话已经在那里了。
const NO_RESUME_GREETING = "你好呀。还没有你的简历，方便的话传一份给我？我想先认识你一下。";

api("/api/persona")
  .then((res) => res.json())
  .then((data) => {
    if (Object.keys(data).length === 0) show(row("them", NO_RESUME_GREETING));
  })
  // 未登录（401）时这条必然失败，不接住的话控制台会挂一条未处理的 rejection。
  // 这条只是开场白，取不到就算了——登录状态由 app.js 的闸门管。
  .catch(() => {});

// 刷新后把整段对话重建出来。会话在 R2（按 sid），刷新只是丢了界面。
// 只重建气泡：简历卡等派生 UI 不回滚，重进 Resume 页自会拉到当前版。
const restoreHistory = async () => {
  try {
    const res = await api("/api/chat/messages", { headers: { "X-Session-Id": sid } });
    const { messages } = await res.json();
    for (const m of messages) {
      if (m.role === "user") show(row("me", m.content));
      else showReply(m.html, m.model);
    }
  } catch {}
};

// 等待 LLM 时 Argus 先"打字"：一个 them 气泡，里面三点跳。
const showTyping = () => {
  const bubble = document.createElement("p");
  bubble.className = "bubble typing";
  bubble.append(...[0, 1, 2].map(() => document.createElement("i")));
  return show(row("them", null, bubble));
};

// 简历卡是**一个槽位**，每轮返回的简历覆盖上一版，不是每轮追加一张新卡。
// 简历是同一份东西的迭代，并排摆一堆只会让人分不清哪版是现在的。
let resumeNode = null;

const showResume = (data) => {
  const card = resumeCard(data);
  if (resumeNode) resumeNode.replaceWith(card);
  else show(card);
  resumeNode = card;
  msgs.scrollTop = msgs.scrollHeight;
};

const clearResume = () => {
  resumeNode?.remove();
  resumeNode = null;
};

// ── 会话侧栏 ──
// 侧栏列的是 R2 上真实存在的会话；空会话（没发过消息）不在这里。当前看哪个由
// localStorage 的 sid 决定，点一条就切过去把历史重建成气泡。
const TRASH_SVG = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">'
  + '<path d="M4.5 7h15M9.5 7V5.6A1.6 1.6 0 0 1 11.1 4h1.8a1.6 1.6 0 0 1 1.6 1.6V7M6.8 7l.7 11.3A2 2 0 0 0 9.5 20.1h5a2 2 0 0 0 2-1.8L17.2 7" '
  + 'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';

const openSide = () => app.classList.add("side-open");
const closeSide = () => app.classList.remove("side-open");
const toggleSide = () => app.classList.toggle("side-open");

const timeAgo = (ts) => {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "刚刚";
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} 天前`;
  return new Date(ts * 1000).toLocaleDateString();
};

const renderSessions = (list) => {
  sideList.replaceChildren();
  if (!list.length) {
    const p = document.createElement("p");
    p.className = "side__empty";
    p.textContent = "还没有对话";
    sideList.appendChild(p);
    return;
  }
  for (const s of list) {
    const item = document.createElement("div");
    item.className = "side__item" + (s.sid === sid ? " is-current" : "");
    item.dataset.sid = s.sid;
    const label = document.createElement("button");
    label.type = "button";
    label.className = "side__label";
    label.textContent = s.title;
    label.title = s.title;
    label.addEventListener("click", () => switchSession(s.sid));
    const time = document.createElement("span");
    time.className = "side__time";
    time.textContent = timeAgo(s.updated_at);
    const del = document.createElement("button");
    del.type = "button";
    del.className = "side__del";
    del.setAttribute("aria-label", "删除会话");
    del.innerHTML = TRASH_SVG;
    del.addEventListener("click", (e) => { e.stopPropagation(); deleteSession(s.sid); });
    item.append(label, time, del);
    sideList.appendChild(item);
  }
};

const loadSessions = async () => {
  try {
    const res = await api("/api/chat/sessions");
    renderSessions((await res.json()).sessions || []);
  } catch {}
};

// 切会话：换 sid、清界面、按新 sid 重建历史。简历卡是派生 UI，一起收掉。
const switchSession = async (next) => {
  if (next !== sid) {
    sid = next;
    localStorage.setItem("argus_sid", sid);
    msgs.replaceChildren();
    lastUserNode = null;
    resumeNode = null;
    closeSide();
    await restoreHistory();
    loadSessions();
  } else {
    closeSide();
  }
};

// 新建会话：只把本地 sid 换成新的，界面上回到空白。R2 要等第一条消息才落。
// 不动列表（列表是 R2 的真实记录，没变化），只把高亮收掉——省一次慢请求。
const resetToBlank = () => {
  sid = crypto.randomUUID();
  localStorage.setItem("argus_sid", sid);
  msgs.replaceChildren();
  lastUserNode = null;
  resumeNode = null;
  awaiting = false;
  stoppedByUser = false;
  for (const el of sideList.querySelectorAll(".side__item.is-current")) el.classList.remove("is-current");
  closeSide();
};

const newSession = resetToBlank;

// ── 删除：乐观移除 + 可撤销 ──
// 点垃圾桶立刻从列表移除（不等后端），真正的 R2 删除延后 UNDO_MS，期间可撤销。
// 这样既有即时反馈、又不误删——后端这个 Worker 每请求都要付 pyodide 冷启动 +
// 全量 _refresh，等它返回再更新界面会像是卡死。
const UNDO_MS = 5000;
const pendingDeletes = new Map();  // sid → { timer, wasCurrent }

const commitDelete = async (target) => {
  try {
    await api("/api/chat/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sid: target }),
    });
  } catch {
    showToast("删除失败，请重试", null);
    loadSessions();  // 后端没删成，把列表拉回来对齐
  }
};

const deleteSession = (target) => {
  const row = sideList.querySelector(`.side__item[data-sid="${CSS.escape(target)}"]`);
  row?.remove();
  const wasCurrent = target === sid;
  if (wasCurrent) resetToBlank();
  const timer = setTimeout(() => { pendingDeletes.delete(target); commitDelete(target); }, UNDO_MS);
  pendingDeletes.set(target, { timer, wasCurrent });
  showToast("已删除", () => undoDelete(target));
};

const undoDelete = async (target) => {
  const info = pendingDeletes.get(target);
  if (!info) return;
  clearTimeout(info.timer);
  pendingDeletes.delete(target);
  hideToast();
  // 删的若是当前会话，删除时已切到空白——撤销要连 sid 和历史一起还回来。
  if (info.wasCurrent) {
    sid = target;
    localStorage.setItem("argus_sid", sid);
    msgs.replaceChildren();
    lastUserNode = null;
    resumeNode = null;
    await restoreHistory();
  }
  loadSessions();  // 把行放回列表（重拉最省事，标题/排序都对）
};

// 底部浮层提示。没有它用户点完删除不知道该不该等——现在秒消失 + 一句反馈。
let toastEl = null;
let toastTimer = 0;
const showToast = (text, onUndo) => {
  if (!toastEl) {
    toastEl = document.createElement("div");
    toastEl.className = "toast";
    document.body.appendChild(toastEl);
  }
  toastEl.replaceChildren();
  const span = document.createElement("span");
  span.textContent = text;
  toastEl.appendChild(span);
  if (onUndo) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "toast__undo";
    btn.textContent = "撤销";
    btn.addEventListener("click", onUndo);
    toastEl.appendChild(btn);
  }
  toastEl.classList.add("toast--show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, UNDO_MS + 400);
};
const hideToast = () => toastEl?.classList.remove("toast--show");

// ── 改自己刚发出去、还没等到回答的那句 ──
// 只给最后一条用户气泡加可点样式：更早的都已经有回答了，改了也没地方生效。
const markEditable = () => {
  if (!lastUserNode) return;
  const bubble = lastUserNode.querySelector(".bubble");
  if (!bubble) return;
  bubble.classList.toggle("bubble--editable", awaiting);
  if (awaiting) {
    bubble.title = "点一下改这句";
    bubble.onclick = () => startEdit(bubble);
  } else {
    bubble.removeAttribute("title");
    bubble.onclick = null;
  }
};

const startEdit = (bubble) => {
  const original = bubble.textContent;
  const box = document.createElement("textarea");
  box.className = "bubble--editbox";
  box.value = original;
  bubble.replaceWith(box);
  box.focus();
  box.setSelectionRange(box.value.length, box.value.length);

  const finish = async (commit) => {
    box.onblur = null;
    const text = box.value.trim();
    // 取消/空内容：当作没改过，把原样放回去
    if (!commit || !text || text === original) {
      const back = document.createElement("p");
      back.className = "bubble";
      back.textContent = original;
      box.replaceWith(back);
      markEditable();
      return;
    }
    const shown = document.createElement("p");
    shown.className = "bubble";
    shown.textContent = text;
    box.replaceWith(shown);
    // 重发前先撤掉服务端那一轮：连接虽然被掐了，Worker 往往照跑完存了盘，
    // 不撤的话会话里会留下「原句 + 完整回答 + 改后这句 + 新回答」四条自相矛盾的记录。
    try {
      await api("/api/chat/undo", { method: "POST", headers: { "X-Session-Id": sid } });
    } catch {}
    lastUserNode = shown.parentElement;
    awaiting = true;
    markEditable();
    await sendMessage(text);
  };

  box.onblur = () => finish(false);
  box.onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); finish(true); }
    if (e.key === "Escape") { e.preventDefault(); finish(false); }
  };
};

// 回首页交给顶部那个固定 logo（它压在所有页面上），聊天头部不再自带返回箭头。

// 侧栏开关。新建会话 = topbar 右上那颗加号；垃圾桶在每条会话行里，删除不确认。
document.getElementById("chat-new").addEventListener("click", newSession);
document.getElementById("chat-menu").addEventListener("click", toggleSide);
document.getElementById("side-close").addEventListener("click", closeSide);
document.getElementById("scrim").addEventListener("click", closeSide);

input.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey) return;
  event.preventDefault();
  form.requestSubmit();
});

// 先 auto 再读 scrollHeight：不置 auto 只能越打越高，收不回来。
const fit = () => {
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
};
input.addEventListener("input", fit);

// 请求被掐掉（切走 App、运营商断流）时，后端那一轮往往已经算完存盘了，丢的只是
// 送达。先把刚算完的那轮取回来，用户看到的还是答案而不是一句 Load failed。
// 要 user 原文对得上才认，否则捞到的是上一轮，宁可不显示。
// 重试窗口按最坏情况给足：实测跑满一轮要 90 秒以上，窗口短了等于没捞。
const recoverReply = async (sent) => {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await api("/api/chat/history", { headers: { "X-Session-Id": sid } });
      const t = (await res.json()).turn;
      if (t && t.user === sent && t.reply) { showReply(t.reply, t.model); return true; }
    } catch {}
    await new Promise((r) => setTimeout(r, 2000));
  }
  return false;
};

// 流式读 SSE。fetch 没有 EventSource 的便利（它只支持 GET），这里手工切帧。
// 帧之间用空行分隔；以 : 开头的是心跳注释行，直接跳过。
// 遇到 content: 事件即刻渲染到页面，遇到 reply: 事件即渲染为最终版并清掉内容块。
const readStream = async (res, pending) => {
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let bubble = null;
  let raw = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let cut;
    while ((cut = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      const ev = frame.match(/^event: (.+)$/m)?.[1];
      if (!ev) continue;
      const data = JSON.parse(frame.match(/^data: (.*)$/m)?.[1] ?? "{}");
      if (ev === "error") { const e = new Error(data.detail); e.fromServer = true; throw e; }
      if (ev === "content") {
        if (!bubble) {
          pending?.remove();
          bubble = document.createElement("p");
          bubble.className = "bubble";
          pendingBubble = show(row("them", null, bubble));
        }
        raw += data.content;
        bubble.textContent = raw;
        msgs.scrollTop = msgs.scrollHeight;
      } else if (ev === "reply") {
        const rowEl = pendingBubble;
        pendingBubble = null;
        if (bubble) {
          const md = document.createElement("div");
          md.className = "bubble md";
          md.innerHTML = data.reply;
          bubble.replaceWith(md);
          appendModel(rowEl, data.model);
        } else { pending?.remove(); showReply(data.reply, data.model); }
        return data;
      }
    }
  }
  return null;
};

// 发一轮。抽成函数是因为「改完重发」要复用同一条路径——两条路径各自维护
// busy/awaiting 的话，迟早会漏掉一处状态。
const sendMessage = async (message) => {
  stoppedByUser = false;
  const node = row("me", message);
  lastUserNode = show(node);
  awaiting = true;
  markEditable();

  setBusy(true);
  const pending = showTyping();
  try {
    const res = await api("/api/chat/stream", {
      method: "POST",
      signal: controller.signal,
      headers: { "Content-Type": "application/json", "X-Session-Id": sid },
      body: JSON.stringify({ message }),
    });
    if (!res.ok) throw new Error((await readJson(res)).detail || res.status);
    const data = await readStream(res, pending);
    if (!data) throw new Error("连接中断");
    if (data.jobs?.length) show(row("them", null, jobCards(data.jobs)));
    if (data.resume) showResume(data.resume);
    loadSessions();  // 会话可能刚落 R2（首轮），刷新标题与时间
  } catch (err) {
    // 用户主动停止不算错误：一个 AbortError 直接静默，气泡上已经标了「已停止」。
    if (err.name === "AbortError") return;
    // 后端明确报错（如所有模型不可用）时它根本没存盘，轮询 2 分钟纯属白等，直接显示。
    // 只有连接被掐（无 error 事件）才去捞，捞不回来才报原始错误，别把真错误盖掉。
    if (err.fromServer || !(await recoverReply(message))) show(row("them", `我说不了话：${err.message}`));
  } finally {
    pending.remove();
    if (busy) setBusy(false);
    // 主动停掉的：awaiting 留着，用户那句话还能改；自己答完的：收回可编辑。
    if (!stoppedByUser) awaiting = false;
    markEditable();
  }
};

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) { stop(); return; }   // 方块状态下这颗按钮是「停止」，不是「发送」

  const picked = file.files[0];
  const message = input.value.trim();
  // 有文件时：走简历上传解析，无视输入框文字
  if (picked) {
    show(row("me", `上传简历：${picked.name}`));
    file.value = "";
    chip.hidden = true;
    const pending = showTyping();
    const body = new FormData();
    body.append("file", picked);
    try {
      const res = await api("/api/persona/init", { method: "POST", body });
      const data = await readJson(res);
      if (!res.ok) {
        show(row("them", `解析失败：${data.detail || res.status}`));
        return;
      }
      const n_work = data.work_history?.length ?? 0;
      const n_skill = data.skills?.length ?? 0;
      const n_edu = data.education?.length ?? 0;
      show(row("them", `解析完成：${n_work} 段经历，${n_skill} 项技能，${n_edu} 段教育`));
    } catch (err) {
      show(row("them", `解析失败：${err.message}`));
    } finally {
      pending.remove();
    }
    return;
  }
  if (!message) return;
  input.value = "";
  fit();
  await sendMessage(message);
});

attach.addEventListener("click", () => file.click());

file.addEventListener("change", () => {
  const picked = file.files[0];
  chip.textContent = picked ? `待解析：${picked.name}` : "";
  chip.hidden = !picked;
});

// 进站初始化：拉会话列表，再把当前 sid 的历史重建成气泡。侧栏默认开合由
// nav.js 按视图管（桌面进 chat 默认展开、手机默认收起）。
loadSessions();
restoreHistory();