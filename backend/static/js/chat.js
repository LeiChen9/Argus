import { go } from "./nav.js";
import { jobCards } from "./cards.js";
import { resumeCard } from "./resume.js";

const sid = (() => { let v = localStorage.getItem("argus_sid"); if (!v) { v = crypto.randomUUID(); localStorage.setItem("argus_sid", v); } return v; })();
const msgs = document.getElementById("msgs");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const file = document.getElementById("file");
const attach = document.getElementById("attach");
const chip = document.getElementById("chip");

// 返回 node：showTyping() 靠它拿回挂载后的节点，之后才能 pending.remove()
const show = (node) => {
  msgs.appendChild(node);
  msgs.scrollTop = msgs.scrollHeight;
  return node;
};

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
const showReply = (html) => {
  const bubble = document.createElement("div");
  bubble.className = "bubble md";
  bubble.innerHTML = html;
  show(row("them", null, bubble));
};

// 还没上传过简历时，Argus 先开口。放在页面加载时做：chat 视图此刻是隐藏的，
// 用户切过去时这句话已经在那里了。
const NO_RESUME_GREETING = "你好呀。还没有你的简历，方便的话传一份给我？我想先认识你一下。";

fetch("/api/persona")
  .then((res) => res.json())
  .then((data) => {
    if (Object.keys(data).length === 0) show(row("them", NO_RESUME_GREETING));
  });

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

document.getElementById("chat-back").addEventListener("click", () => go("home"));

// 清空对话上下文。后端历史是内存单例，清掉重启也一样，所以不做二次确认——
// 说错了重来一遍的成本，远低于点一次「确认」的摩擦。清完把气泡也清掉，
// 留一句 Argus 的话，不然界面空得突兀。清空会一并退出简历模式，简历卡也收掉。
document.getElementById("chat-clear").addEventListener("click", async () => {
  try {
    await fetch("/api/chat/clear", { method: "POST", headers: { "X-Session-Id": sid } });
  } catch (err) {
    show(row("them", `没清成功：${err.message}`));
    return;
  }
  msgs.replaceChildren(row("them", "好，我们重新聊。"));
  clearResume();
});

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
      const res = await fetch("/api/chat/history", { headers: { "X-Session-Id": sid } });
      const t = (await res.json()).turn;
      if (t && t.user === sent && t.reply) { showReply(t.reply); return true; }
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
      if (ev === "error") throw new Error(data.detail);
      if (ev === "content") {
        if (!bubble) { pending?.remove(); bubble = document.createElement("p"); bubble.className = "bubble"; show(row("them", null, bubble)); }
        raw += data.content;
        bubble.textContent = raw;
        msgs.scrollTop = msgs.scrollHeight;
      } else if (ev === "reply") {
        if (bubble) { const md = document.createElement("div"); md.className = "bubble md"; md.innerHTML = data.reply; bubble.replaceWith(md); }
        else { pending?.remove(); showReply(data.reply); }
        return data;
      }
    }
  }
  return null;
};

form.addEventListener("submit", async (event) => {
  event.preventDefault();
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
      const res = await fetch("/api/persona/init", { method: "POST", body });
      const data = await res.json();
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
  show(row("me", message));
  input.value = "";
  fit();
  const pending = showTyping();
  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Id": sid },
      body: JSON.stringify({ message }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.status);
    const data = await readStream(res, pending);
    if (!data) throw new Error("连接中断");
    if (data.jobs?.length) show(row("them", null, jobCards(data.jobs)));
    if (data.resume) showResume(data.resume);
  } catch (err) {
    // 捞不回来才报原始错误，别把真错误盖掉。
    if (!(await recoverReply(message))) show(row("them", `我说不了话：${err.message}`));
  } finally {
    pending.remove();
  }
});

attach.addEventListener("click", () => file.click());

file.addEventListener("change", () => {
  const picked = file.files[0];
  chip.textContent = picked ? `待解析：${picked.name}` : "";
  chip.hidden = !picked;
});