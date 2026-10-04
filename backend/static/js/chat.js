import { go } from "./nav.js";

const msgs = document.getElementById("msgs");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const file = document.getElementById("file");
const attach = document.getElementById("attach");
const chip = document.getElementById("chip");

const row = (who, text) => {
  const el = document.createElement("div");
  el.className = `msg msg--${who}`;
  if (who === "them") {
    const avatar = document.createElement("img");
    avatar.className = "avatar";
    avatar.src = "assets/argus-anime.webp";
    avatar.alt = "";
    el.appendChild(avatar);
  }
  const bubble = document.createElement("p");
  bubble.className = "bubble";
  bubble.textContent = text;
  el.appendChild(bubble);
  return el;
};

const show = (node) => {
  msgs.appendChild(node);
  msgs.scrollTop = msgs.scrollHeight;
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
    show(row("them", "简历解析中…"));
    const form = new FormData();
    form.append("file", picked);
    const res = await fetch("/api/persona/init", { method: "POST", body: form });
    const data = await res.json();
    msgs.lastChild.remove();
    if (!res.ok) {
      show(row("them", `解析失败：${data.detail || res.status}`));
      return;
    }
    const n_work = data.work_history?.length ?? 0;
    const n_skill = data.skills?.length ?? 0;
    const n_edu = data.education?.length ?? 0;
    show(row("them", `解析完成：${n_work} 段经历，${n_skill} 项技能，${n_edu} 段教育`));
    return;
  }
  if (!message) return;
  show(row("me", message));
  input.value = "";
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  show(row("them", (await res.json()).reply));
});

attach.addEventListener("click", () => file.click());

file.addEventListener("change", () => {
  const picked = file.files[0];
  chip.textContent = picked ? `待解析：${picked.name}` : "";
  chip.hidden = !picked;
});