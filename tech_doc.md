# Argus — Tech Doc

已达成共识的技术选型。**只记已确定的选择和决策理由**，不记实现细节、不记待办。
进度与踩坑记录写 `dev_log.md`。

Last updated: 2026-10-09

---

## Environment

| 项 | 值 | 备注 |
|---|---|---|
| Conda env | **`echo`** | 所有 Python 命令前加 `source activate echo` |
| Python | 3.10.20 | echo env 自带版本 |
| 机器 | macOS (darwin) | zsh |
| 已装关键包 | fastapi 0.115.6 / uvicorn 0.30.0 / pydantic 2.7 / httpx 0.28 | 切片 1 阶段**不建 requirements.txt**，够用即可 |

## Stack

| 层 | 选型 | 决策理由 |
|---|---|---|
| Runtime | **Cloudflare Python Worker**（pyodide）+ Workers Static Assets | 2026-10-16 从本机 FastAPI 迁来：线上负载只是 chat + 读，不需要常驻本机。入口见「部署」。 |
| Backend | **Python（核心逻辑不换语言）** | 用户指定 Python（熟悉）。FastAPI/uvicorn 已退役——pyodide 装不了，路由层是手写分发（`entrypoint_worker.py`）。 |
| Frontend | **静态 HTML + 原生 JS** | 无构建步骤、无 node 工具链进应用路径。Workers Assets 原样托管，SPA 回退。 |
| Storage | **R2（线上）+ data/ 镜像（本地）**，无 DB、无 ORM | 单用户。key 布局见「部署」；离线脚本与 Worker 跑同一份领域代码，`store_active()` 切双模式。 |
| LLM Provider | 多家 OpenAI 兼容端点，双传输 | 离线 openai SDK / Worker `js.fetch`（pyodide 装不了 SDK）。key 在 Worker secret（线上）/ `.env`（离线）。免费模型优先、付费兜底。 |

### LLM 容灾链

`common.MODEL_CHAIN` 是一个有序列表，`_run_chain` 逐个试，第一个成功的即返回。
链首免费、付费在后兜底：`agnes-3.0-flash` → Groq 的 `gpt-oss-120b` / `gpt-oss-20b` /
`qwen3.8-27b` → `gemini-3.5-flash` → `deepseek-v4-flash`。
`active_chain` 还会把不在开放时段的 DeepSeek 剔掉（峰段按北京时间，显式 UTC+8）。
chat（带工具的主 agent）只走 `CHAT_ENDPOINTS = {gemini, agnes, groq, deepseek}`，
由 `_run_chain` 的 `allow_endpoints` 过滤。

几个免费端点实测出来的坑：

- **Groq 的 context 与额度是两回事**：模型 context window 是 128K（`/v1/models`
  实测 `131072`），但免费档 TPM 只有 8K——**单条请求总 token 超 8K 直接 413**，
  跟窗口无关。故链上给 groq 三条设 `max_input_tokens=7000` 提前跳过（token 估算
  是字符启发式：中文偏保守，重复 ASCII 会低估）。Groq 从 Cloudflare 边缘可达
  （中国 IP 直连的 403 在 Worker 上消失），离线脚本仍要走系统代理。
- **Gemini 3 的 thought_signature**：多轮工具调用必须把上轮 tool_calls 的
  `extra_content` 原样带回，否则 400。chat.answer 里因此直接透传 dict；中途换模型
  会把别的模型产出的 tool_calls 带过去，是已知边界。
- **agnes 会 429**（Cloudflare `error code: 1015` 限流），链上按普通失败降级。

工具轮（chat 的 agent loop）`pinned=gemini` 只影响首轮：gemini 挂了照常降级到
agnes → groq → deepseek。gpt-oss-120b 实测带 tools 正常（能纯文本回复、也能正确
发起 tool_call）。`max_tokens=4096`：SYSTEM_PROMPT 要求简短，1024 会把正常回答切断。

### Storage 说明

早期 tech_doc 写的是 SQLite，那是**计划**不是现状：`backend/` 里没有任何 `sqlite3`
引用。现在的形态是 R2（线上）+ 本地 `data/` 镜像，见「部署」与 `data/README.md`。

岗位数据物理含义是**覆盖快照**而非追加（`save_snapshot` 按 id 去重合并，新批次覆盖
旧值），写入时过滤掉 `jd` 为空的岗位。数据量级是几十条，全量返回前端，没有分页。
真的到需要分页或并发写的那天再谈迁移，不要提前抽象 DAL。

## Layout

```
backend/
  entrypoint_worker.py         Worker 入口：路由表、用户名登录、_refresh 灌 store、
                               bindings 注入（模型 key / session / writer）
  api_read.py                  只读 API：jobs / careers / persona / me / resumes
  api_chat.py                  chat HTTP 层：四端点、SSE（TransformStream + 5s 心跳）
  api_write.py                 写路径：persona 上传/意向、resume 手改
  sessions.py                  会话存取：R2 chat_sessions/{sid}.json（无 TTL，用户自删）
  chat.py                      Agent 循环、工具注册表、system prompt 拼装
  tools.py                     Agent 工具实现：只读工具、analyze_jd、auto_compact
  jobs.py                      岗位领域：normalize、save_snapshot、job_cards、career_documents
  crawler.py                   BOSS CDP 采集 + 猎聘回退（只归离线）
  persona.py                   简历解析与 Persona（async 写，R2/本地双模式）
  resume.py                    简历领域：底稿、apply_edits、critique（async 写）
  common.py                    .env/secret 读取、容灾链（双传输）、markdown、token 启发式
  utils.py                     load_file/save_file(_async) + store 双模式 + patch + tool 外壳
  static/                      前端原样托管（Workers Assets）
wrangler.jsonc                 argus-web：python_workers flag、assets、R2 binding
python_modules/                vendor 的 workers-py SDK 与应用依赖（gitignore）
scripts/
  build_careers.py             岗位 → ≤3 个 Career（可丢弃）
  extract_capabilities.py      逐 Career 抽能力
  cluster_jobs.py              legacy gaps，已停用
  r2_pull.sh                   Web 写的拉回本地
  r2_push.sh                   离线产物推上 R2
tech_doc.md         本文件
dev_log.md          开发日志
```

## Frontend

**设计系统移植自 `../FluentChat/site/`**，不重复造轮子。移植进来的那部分
（首页 + Chat + tabbar）与上游逐字节相同，回上游取改动时 `diff` 一下就知道我们改过哪。
往后追加的段落（岗位详情、AI 解读）是我们自己的，**不承诺与上游一致**。

底部四个 tab 是产品结构，不是实现细节：

| Tab | 职责 | 状态 |
|---|---|---|
| **Chat** | 更新 Persona 的地方 | 已做：WhatsApp 式气泡 + composer + 上传按钮 |
| **Jobs** | 爬虫找到的求职意向下的活跃岗位聚类 | 已做：拉 `/api/jobs` 渲染卡片网格，点开进站内详情页 |
| **Career** | 把活跃岗位收敛成 Career（`workflow.md` S1） | 已做：拉 `/api/careers` 渲染卡片，Career 内岗位横滑轨道 |
| **Me** | 个人资料与设置 | placeholder |

### NPC 资产：JPEG 必须转带 alpha 的 webp

源图 `argus-anime.jpeg` 是 **RGB，无 alpha 通道，白底烘死在像素里**。
页面暗色模式底色是 `#000000`，直接用会是一块发光白板。

所以用**连通域泛洪**抠底：判白条件 `min(RGB) >= 246`，只保留**触边**的白色连通域。
关键点：只抠触边区域，角色身上的白斑/高光不触边，不会被抠穿成洞。
产出 `argus-anime.webp`（RGBA，45% 透明）。FluentChat 的 `npc-cat.webp` 同样是这个套路。

### Chat 视图

对话气泡层是**新写的**，FluentChat 里没有可抄（它是语音应用，`grep` bubble/msg/
composer/avatar 命中 0）。能复用的只有 token、`.view` 入场动画、`.tabbar`。

**首页与 Chat 是两个独立 view。** 顶部全局 `.topbar` 的 "Argus" 文字标识是
**回首页的唯一入口**，首页不在 tabbar 里（tabbar 仍是 Chat / Jobs / Me）。

Chat 页让位给对话：`.topbar` 换成 `.chat__head`（返回键 + 头像 + 名字），
`.tabbar` 隐藏、composer 顶替 —— WhatsApp / Line / 微信进具体会话都是这样。
切页逻辑集中在 `js/nav.js` 的 `go(name)`：同时处理 view 显隐、tab 选中态、
两条 bar 的显隐。`app.js` 与 `chat.js` 都从 `nav.js` import，不走循环依赖。

- Argus 气泡带小头像（`.avatar`，方形圆角，不做人脸裁切——见下）
- 头像不做人脸裁切的原因：NPC 源图 1024×1024，**脸的位置未知**（模型不支持读图）。
  用完整角色的圆角方图，零猜测风险。要裁脸需先确认脸的坐标。
- **不做人脸裁切，也不做圆形头像**
- 上传按钮只到"选中文件显示文件名 chip"，**没有后端端点**，不传文件
- Persona 更新逻辑**尚未设计**，`.env` 的智谱 key 仍未被任何代码使用

### 品牌色：暖色体系（奶油 + 摩卡棕）

用户选定「温暖一点」。原靛紫 `#5e5ce6` 全部废弃。

| token | 亮色 | 暗色 | 角色 |
|---|---|---|---|
| `--accent` | `#8b6f47` 摩卡 | `#d2b48c` 浅奶油 | tab 图标、返回箭头、chip 文字、send 底 |
| `--bubble-me` | `#f0e0c8` 奶油 | `#4a3b2e` 深棕 | 用户气泡底 |
| `--on-bubble` | `#3a2e22` 深墨 | `#f0e0c8` 奶油 | 压在气泡上的文字 |
| `--on-accent` | `#ffffff` | `#2a2118` | 压在 `--accent` 上的文字 |
| `--glow` | 暖 rgba | 暖 rgba | NPC 光晕、图标按钮底 |
| `--npc-shadow` | 投影 | 辉光 | 一个 token 切换两种模式，省掉一条覆盖规则 |

**三条不能省的规则：**

1. **`--accent` 必须分亮暗两档。** 亮底要深（4.55:1）、暗底要浅（10.65:1），
   方向相反。单一暖色无法两边都过 AA——实测奶油 `#F5E6D3` 压亮底只有 **1.19:1**。
2. **`--on-accent` 和 `--on-bubble` 是两回事，不能合并。** send 按钮是
   「accent 底 + 白字」，气泡是「奶油底 + 深墨字」，同一个 token 装不下。
3. **不要把奶油色用作图标/小字。** NPC 身体本身就是奶油（对比 1.03:1），
   奶油当图标会同时糊在底色和角色上。奶油只做底色。

全部对比度实测：亮底 accent 4.55、气泡 10.17；暗底 accent 10.65、气泡 8.28、
send 按钮 8.01。均过 WCAG AA（文本 4.5:1）。

**不要再用 PIL 的 `ImageDraw.floodfill`** —— 实测 thresh=8 下它会把中心像素
`(250,237,221)` 也填掉（蓝通道差 34 本该拦住），整图被吞光。语义不可靠，用连通域。

## Run

线上跑在 Cloudflare Worker（见下一节），本地只剩**离线管线**：爬虫、聚类、
抽能力。先 `source activate echo`（Python 3.10.20）。

```bash
# 数据同步（方向规则见 data/README.md）：Web 写的拉回，离线写的推走
bash scripts/r2_pull.sh
bash scripts/r2_push.sh

# 管线
python3 scripts/build_careers.py           # 岗位 → ≤3 个 Career，允许丢弃
python3 scripts/extract_capabilities.py    # 逐 Career 抽能力
python3 scripts/cluster_jobs.py            # legacy，已停用
```

Career 上限 3 个（`build_careers.py::MAX_CAREERS`）：招聘平台只让留 3 份简历，
多了用户也看不过来；归不进任何 Career 的岗位允许丢弃，main 会打印丢弃名单。

## 部署（Cloudflare Worker + R2）

**2026-10-16 迁移完成，本机不再是运行时。** 入口
`https://argus-web.luent-hat.workers.dev`（Worker，免费档）。所有请求先过
登录：用户名 + 密码比对 R2 的 users.json（明文），成功种 HttpOnly 会话 cookie；
站级没有 access code——网址本身就是唯一的秘密，拿到网址的人只能看见登录页
`ACCESS_CODE`——Worker 持有六家 LLM key，不设防等于公开调用权。

- **形态**：Workers Static Assets（`backend/static` 原样托管，SPA 回退）
  + Python Worker（`compatibility_flags: ["python_workers"]`，入口
  `backend/entrypoint_worker.py`）。FastAPI / uvicorn 已退役。
- **数据在 R2**（bucket `argus-data`，私有）：key = `careers.json` /
  `boss_jobs.json` / `persona.json` / `resumes/*.json` / `chat_sessions/*.json`。
  每个数据请求前 `_refresh` 全量灌进 `utils` 的 store（<300KB，R2 往返约
  200ms，I/O 不计 CPU），领域函数 `load_file` 缓存优先、未命中退本地——
  **离线与 Worker 跑同一份代码**，`store_active()` 切双模式。写路径同构：
  `save_file_async` 经注入的 writer 落 R2，写后同步进 store（同请求的后续
  读取要看得见刚写的内容）。
- **LLM 双传输**：pyodide 装不了 openai（httpx 依赖 socket），Worker 侧
  `js.fetch` 直打各家 OpenAI 兼容端点；容灾链主循环只有一份（`_run_chain`），
  传输以回调注入。离线脚本照旧走 SDK（同步入口 `call_llm`，asyncio.run 包装）。
  token 估算用字符启发式（tiktoken 有 Rust 扩展装不了）：西文 4 字符/token、
  CJK 1 字/token，刻意高估。Gemini 3 多轮工具调用必须原样回带 tool_calls 的
  `thought_signature`，重建三件套会 400。
- **session 落 R2**：`sessions.py`，`chat_sessions/{sid}.json`，**没有 TTL**——
  会话是侧栏里看得见、能自己删的东西，静默过期反而是数据丢失。免费档请求散在
  多个边缘节点，内存会话十次有九次恢复不到——这就是它必须在 R2 的原因。
- **Python 依赖** vendor 在 `python_modules/`（workers-py SDK + chinese-calendar
  + markdown-it-py，`uv pip install --target`，gitignore，换机器要重建）。不用
  requirements.txt：远端运行时会用 site-packages 的 workers shim 盖回去。
- **密钥**全走 `wrangler secret put`：`ACCESS_CODE` + 五家模型 key
  （`AGNES_API_KEY` 等，名字见 `common.ENDPOINTS`）。本地开发用 `.dev.vars`。
- **部署**：`CLOUDFLARE_ACCOUNT_ID=<id> npx wrangler deploy`。验 bundle 不泄密：
  `wrangler deploy --dry-run --outdir d` 后 grep `.env`。
- **排障**：`NODE_USE_ENV_PROXY=1 HTTPS_PROXY=http://127.0.0.1:8118 npx wrangler
  tail`（本地网络直连不上 tail 端点，必须走 8118 代理）；chat 响应自带
  `model`/`chain`/`session_backend` 诊断字段；`GET /api/ping` 带分步耗时与
  chain trace；`POST /api/debug/llm` 可指定模型/pinned 单发。
- **免费档实测边界**（2026-10-16）：10ms CPU/请求。读取路径（refresh + 解析 +
  markdown）稳定通过；token 启发式曾是 CPU 炸弹（逐字符 Python 循环，实测
  1101 超限），改 C 级 encode 后 18.5ms→0.13ms。LLM 等待是 I/O 不计 CPU。
  groq 从边缘可达（中国 IP 的 403 消失）。
- **已退役**（2026-10-16 删）：cloudflared 隧道、`argus-proxy` Worker + KV、
  `scripts/restart.sh`、`scripts/watchdog.sh`、uvicorn、`backend/main.py`、
  `me.py`、`routes_legacy.py`。

## 岗位详情（2026-10-09）

卡片点开进站内详情页，投递才是唯一离开本站的动作。

- **卡片仍是 `<a>`，`href` 是站内真路径 `/job/<id>`**，不是外链（复制链接/新标签打开
  都走得了）。点击时 `preventDefault` + `pushState`，不整页刷新。所以 `.jobcard` 样式
  一行没动，长按/右键行为照旧
- **岗位本体不需要新后端接口**：`jd` 全文一直存在 `data/boss_jobs.json` 里，`/api/jobs`
  本来就全量返回。`cards.js` 渲染时顺手 `remember(job)` 存进内存，深链接直接命中，
  未命中的才回落到 `/api/jobs`。（AI 解读是另一份数据，另走一个接口，见下节）
- `job` 视图必须和 Chat 一样归入「沉浸式」（隐藏 tabbar）：否则在详情页点 Jobs tab
  会撞上 `app.js` 里「已选中就 return」的短路，卡在原地回不去
- 后退优先交给 `history.back()`（iPhone 侧滑返回才对得上），直接粘链接进来的场景
  `history.state` 为 null，降级为记住来源视图的 `nav.back()`
- **JD 有康熙部首乱码**（`建⽴⽬标`），是抓取器字体解码的产物。只对命中的码位段做
  NFKC，**不能整串 NFKC** —— 那会把全角逗号也压成半角
- `normalize()` 原本丢弃了 `company_scale / company_stage / company_industry /
  welfare / boss_title / job_labels / skills` —— 抓取器一直在返回（`map_api_job`），
  只是没存。补上后需**重跑一次采集**才有数据，详情页对缺失字段整行跳过

### AI 解读（2026-10-09）

`scripts/cluster_jobs.py` 跑出的 `data/job_gaps.json`（438KB / 30 岗位 ≈ 15KB 每岗）
接进详情页，位置在 **JD 原文之后**。

**默认形态：JD 展开，解读折叠。** JD 是投递的原始依据，解读是模型的推论——
折叠起来让用户自己决定什么时候看，而不是被推着先读一段 AI 的话。折叠头只给
结论徽标（「长期储备」这类），点开才是完整解读。

**数据通道：单岗位接口，不并入 `/api/jobs`。**
`GET /api/jobs/{job_id}/analysis` → `{job_id, generated_at, model, analysis, target}`。

- 全量 `/api/gaps` 不划算：438KB 一次性下发，且岗位刷新后解读不跟着更新。
  单岗位约 15KB，懒加载，详情页 `render()` 后异步补进来
- **必须带上 `target`**（`target_base` / `target_salary`）。`intent_match` 只给
  `aligned` / `above_target` 这类状态，**没说是跟什么对齐**——不下发目标值就只能显示
  「已对齐」这种没主语的词。前端拼成「地点符合你的意向 上海」这种整句
- **`analysis` 原样透传，不在后端归一化**

**LLM 输出的键不齐，前端一律 `??` 兜底。**

| 现象 | 实测 | 处理 |
|---|---|---|
| `openning` 写成 `opening` | 1/30 岗位 | `a.openning ?? a.opening` |
| `defensive_script` 有四种键变体 | 76 条**全都**带 `mitigation_angle`，其余是重复而非替代 | 只读 `mitigation_angle` |
| `gap_details` 只有 `has_gap` | 43/293 条要求 | 缺口文案与难度都按可选渲染 |
| 引用 JD 原文带康熙部首 | 23 处 | `deRadical` 也要过解读文本，不只 JD |

**不要把这些归一化搬到后端。** 后端归一化等于把这一批的脏数据固化成 API 契约，
重跑 cluster 后还得再改一次；放前端读时兜底，重跑即自愈。

**分层：core 展开，非 core 折叠。**

- 概览卡片统计**全部**要求（分母诚实），但只列 `core` 行的明细。
  `important` / `bonus` 不影响「投不投」的判断，收进一个 `<details>`
- 每种匹配状态一张卡，带一句「凭什么」：`已证明 / 有直接对应的经历`。
  光有「已证明」三个字看不出是拿什么证明的。原来的 6px 细条 + 小字图例在手机上
  很难受，四种颜色得盯着 6px 去分辨
- **补齐行动按 `bridge_difficulty` 降序排**（难补的排前面）。行动条目通过
  `target_gap_tag` 反查要求里的难度，两边靠这个 tag 关联
- 折叠一律用原生 `<details>`：键盘与读屏行为免费，不需要自己写 accordion

**状态色都过 4.5:1（对白底）**，小字可直接用不必再套底色：
`#2e6b4f` 6.30 / `#a03d33` 6.54 / `#6b6259` 5.97 / `--accent` 4.71。

**前端领域切分**：`job.js` 只管岗位本体与路由，`analysis.js` 只管解读渲染，
`el` / `deRadical` / `fold` 提到 `dom.js` 共用——否则会形成
`analysis ← job ← analysis` 的循环依赖。

**未验证**：这套布局**没有在真机浏览器里看过**。已做的验证：后端经 `TestClient`
与重启后的 7800 实测；前端用临时 DOM shim 跑通 30 个岗位（卡片数字与数据逐岗对账、
段宽合计 100%、无 `undefined`/`[object` 泄漏、复制文案与清单一致）。
卡片的实际视觉与折叠头箭头位置仍需真机确认。

## Career 页（2026-10-10）

把 S1 的产物 `data/careers.json`（`workflow.md` §2）摆到站上。它是**岗位侧**
的产物——Career 定义与 `job_id → career` 映射，不读 persona，与人无关。

### 布局：常驻三行 + 两个默认折叠

每个 Career 一张白卡（沿用 `.jobcard` 的发丝边 + 投影语汇），卡内：

```text
经营分析 · 6 个岗位                          ← Career 名
承接企业或事业部（BU）战略规划，围绕营收…    ← positioning，常驻
岗位职责以经营目标拆解（营收/利润/OKR）…      ← membership_criteria，常驻
  ▸ 能力要求 4 条     （徽章分级 + JD 原文）   ← 默认折叠
  ▸ 岗位 6 个          （横滑轨道）            ← 默认折叠
```

**定位与判据必须常驻。** 它俩是判断「这些岗位是不是同一个 Career」的唯一依据，藏进折叠里
等于没写；能力清单和岗位列表是查表用的，默认全收，页面首屏能纵览全部 Career。

能力按 `core / important / bonus` 三级上色，配色沿用 AI 解读的绿/金/灰，
每条带 `jd_evidence` 原文——Career 定义是人可编辑的地基，得能对着 JD 核对。

**当前 `capabilities` 是空的**：S1 已拆成「切边界」与「抽能力」两步，后者
（`scripts/extract_capabilities.py`）尚未实现，见 `workflow.md` §2。前端用
`f.capabilities ?? []` 兜住，折叠区会显示「能力要求 0 条」，页面不会崩。

### 三个决定

- **Career 内岗位复用 `cards.js` 的 `jobCards()`**，零新组件。`jobCard()` 内部会
  `remember(job)`，所以在 Career 页点卡片进 `/job/<id>` 后，`job.js` 的详情页直接
  命中内存，返回时 `nav.js` 的 `last` 记住来源是 `career`，往返正常
- **详情页走真路径，Career 本身没有独立路由**。细节页（`/job/<id>`、`/resume/<id>`）
  用 `pushState`，浏览器返回/刷新/直达都走得通；Career 只有一层，六张卡一屏装得下，
  不为它单开一条 `/career/<id>`——那只会多一套返回栈和一份导航状态，
  `nav.js` 的沉浸式分支（`chat` / `job`）也跟着变复杂。
  折叠用 `dom.js` 的 `fold()`（原生 `<details>`），键盘和读屏免费
- **接口放在 `jobs.py` 而非新建 `careers.py`**：路由已在 `main.py` 注册好，
  `data/careers.json` 本就是岗位侧产物，归 jobs 域说得通

### 后端要回填岗位

`careers[].jobs[]` 里只有 `job_id / company / title / belongs_note`，**缺
`salary` / `location` / `source` / `collected_at`**，直接喂 `jobCard()` 会得到空薪资、
空 meta、`href` 变成 `/job/`。`/api/careers` 因此按 id 回填 `boss_jobs` 的完整岗位：

```python
{**j, **jobs.get(j["job_id"], {}), "id": j["job_id"]}
```

Career 内的 company/title 在**前**、快照的在**后**，于是快照更新时以快照为准；
岗位已从新快照消失时回落到 Career 内那份，页面显示的是仍然存在的岗位而不是 `None`。

### 两个空态要分开

`res.ok` 为假（后端没重启，接口 404）和 `careers` 为空（还没跑过 S1）是两回事，
必须给不同文案。曾经 404 时页面显示「还没跑过 S1」——S1 明明跑过，文件就在
`data/` 里躺着，那是在骗人。

**前端跟着后端的版本走**：`StaticFiles` 每次从磁盘读，改完前端刷新就生效；
但 Python 改动**必须重启 uvicorn**，否则接口还是旧的 404。

### 已知取舍

- 返回的 Career 成员里 `job_id` 与 `id` 重复透传。跟 `jobs.py` 里 `gaps_by_job()` 的既有写法
  一致，为省一次清洗没去掉
- 页面不显示 `belongs_note`（某岗位为何属于这个 Career）。它是 S1 唯一解释 title 与实际
  职能不符的地方，核对价值最高，但现在只在 API 里。Career 内岗位多了会挤，先不做

## Chat Agent（2026-10-11）

Chat 是主 Agent loop：system prompt 里只有工具说明，**所有事实都在文件里，由模型自己决定读哪个**。
四个只读工具，schema 注册在 `chat.py::TOOLS`，**实现在 `tools.py`**：

| 工具 | 返回 | 大小 |
|---|---|---|
| `read_persona` | 用户**最初上传的那份**履历与求职意向（经历、项目、技能、意向职位/城市/薪资） | 4KB |
| `read_careers` | 6 个 Career 的定位、归属判据、能力清单、成员岗位，全量 | 19KB |
| `read_job_gaps` | 岗位 × persona 差距解读的**索引**（公司/岗位/薪资/地点） | 5KB |
| `read_job_gap(job_id)` | 单个岗位的完整解读：每条要求的匹配状态、缺什么、简历证据 | ~12KB |

### 领域的划分：注册归 chat，实现归 tools

划分依据是**这块代码归哪个领域、谁消费它**，不是「看起来像什么」。
**被 LLM 当 tool call 调用的函数，实现全在 `tools.py`**——它们的服务对象是模型调用，
不是某个 HTTP 路由。`chat.py` 决定「有哪些工具、怎么注册」，`tools.py` 决定
「工具被调用时干什么」。于是 `SYSTEM_PROMPT`（对话总指令，不注册任何工具）与
`TOOLS`/`READERS` 注册表都留在 chat.py，而 `read_careers` 等实现从 `jobs.py`
搬进 `tools.py`。

**tools.py 因此不认识 HTTP**，四个只读工具直接读 `data/` 下的文件，不经 `jobs.py`
的路由函数——两者用途不同（`/api/careers` 是给前端渲染，工具是给模型读的）。
`jobs.py::_gaps` 改名 `gaps_by_job`，因为工具与路由共用它。

依赖方向单向：`chat → tools → {persona, jobs, crawler}`、`chat → persona`、
`jobs → persona`。**chat.py 已不 import crawler。**

### 上下文压缩：按 token 阈值，不按轮数（2026-10-11）

原先用 `MAX_HISTORY = 20` 截断历史，有两个各自独立的毛病：

1. **轮数与 token 无关。** 9 轮闲聊就能让单次请求到 10k+ token。实测固定开销
   610（system + 工具声明）+ `read_careers` 返回 5370 + `read_job_gap` 最大 7082，
   一轮就可能顶到 18k。
2. **工具结果不跨轮持久化。** `_history` 只收 user 文本与 assistant 回复，
   `read_careers` 那 5370 token 只活在单次请求的局部列表里。且 9 轮窗口会把
   前几题挤出历史——后续做 S2/S3 追问流程时，模型到第 8 题就已经想不起 Q1。

改为**超 token 阈值触发压缩**：`tools.auto_compact()` 在 `/api/chat` 发请求前调，
保留最近 6 轮原文 + 一条摘要，摘要以 `user` 身份注入（system prompt 保持单一
事实源，与 Claude Code / Codex 一致）。

阈值 **128k** = 链首三个模型（`agnes-3.0-flash` 262k / `ling-3.1-flash` 262k /
`nemotron-3-ultra 1M`）context window 平均值 507k 的 25%。

- **`auto_compact` 不注册进 `TOOLS`。** 压缩若是模型可选行为，模型不调就不压，
  阈值形同虚设。它是代码行为。
- **压缩失败不抛**，原样保留历史：压缩是优化，不该让这一轮问答整个失败。
- 摘要 prompt 硬性要求保留三件事：未完成的事（追问停在第几题）、用户的事实性
  陈述（persona 里没有、只存在于对话里的信息）、已确认的结论。
- 只动内存不落盘，与既有语义一致（重启即丢）。

会话列表走 `GET /api/chat/sessions`（当前用户 R2 前缀下所有会话摘要，标题 +
更新时间倒序，见 `sessions.list_all`），删除走 `POST /api/chat/delete`
（body `{"sid"}`，同步删 R2 对象）。前端侧栏每行一个垃圾桶：
- **乐观移除 + 可撤销**。点垃圾桶立刻从列表移除（不等后端），真正的 R2 删除延后
  5s，期间底部弹「已删除 · 撤销」。不弹阻塞式二次确认——误触靠撤销兜，逐字敲
  「确认」的摩擦只为 5s 内点一下「撤销」的极小概率买单不值得。之所以必须乐观，
  是因为 Worker 每请求都要付 pyodide 冷启动 + 一轮全量 `_refresh()`，等后端返回再
  更新界面会像卡死。
- **这几个 chat 端点跳过 `_refresh()`**（`entrypoint_worker.NO_STORE_PATHS`）：
  `sessions`/`delete`/`history`/`messages`/`undo` 只读 `chat_sessions/` 下的会话
  对象，不碰任何数据文件，灌 store 纯属白等；带模型/工具的 `/api/chat`、
  `/api/chat/stream` 才需要。
- 首轮落盘时用 groq 小模型（`openai/gpt-oss-20b`，不带工具的 subagent 调用）
  给会话起个标题，失败退回首条用户消息截断。会话**没有 TTL**：可见、可删的东西
  就该一直在，静默过期反而是数据丢失。

### 四个决定

1. **persona 不再常驻 system prompt。** 原先 `_system_with_persona()` 每轮把整份 JSON 拼进
   system message（4KB ≈ 2k token），现在改成工具按需读：省 token，也让「读文件」这件事
   本身成为模型的显式动作。
2. **`job_gaps` 两段式。** 全量 438KB（30 岗 ≈ 15KB/岗）读不动，且必然顶穿 Groq 的
   7000 输入 token 闸门（`common.py:101`）。先给 5KB 索引、模型挑中再按 `job_id` 读单条，
   单次上限因此可控。
3. **`careers` 一次全量。** 只有 6 个 Career，模型要横向比较；两段式会让它多绕一次，
   而且得先知道叫什么名字才能查。
4. **读工具不产出前端卡片。** `search_boss_jobs` 原本把结果旁路成 `resp["jobs"]` 给前端，
   读工具纯做上下文注入，不碰渲染。

### 暂时停用的两个工具

`update_persona`（写求职意向）与 `search_boss_jobs`（搜岗位）已从 `TOOLS` 摘掉，
`save_targets` 调用留在 `chat.py` 的 dispatch 分支，`search_jobs` 实现在 `tools.py`
（原 `chat.py::_search_jobs`，去掉下划线是因为它是跨模块公开的实现）。
想开回来把它们加回 `TOOLS` 即可。dispatch 走 `READERS` 字典，`_execute_tool` 里
先查 `READERS` 再落到旧分支——不加这个字典，读工具会被旧代码当成 `search_boss_jobs`
去搜岗位。

`search_jobs` 是**唯一会写 `data/` 事实源的工具**（落 `boss_jobs.json` 覆盖快照），
其余只读工具不写。另有一类写的是 `data/resumes/`——`copy_from_persona` 建底稿、
`apply_edits` 改正文，但**触发者是用户不是 LLM**（见下节）。

## Resume 页与简历所有权（2026-10-11）

**简历是用户的文件，不是 AI 的产物。** AI 在简历上只剩两个动作：**问**（S2 的追问清单）
和**评**（`critique_resume`，筛简历那步，只读不写）。`draft()` / `rewrite()` 已删，
`draft_resume` / `rewrite_resume` / `apply_resume_edits` 三个工具从 `TOOLS` 摘掉，
工具从 9 个降到 7 个。

**上下文里永远是最新的。** 进简历模式后，简历正文进 **system prompt** 而不是 history——
`auto_compact` 压的是 history，贴进去会被压成摘要，模型就拿着改之前的旧版本跟用户讨论。
每轮现读磁盘，尾部带一句「你在这段对话里读到的、记下的任何简历内容一律作废」。
顺带把 `read_persona` 描述改成「他**最初上传的那份**」：用户改完简历后 persona 与
简历会分叉，模型最可能在这里出精神错乱。

**Resume 页**（tabbar：Chat | **Resume** | Jobs | Career | Me）：
- 每个 Career 默认一份底稿（`ensure_all`，逐字拷 persona 去掉求职意向，**零 LLM**）
- 卡片平时只读，右上角 Edit 图标；点开才变成输入框，改完点「提交」才发请求
- **不挂 AI 评语**——评语是 Argus 在 Chat 里说的话
- 删除换成垃圾桶图标；删整段经历要点两次（3 秒后自动复原）

**patch 机制保留，触发者从 LLM 变成用户。** `apply_edits` 现在唯一的调用方是
`POST /api/resumes/{id}/edits`，前端表单把字段换算成 ops 发过来。
结构化表单天生知道「用户改的是哪个 JSON Pointer」，所以它没进冷冻室。

**前端按「谁消费它」拆成两份**，跟 `cards.js` / `job.js` 一个路子：
- `resume.js`——共享件：Chat 全文卡、Career 软链、索引拉取（`loadIndex`）、只读渲染（`work`）
- `resumepage.js`——Resume 页：列表、详情、编辑器、真路径路由（`/resume/<id>`）

### 约定

- `StaticFiles` mount在 `/` **必须放在所有 API 路由声明之后**，否则会遮蔽它们。
- **静态资源一律 `Cache-Control: no-store`**（`main.py` 中间件）。不设这个头时浏览器
  会用 `Last-Modified` 做启发式缓存：文件刚改过（Last-Modified 是几分钟前）就仍算
  「新鲜」而继续跑旧 JS，PWA 模式下 Safari 判得更松，改完前端不生效只能强刷。
  自用开发机，牺牲缓存换「改完刷新就是新的」
- 前端所有 API 调用走相对路径 `/api/...`，由同一个 FastAPI 进程 serve，无需 CORS、无需 dev server 代理。
- **改 JS 后必须做模块图可达性检查**：`index.html` 只加载 `js/app.js`，
  其余模块靠 import 链到达。裸副作用导入 `import "./x.js"`（没有 `from`）
  最容易在重写入口文件时被漏掉——文件在磁盘上、代码看着完全合理，但浏览器不下载它。
  检查要同时匹配 `from "..."` 和 `import "..."` 两种形式。

## Crawler (2026-10-08 定稿)

- **BOSS 推荐流 `wapi/zpgeek/recommend/job/list.json` 上限约 30 条**（2 批，每批 15 条，`page=1` 且 `hasMore` 为空；第 3 批 `Network.requestWillBeSent` 无新请求，滚动 3 次重试仍 `None`，`diag_net.py` 复现）。`crawler.py` `fetch_boss_recommendations` 初始 `Page.navigate zhipin.com` 即拿 15 条，滚动仅再得 1 批；`max_batches=5` 亦止于 30。
- **全量搜索 `wapi/zpgeek/search/joblist.json` 已封 `code:37 zpData seed`**，`ScraperAPI premium+render` 44k 滑块，不可用；当前唯一真实源为推荐流，猎聘 Liepin 为回退。
- **全量 JD**：`fetch_boss_details` 复用 `vendor/boss-zhipin-scraper scrape_details` 逐条 `job_detail` 拿 `jd/skill_tags/boss_active_status`，`extract_detail_fields` 校验；`jd` 为空视为关闭过滤，不入 `boss_jobs.json`。
- **存储语义**：`data/boss_jobs.json` 为**覆盖快照**（`save_snapshot`，`data/jobs.json` 已废弃删除），物理意义=当前推荐开放中岗位，非追加；仅保留带 `jd` 的开放岗。

## 尚未决定（不要自行假设）

- Persona 的存储 schema 与 Evidence 链怎么建模
- 接哪个 LLM 做 Persona 抽取 / Gap Analysis，以及是否流式。
  （Gap Analysis 已经跑起来了，走 `common.active_chain` 的容灾链，
  这一批 30 个岗位实际分布在 gemini-3.5-flash / glm-4.7-flash / deepseek-v4-flash
  三个模型上——**逐岗位独立选模型，不是整个批次一个模型**。
  解读是否流式仍未定，目前是跑批产出 JSON 文件、页面按需读文件。）
- 前端在 Phase 1 之后是否升级为 React + Vite（引入构建链）
- 前端形态（对话流 / Persona 面板 / Gap 列表）如何对应 README 的 MVP 五个模块。
  （岗位维度的 AI 解读已接入详情页，跨岗位的 Gap 频次视图还没做——
  `gap_canonical_tag` 是为跨岗位统计设计的，数据已经就位，界面还没有。）
- `job_gaps.json` 的生命周期：目前**不入 git**（`.gitignore` 第 226 行 `data/`
  整目录忽略），重跑 cluster 是全量覆盖。重跑后页面上的解读会变，要不要版本化留档未定。
  注意这意味着**换台机器 clone 下来没有解读数据**，页面会对所有岗位显示成无解读


## Persona Schema（2026-10-03 定稿，**2026-10-04 已作废**）

> 以下设计讨论保留作历史记录。当时的落地物是 `backend/persona_model.py`（Pydantic）
> 与其导出产物 `persona.md` / `backend/persona_schema.json`，现已全部删除。
> Persona 内部不再有数据模型，就是一个 dict；字段约定的唯一来源是
> `backend/persona.py` 里的 `RESUME_TO_PERSONA` prompt。
> 导出脚本 `backend.tools.export_persona_schema` 与约束检查
> `backend.tests.run_persona_checks` / `test_persona_model.py` 一并删除，无替代。

### 五条定稿决定

1. **gaps 持久化 + 快照语义。** `current_level`/`target_level` 冗余存储
   评估当时的值，**不从 `capabilities` 反查**——反查会让 gap 状态机依赖的值被偷改。
   新鲜度看 `Gap.stale()`（capability 档案比 `evaluated_at` 新即过期）。
2. **多目标。** `targets[]`，gap 挂在 target 下并按 target 分片。
3. **interventions 顶层去重。** 完成状态按 `(干预, gap)` 逐对记在
   `gap_results`，**不能**在 intervention 上放单个完成标志——两个 target 对
   同一能力的 `target_level` 可能不同，一次「学 SQL」可能关掉 PM 的 gap
   而关不掉 DA 的。
4. **LLM 产出的 gap 初始为 `proposed`**，用户批准才转 `open`。
   对应 README 的 Human in the Loop。
5. **`level` 统一 1-5 带锚点**（`LEVEL_ANCHORS`）。gaps 的 current/target 与
   `capabilities[].level` 同尺度，否则差值无意义。

### 两个承重约束

- **`capabilities[].id` 是承重外键**，`expression` 和 `gaps` 都引用它。
  必须用 `capability_slug()` 派生稳定 slug，**不能用 UUID**——改 id 即悬空。
- **`dangling_refs()` 不自动触发**。它是显式调用方法，Pydantic 不会拦。
  增量写入时允许暂时悬空是合理的；B 片落库前必须显式检查一次。

### 相对原草稿的改动

| 原草稿 | 改动 | 原因 |
|---|---|---|
| `gaps` 在 persona 下扁平 | 移到 `targets[].gaps` | 多目标需分片 |
| `interventions` 在 target 下 | 提到顶层 + `serves_gaps` | 跨目标去重 |
| 无 gap 状态 | `proposed/open/resolved/dismissed` | README 358 行避免凭印象贴标签 |
| `development.goals/- ...` | 删除 | 与 `targets[].role` 语义重叠且未定义 |
| `development.progress` | 删除 | 与 intervention 的关系无 FK；证据回流走 `new_evidence` |
| `level` / `confidence` 裸标量 | 1-5 带锚点 + 三档枚举 | 裸数字对 LLM 无意义 |
| 无时间戳 | `occurred_at` / `evaluated_at` / `updated_at` | README 385 行"有没有变好"在数据上无法回答 |
| `strengths`/`weaknesses` 缺失 | 删除 | 可从 `gaps.importance` 推导，重复存储必然漂移 |
| `compensation` 单标量 | `{current, expected}` | 谈判需要两个值 |
| `note` 自由文本 | `preferences.notes` + LLM 禁写标注 | 自由文本是 schema 退化起点 |
| 无 Communication | `expression[]` 独立结构 | 能力≠表达，README 144 行的 gap 类型塌缩了 |

### 已知取舍

- `dangling_refs()` 只报不抛：允许增量构建中途悬空。
- `category` 与 `category_raw` 并存，等真实 JD 数据到位后再定受控词表。
- 存储（B 片）用单行 JSON 列，不建正规表。等多目标跑起来有真实数据再做迁移依据。
