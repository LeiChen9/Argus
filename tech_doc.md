# Argus — Tech Doc

已达成共识的技术选型。**只记已确定的选择和决策理由**，不记实现细节、不记待办。
进度与踩坑记录写 `dev_log.md`。

Last updated: 2026-10-08

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
| Backend | **Python + FastAPI** | 用户指定 Python（熟悉）。FastAPI 自动出 `/docs`，Pydantic 类型化便于后续接 LLM 流式响应。 |
| Frontend | **静态 HTML + 原生 JS** | 无构建步骤、无 node 工具链进应用路径。改完刷新即见，Phase 1 迭代最快。 |
| Storage | **SQLite，走 stdlib `sqlite3`，不上ORM** | 单用户单进程，慢的是 LLM 不是 DB。零新依赖。`.gitignore` 已忽略 `db.sqlite3`。 |
| LLM Provider | 智谱 `zhipu_realtime`，key 在 `.env` | `.env` 已被 gitignore；`.env` 不入库。 |

### Storage 已知债务

裸 `sqlite3` 意味着**方言绑定**。将来若换 Postgres，以下都要重写：
`AUTOINCREMENT`、`?` 占位符、类型声明、以及每一个拼接出来的查询字符串。

这是**明确接受的债务**，不是疏漏。换库的前提条件是：先引入 ORM 做一次集中迁移。
在债务兑现前，不要写 ORM 也不要提前抽象 DAL —— 按需引入。

## Layout

```
backend/
  main.py                      FastAPI app
  static/
    index.html                 由 FastAPI StaticFiles 直接 serve
    css/app.css                设计系统，移植自 FluentChat
    js/app.js                  tab 切换 + 招呼语注入 + 引入 chat.js
    js/chat.js                 气泡渲染 / 调 /api/chat / 上传 chip
    js/greeting.js             时段×星期招呼语
    assets/argus-anime.jpeg    NPC 源图（用户设计）
    assets/argus-anime.webp    带 alpha，页面实际使用
tech_doc.md         本文件
dev_log.md          开发日志
```

## Frontend

**设计系统移植自 `../FluentChat/site/`**，不重复造轮子。`css/app.css` 268 行里
除注释外与上游逐字节相同。回上游取改动：`diff` 一下就知道我们改过哪。

底部三个 tab 是产品结构，不是实现细节：

| Tab | 职责 | 状态 |
|---|---|---|
| **Chat** | 更新 Persona 的地方 | 已做：WhatsApp 式气泡 + composer + 上传按钮 |
| **Jobs** | 爬虫找到的求职意向下的活跃岗位聚类 | placeholder，爬虫未接 |
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

```bash
source activate echo
uvicorn main:app --app-dir backend --port 7800
```

访问 `http://localhost:7800`（页面）/ `http://localhost:7800/docs`（API 文档）。

**端口 7800。** 本机同时有别的程序在跑 localhost 测试，Argus 固定占 **7800**。
历史：曾是 8010；更早的 8000 被一个遗留的 `python -m http.server 8000` 占过
（它 listen 在 IPv6 `*:8000`，会劫持 `localhost` 的 IPv6 解析，表现为收到 501）。

端口只出现在本节，**代码里没有硬编码端口**。换端口只改这一行。

## 公网访问（Cloudflare Tunnel）

不做 Workers 迁移（FastAPI + 本地文件存储 + 本机浏览器探针跑不上 Workers），
用 Cloudflare Tunnel 把本机 7800 暴露出去。

- 临时预览：`cloudflared tunnel --url http://localhost:7800`（免登录，地址每次变）
- 固定入口（免买域）：`worker-proxy` Worker 固定 `https://argus-proxy.luent-hat.workers.dev` 转发到 `*.trycloudflare.com` 源；`cloudflared tunnel --url` 重启换 URL 后需更新 `worker-proxy/worker.js` 的 `ORIGIN` 并重部署
- 一键重绑：`./scripts/restart.sh` 起 7800 + 拉新 quick URL + `wrangler deploy --cwd worker-proxy` + 校验 `worker /api/jobs` 30 条；固定域重启不变，临时域会变
- 正式（需自有域）：`cloudflared tunnel login` → 建 tunnel → 绑自有域名 → 常驻运行
- `cloudflared` 用 homebrew 装；`cert.pem` 缺失时 `tunnel list` 会报错，
  需要重新 `tunnel login`（FluentChat 走 wrangler，不共用这份授权）。

## 约定

- `StaticFiles` mount在 `/` **必须放在所有 API 路由声明之后**，否则会遮蔽它们。
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
- 接哪个 LLM 做 Persona 抽取 / Gap Analysis，以及是否流式
- 前端在 Phase 1 之后是否升级为 React + Vite（引入构建链）
- 前端形态（对话流 / Persona 面板 / Gap 列表）如何对应 README 的 MVP 五个模块


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
