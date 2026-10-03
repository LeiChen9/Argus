# Argus — Dev Log

倒序追加。一次 session 一个条目。技术选型不要写这里，去 `tech_doc.md`。

---

## 2026-10-03 — Session 1: 前后端链路打通

**做了什么**

读 README 确认目标（Argus = AI-native career copilot，MVP Phase 1 = Persona / Job
Intelligence / Gap Analysis / Career Plan / Interview Prep）。用户选择「先只验证链路」，
所以本 session 不碰 Persona 逻辑。

- `backend/main.py` — FastAPI app + `POST /api/echo` + mount `static` 到 `/`
- `backend/static/index.html` — input + button + fetch，够点通即可
- `tech_doc.md` / `dev_log.md` — 建立

**验证结果**

```
POST localhost:8010/api/echo  {"message":"ping"} -> {"echo":"ping"}
GET  localhost:8010/          -> HTTP 200
GET  localhost:8010/docs      -> HTTP 200
```

**踩的坑**

1. **`localhost:8000` 被别人的进程劫持。** 首次 curl 拿到 `501 Unsupported method`，
   来自一个遗留的 `python -m http.server 8000`（PID 76215，listen 在 IPv6 `*:8000`）。
   它抢在 uvicorn（只 listen `127.0.0.1`）前面被解析到。改用 **8010** 解决。
   该进程不是本次 session 起的，**未 kill**，留给用户决定。
2. `StaticFiles` mount `/` 必须写在 API 路由之后，否则遮蔽 `/api/*`。

**下个 session 从哪继续**

前后端链路与交互形状已完成（见下方补记 2）。**建表仍推迟：schema 未定，不在数据形状
定下来前建表。** `.env` 的智谱 key 目前完全未被使用——下一步应先定 Persona 数据形状，
再决定先接 LLM 抽取还是先建表。

---

## 2026-10-03 — Session 1 补记：类重命名 + Storage 决策

**`Echo` → `EchoRequest`**（`backend/main.py:10,15`）。`Echo` 与 conda env `echo`
撞名会误导。路由 `/api/echo`、函数名 `echo`、响应键 `echo` 保持不变——纯重命名，
零行为变化，`/docs` schema 名已确认变成 `EchoRequest`。

**Storage 决策：裸 stdlib `sqlite3`，不上 ORM。** 用户选定。理由见 `tech_doc.md`。

**流程教训：我给SQLite 的理由太薄，且漏写了它的隐藏条款。**
当时只写"Postgres 要起服务"，没说清真正含义是"这决定了要不要上 ORM"。
用户追问「为啥要 SQLite」才暴露出：换库成本完全取决于第0 天怎么写 SQL。
**教训：给技术选型写理由时，必须连带写出它的代价和触发条件，
否则用户批准的是一个自己没看清的选项。** 已补进 `tech_doc.md` 的「Storage 已知债务」。

---

## 2026-10-03 — Session 1 补记 2：换成真实 Argus 交互形状（Slice 3）

**做了什么**

建表被用户砍掉——「现在还没定要存什么样的数据」。改为把 echo 占位换成真实交互形状，
**零存储、零 LLM 调用**：

- `POST /api/chat`（`backend/main.py:24`）— canned 回声，`ChatRequest` 校验 422 仍在
- `GET /api/persona`（`backend/main.py:31`）— 返回 `PERSONA_MOCK`
- `backend/static/index.html` — 左侧聊天气泡流 + 右侧 persona 面板
- `POST /api/echo` 已移除（现在返回 405）

**验证**
```
POST /api/chat {"message":"我在字节做过三年数据分析师"} -> {"reply":"收到：..."}
POST /api/chat {}   -> 422 missing
GET  /api/persona   -> 11 fields
GET  /             -> 200        POST /api/echo -> 405
```

**`PERSONA_MOCK` 的 11 个字段是 UI mock，不是 schema 决定。**
抄自 README 的 Persona 分类（experience/skills/knowledge/projects/domain_expertise/
communication/career_preferences/strengths/weaknesses/evidence/goals），全部空值。
页面上标了「schema 未定稿」。**要改就改 `backend/main.py:9` 一个 dict。
别在没讨论过的情况下照它建表。**

**做过头的地方**：我在提议里说"不碰 schema"，但写下 11 个字段本身已经是在预设立场。
用户批准的是 UI mock，所以我把它标成未定稿来对冲——但这是我自己造成的张力，记下来。

**依赖现状**：没有 `requirements.txt`（用户决定先不做）。依赖全靠 `echo` env裸奔，
换机器/重建 env 会断。
---

## 2026-10-03 — Session 1 补记 3：首页移植自 FluentChat（Slice 4）

**做了什么**

把 FluentChat 的设计系统搬过来，只做首页（NPC + 招呼语）。

- `css/app.css` — 268 行，从上游 317 行移植，**除注释外逐字节相同**
- `js/greeting.js` — `cp` 上游文件，逐字节相同
- `js/app.js` — 上游删掉 `initUnits` 两行（不抄 `live.js`）
- `index.html` — 3 tab 改 chat/jobs/me，Jobs/Me 用上游现成 `.placeholder`
- `assets/argus-anime.jpeg` — 源图，从仓库根目录移入
- `assets/argus-anime.webp` — 生成，带 alpha

**验证**
```
/                 200 text/html 3088B
css/app.css       200 text/css 5806B
js/app.js         200 text/javascript 810B
js/greeting.js    200 text/javascript 2028B
assets/…webp      200 image/webp 51078B  RGBA, alpha 0-255, 45% 透明
POST /api/chat    {"reply":"收到：hi"}    ← 静态 mount 未遮蔽 API
```

**抠图方法（已写进 tech_doc，别再用错方法）**

PIL 的 `ImageDraw.floodfill` **不可靠**：实测 thresh=8 下把中心像素 (250,237,221)
也填掉，蓝通道差 34 本该拦住，整图被吞光（背景判定 100%，webp 只剩 2KB）。
改用 scipy 连通域：判白 `min(RGB)>=246` → `ndi.label` → **只保留触边连通域**。
结果：45.0% 抠掉，触边连通域 1 个，内部白斑 12 个**正确保留**，
实体内部（腐蚀 4px）**破洞 0 个**。

**我看不到图，怎么确认抠对了**：ASCII 打alpha 轮廓 + 明暗，肉眼读出两只耳朵、
圆润身体、右侧尾巴、底部地面阴影 —— 与用户描述的"宝可梦小狗蹲坐"一致。
这是代替肉眼看图的替代手段。

**关于"我看不到图"这件事本身**：用户以为我看到了 NPC 并给了设计意见。
实际上模型不支持图像输入，我全程靠 PIL 测量 + ASCII 轮廓工作。
**这个局限必须让用户知道，不能默认自己"看过了"。**

**没做**：Chat 视图的对话气泡/persona 面板（用户说先不管）、Jobs 岗位聚类卡片
（`.unit*` 样式已从 CSS 删除，做 Jobs 时从上游再拿）、Me 页。
`main.py` 一行没动，`/api/*` 全部保留但首页不调用。

**待定**：`--accent` 仍是 FluentChat 的 `#5e5ce6` 紫，Argus 品牌色未定。

---

## 2026-10-03 — Session 1 补记 4：Chat 视图（Slice 5）

**做了什么**

- `index.html` — `#view-chat` 重构：hero(空状态) + `.msgs` + `.composer`
  （上传按钮 / 输入框 / 发送），去掉该 view 上的 `view--center`
- `css/app.css` — +130 行，全新：`.chat` `.msgs` `.msg` `.bubble` `.avatar`
  `.composer*` `.icon-btn` + `bubbleIn` 入场动画 + 两个新 token
- `js/chat.js` — 新模块：气泡渲染、调 `/api/chat`、首条后收 hero、文件名 chip
- `js/app.js` — +1 行 `import "./chat.js"`

**验证**
```
/  css/app.css  js/app.js  js/chat.js   全部 200
POST /api/chat  ->  {"reply":"收到：我在字节做过三年数据分析师"}
死代码扫描: CSS 未引用 class 无 / 引用但未定义 无 / 未用变量 无 / id 双向匹配 无
```

**FluentChat 这次没什么可抄的**：它是语音应用，`bubble|msg|composer|avatar|header`
在 css/js/html 里命中 **0**。能抄的只有 token、`.view` 入场动画、`.tabbar`。
所以这片 CSS 是新写的，上一片那种"逐字节移植"不适用——**别再默认能抄**。

**头像不做人脸裁切**：NPC 源图 1024×1024，**脸在哪个位置我不知道**（读不了图）。
从 alpha 轮廓只能测出耳朵在 y≈73-184。选方形圆角显示完整角色，零猜测。
若要圆形裁脸，需先拿到脸的坐标。

**发现并修掉一个我自己写错的数字**：CSS 注释里写暗色气泡"~6.5:1"，
实算是 **5.97:1**。注释里的错数字比没注释更糟，已改。

**为什么 `--bubble-me` 要和 `--accent` 分开**：暗色 `--accent: #7d7aff` 配白字
只有 **3.44:1**，不过 WCAG AA。实测后单独压深到 `#514ee0`(5.97:1)。
对比度是算出来的，不是估的。

**扫描里两个假警报**（记下来免得下次又被绊）：
- `msg--me` / `msg--them` 被报"CSS 未引用"——实际由 `chat.js:11` 的
  模板字符串 `` `msg msg--${who}` `` 运行时生成，正则看不穿模板
- `view-chat/jobs/me` 被报"JS 未用"——实际由 `app.js:24` 的 `dataset.view` 动态取

**真死代码 1 处**：`index.html` 的 `id="send"` 没有任何 JS 引用（按钮靠
`type="submit"` 触发表单处理器，不需要 id）。**故意留着**，将来做浏览器自动化测试
要当选择器。8 个字符，不值得为洁癖删掉。

**后端零改动**。`/api/persona` 和 `PERSONA_MOCK` 现在前端一处都不调——
Persona 更新逻辑尚未设计，这是下一件事。

---

## 2026-10-03 — Session 1 补记 5：首页/Chat 分离 + 修一个真 bug

**首页与 Chat 拆成两个 view**

顶部加全局 `.topbar`，纯文字 "Argus" 标识是**回首页的唯一入口**。
首页 `#view-home`（hero）不再和 Chat 共用。Chat 页 `.topbar` 换成 `.chat__head`
（返回键 + Argus 头像 + 名字），`.tabbar` 隐藏、composer 顶替。
新增 `js/nav.js` 的 `go(name)` 统一切页 —— 原来 tab 循环假设"每个 view 对应一个 tab"，
首页（无 tab）和 Chat（无 tab 且要藏 tabbar）都打破了这个假设。
`app.js` 和 `chat.js` 从 `nav.js` import，不走循环依赖。

**BUG：Chat 页回车会跳回首页**

根因：Slice 6 重写 `app.js` 时**漏掉了 `import "./chat.js"`**，chat.js 从未被浏览器下载。
后果链条：
```
chat.js 未加载 → 无 submit 监听 → 回车触发原生表单提交
→ <form> 无 action，提交到当前 URL → 页面重新加载
→ 默认激活 #view-home → 看起来像"回车送我回首页"
```
同时被弄死：返回键、`+` 上传、文件名 chip。

**为什么我的检查没抓到**：我验的三件事（DOM 目标存在、`go()` 指向真实 view、
死代码双向匹配）**没有一条检查"文件会不会真的被下载"**。
文件在磁盘上、代码看起来完全合理，但不在模块图里。

**我的检查脚本自己也是瞎的**（第二层 bug）：它只匹配 `from "..."`，
看不见 `import "./chat.js"` 这种**裸副作用导入**。修好正则才真正验到。
**教训：模块图可达性要同时匹配 `from "..."` 和 `import "..."`。**
已写进 `tech_doc.md` 的「约定」。

**顺手清的死代码**：`.msgs[hidden]`（msgs 不再被隐藏，hero 收起逻辑已删）；
`id="send"` 上一轮就确认无引用、故意留作测试选择器。

**端口改为 7800**：本机另一个程序也在跑 localhost 测试（7000 已被占，PID 570）。
代码里没有硬编码端口，只改了 `tech_doc.md` 的 Run 一节。8010 已释放。

**仍然验不了的**：没有浏览器，渲染、滚动、tap 手感全靠读代码推。
导航矩阵是推演出来的，不是跑出来的。

---

## 2026-10-03 — Session 1 补记 6：品牌色改暖色（奶油 + 摩卡棕）

用户选定「温暖一点」。靛紫 `#5e5ce6` 全废弃，改暖色体系。
实现在 `css/app.css` 的 token 块，明细已进 `tech_doc.md`。

**关键约束：单一暖色无法同时在亮底和暗底过 AA。** 实测：

| 候选 | 亮底 #fbfbfd | 暗底 #000 | vs NPC奶油 |
|---|---|---|---|
| 奶油 #F5E6D3 | **1.19** | 17.14 | **1.03** |
| 浅棕 #D2B48C | **1.91** | 10.65 | 1.57 |
| 焦糖 #C68E5D | 2.74 | 7.43 | 2.25 |
| 摩卡 #8B6F47 | 4.55 ✓ | 4.46 | 3.75 |
| 可可 #6F5545 | 6.64 ✓ | 3.06 | 5.46 |

所以 `--accent` 分两档：亮色 `#8b6f47`、暗色 `#d2b48c`。

**顺带修掉两个既有缺陷**（都是我自己上轮埋的）：
1. **暗色模式从来没做对比度适配。** 靛紫暗底只有 4.15:1，不达标——
   上轮我只算了亮色就宣布做完了。这次两个模式都算。
2. **有硬编码的品牌色。** `app.css` 里 NPC 的暗色辉光写死 `rgba(125,122,255,.34)`
   （纯靛紫），改 token 它不会变。已提成 `--npc-shadow`，
   顺带**删掉一条暗色覆盖规则**——两模式只切一个 token。

**奶油色不能当图标色**：NPC 身体实测就是奶油（min-channel 200-243），
奶油压亮底 1.19:1、压 NPC 1.03:1，两头都糊。奶油只做底色（气泡/光晕）。

**`--on-accent` 与 `--on-bubble` 不能合并**：send 按钮是「accent 底 + 白字」，
气泡是「奶油底 + 深墨字」。合并必然有一个不达标。

**验证**：CSS 里已无硬编码颜色（只剩注释中的色号说明）；
靛紫/冷灰残留 grep 0 命中；死代码扫描 6 项干净（老两个假警报照旧）；
服务的 CSS 与磁盘 diff 一致。

**仍然验不了的**：配色实际观感。全部对比度是算的，但"看起来暖不暖"只能你判断。

**操作坑：后台起服务必须 `disown`。**
`nohup uvicorn ... &` 起的进程会随 bash 工具调用的 shell 结束而被连带杀掉
（日志里表现为 `Shutting down` / `Finished server process`）。
后果是我在同一次调用里 curl 验证全绿，但用户点链接时服务已经没了——
**验证通过 ≠ 用户能访问**。正确写法：

```bash
source activate echo && nohup uvicorn main:app --app-dir backend --port 7800 \
  > /tmp/argus-uvicorn.log 2>&1 & disown
```

`disown` 后要**另开一次工具调用**复查进程还在，才算真的起来了。
