import { go } from "./nav.js";
import { jobCards } from "./cards.js";

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

document.getElementById("chat-back").addEventListener("click", () => go("home"));

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
  const pending = showTyping();
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await res.json();
    if (!res.ok) {
      show(row("them", `我说不了话：${data.detail || res.status}`));
      return;
    }
    showReply(data.reply);
    if (data.jobs?.length) show(row("them", null, jobCards(data.jobs)));
  } catch (err) {
    show(row("them", `我说不了话：${err.message}`));
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