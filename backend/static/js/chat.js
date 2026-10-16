import { go } from "./nav.js";
import { jobCards } from "./cards.js";
import { resumeCard } from "./resume.js";
import { api } from "./api.js";

const sid = (() => { let v = localStorage.getItem("argus_sid"); if (!v) { v = crypto.randomUUID(); localStorage.setItem("argus_sid", v); } return v; })();
const msgs = document.getElementById("msgs");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const file = document.getElementById("file");
const attach = document.getElementById("attach");
const chip = document.getElementById("chip");
const send = document.getElementById("send");

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
const showReply = (html) => {
  const bubble = document.createElement("div");
  bubble.className = "bubble md";
  bubble.innerHTML = html;
  show(row("them", null, bubble));
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

document.getElementById("chat-back").addEventListener("click", () => go("home"));

// 清空对话上下文。后端历史是内存单例，清掉重启也一样，所以不做二次确认——
// 说错了重来一遍的成本，远低于点一次「确认」的摩擦。清完把气泡也清掉，
// 留一句 Argus 的话，不然界面空得突兀。清空会一并退出简历模式，简历卡也收掉。
document.getElementById("chat-clear").addEventListener("click", async () => {
  try {
    await api("/api/chat/clear", { method: "POST", headers: { "X-Session-Id": sid } });
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
      const res = await api("/api/chat/history", { headers: { "X-Session-Id": sid } });
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
        pendingBubble = null;
        if (bubble) { const md = document.createElement("div"); md.className = "bubble md"; md.innerHTML = data.reply; bubble.replaceWith(md); }
        else { pending?.remove(); showReply(data.reply); }
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
    if (!res.ok) throw new Error((await res.json()).detail || res.status);
    const data = await readStream(res, pending);
    if (!data) throw new Error("连接中断");
    if (data.jobs?.length) show(row("them", null, jobCards(data.jobs)));
    if (data.resume) showResume(data.resume);
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