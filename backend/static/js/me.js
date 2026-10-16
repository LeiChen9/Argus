// me.js —— Me 页：登录 / 注册 / 账号信息 / token 用量。
//
// 数据隔离的可见面就这一页：登录前谁都进不来（Worker 那边 401），登录后看到
// 「我是谁」和「我烧了多少 token」。用量是 Worker 每轮对话结束时累加进
// <用户>/usage.json 的，前端只读不算。

import { api, apiJson, setAccessCode } from "./api.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
};

const root = () => document.getElementById("me-body");

const fmt = (n) => {
  n = Number(n) || 0;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
};

function renderLogin(message) {
  const box = root();
  box.replaceChildren();

  const form = el("form", "meform");
  const user = el("input", "meform__input");
  user.name = "username"; user.placeholder = "用户名"; user.autocomplete = "username";
  user.required = true; user.maxLength = 24;
  const pass = el("input", "meform__input");
  pass.name = "password"; pass.type = "password"; pass.placeholder = "密码";
  pass.autocomplete = "current-password"; pass.required = true;

  const note = el("p", "meform__note", message || "");
  form.append(user, pass);

  // 访问码不对时补一个输入框：之前只能靠 ?code= 打开网址带进来，用裸网址进来
  // 的人（收藏夹、手输）就被挡在门外，且看不出到底缺了什么。
  if (message === "access code 不对") {
    const code = el("input", "meform__input");
    code.type = "password"; code.placeholder = "访问码";
    code.autocomplete = "off";
    form.append(code);
    note.textContent = "先填访问码，它会存在这台设备上，以后不用再填";
    const submit = el("button", "meform__btn", "用这个访问码再试一次");
    submit.type = "submit";
    form.append(submit);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      setAccessCode(code.value.trim());
      renderLogin("");
      loadMe();
    });
    box.append(form);
    code.focus();
    return;
  }

  const submit = el("button", "meform__btn", "登录");
  submit.type = "submit";
  form.append(submit, note);

  const send = async (path, body) => {
    note.textContent = "…";
    try {
      await api(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      note.textContent = "";
      await loadMe();
    } catch (e) {
      note.textContent = e.detail || e.message || "登录失败";
    }
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    send("/api/auth/login", { username: user.value.trim(), password: pass.value });
  });

  let registering = false;
  swap.addEventListener("click", () => {
    registering = !registering;
    submit.textContent = registering ? "注册并登录" : "登录";
    swap.textContent = registering ? "已有账号？登录" : "没有账号？注册";
    note.textContent = registering ? "注册后会带你那一份职位库，简历和个人资料要自己上传" : "";
  });

  box.append(form, swap);
  user.focus();
}

function renderProfile(data) {
  const box = root();
  box.replaceChildren();

  const card = el("div", "mecard");
  card.append(el("div", "mecard__name", data.me.user));
  card.append(el("div", "mecard__sub", "数据都存在你自己的命名空间里，别人看不到"));
  box.append(card);

  const rows = Object.entries(data.usage || {}).sort((a, b) => (b[1].input + b[1].output) - (a[1].input + a[1].output));
  const section = el("div", "meusage");
  section.append(el("div", "meusage__title", "token 用量"));
  if (!rows.length) {
    section.append(el("p", "meusage__empty", "还没有记账，聊一轮就有了"));
  } else {
    for (const [model, u] of rows) {
      const row = el("div", "meusage__row");
      row.append(el("span", "meusage__model", model));
      const nums = el("span", "meusage__nums");
      nums.append(el("span", null, `输入 ${fmt(u.input)}`));
      nums.append(el("span", null, `输出 ${fmt(u.output)}`));
      nums.append(el("span", null, `${u.calls} 次`));
      row.append(nums);
      section.append(row);
    }
    section.append(el("p", "meusage__note",
      "输入是估算值（provider 没回 usage 就按 token 数算），输出按正文字数折。够看个大概。"));
  }
  box.append(section);

  const out = el("button", "meform__alt", "退出登录");
  out.addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" });
    renderLogin("已退出");
    onAuth(false);
  });
  box.append(out);

  box.append(selfCheck());
}

// 自检：把三个页面的接口逐个打一遍，把状态和条数写在屏幕上。
//
// 为什么要有它：页面取数失败过一次是「静默空白」——jobs.js 没有 catch，resume/
// career 显示一句「后端可能没重启」，而真实原因可能是访问码过期、cookie 掉了、
// 或者真的 500，三种病三种药。没有这一屏就只能在浏览器控制台里猜。
async function selfCheck() {
  const wrap = el("div", "meusage");
  wrap.append(el("div", "meusage__title", "数据自检"));
  const targets = [["/api/careers", "careers"], ["/api/jobs", "jobs"], ["/api/resumes", "resumes"]];
  for (const [path, name] of targets) {
    const line = el("div", "meusage__row");
    line.append(el("span", "meusage__model", name));
    line.append(el("span", "meusage__nums", "…"));
    wrap.append(line);
    api(path).then(async (res) => {
      const body = await res.text();
      let detail = "";
      try {
        const doc = JSON.parse(body);
        const count = doc.careers?.length ?? Object.keys(doc.jobs || {}).length ?? (doc.resumes?.length ?? "-");
        detail = res.ok ? `${count} 条` : `HTTP ${res.status}`;
      } catch { detail = `HTTP ${res.status}`; }
      line.lastChild.textContent = `${detail}（${res.status}）`;
    }).catch((e) => {
      line.lastChild.textContent = `失败：${e.detail || e.message}`;
    });
  }
  return wrap;
}

// 登录状态变了就通知外面（app.js 拿它开关 tabbar）——登录成功后 tabbar 要回来。
let onAuth = () => {};
export const onAuthChange = (fn) => { onAuth = fn; };

export async function loadMe() {
  try {
    const data = await apiJson("/api/me");
    renderProfile(data);
    onAuth(true);
  } catch (e) {
    renderLogin(e.status === 401 ? "" : (e.detail || e.message));
    onAuth(false);
  }
  return root();
}

// 未登录时把用户送到 Me 页（app.js 的 tabbar 闸门用）
export async function ensureLogin() {
  try {
    return await apiJson("/api/me");
  } catch {
    return null;
  }
}