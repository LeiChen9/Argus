# Argus — 求职流程

README 的 The Career Loop（Observe → Understand → Model → Diagnose → Intervene →
Practice → Measure → Update）是八步愿景循环。本文档只细化其中当前可执行的一段：

```text
Observe（已有 boss_jobs.json）
    ↓
Model   → S1 Career
Diagnose→ S2 Career × persona 的 gap，S3 补 persona
Intervene→ S4 Career 级简历
Practice→ S5 Career 级面试 playbook + job 级 delta
```

`Measure` / `Update` 需要投递与面试的真实数据，见 §5「已知缺失」。

---

## 1. 三类产物

流程能立住，靠的是按「会不会过期」把东西分开。

| 类别 | 产物 | 语义 |
| --- | --- | --- |
| **事实源** | `backend/persona.json` | 不可删，只增。每条经历带 `source`（上传 / 追问） |
| **岗位侧** | `data/careers.json` | 与人无关。Career 定义 + `job_id → career` 映射 |
| **派生物** | `data/resumes/{career}.md`<br>`data/playbooks/{career}.json` | 可随时删了重生成 |

承重的一句话：**Career 定义变了，已生成的简历立刻作废，但 persona 不受影响。**

派生物和事实源分开是唯一的结构性约束：LLM 改了 Career 定义时，
`boss_jobs.json` 和 persona 都不能跟着漂。

### 为什么 persona 需要 `source`

S4 的硬约束是「简历里每一行都能追溯到 persona 的一条事实」。
prompt 里写「不要编造」是自觉，不是检查；`source` 字段让追溯成为可核对的事。
它比一套 confidence 评分体系省事得多，后者要维护、也要不了多少准确性。

---

## 2. 六阶段

| 阶段 | 输入 | 动作 | 输出 | 人工卡点 | 怎么验证算过 |
| --- | --- | --- | --- | --- | --- |
| **S0** 硬过滤 | `boss_jobs.json` | 规则匹配，**零 LLM** | 存活 job 列表 | 无 | 数砍了几个、砍的理由 |
| **S1** 建 Career | 存活 job 的 JD | 1 次 LLM 读全部 JD → Career 定义 + 归属 | `careers.json` | **人可编辑** | 逐个读：内里像不像一类，彼此分得开吗 |
| **S2** Career × persona | Career 要求 + persona | 1 次 LLM / Career | Career 级 gap + **追问清单** + 表达建议 | 人决定投哪几个 Career | 追问清单每条是否真的指向某段经历 |
| **S3** 补 persona | 追问清单 | 用户作答 | persona 增条，带 `source` | 必须人回答 | 新经历能否追溯到具体回答 |
| **S4** 简历 | persona + Career 要求 | 1 次 LLM / Career | `resumes/{career}.md` | 人读 | **逐行追溯**到 persona 一条 |
| **S5** 面试 | 简历 + Career 要求 + 本岗 JD | 1 次 LLM / Career + 轻量 diff / 岗 | playbook + per-job delta | 人读 | playbook 里的问题你自己答得上来吗 |

### S0 硬过滤

免费的一刀，先砍掉后面所有 LLM 成本里注定无用的部分。

对当前 `boss_jobs.json`（30 个岗位）的实际效果：

- **地点非上海**：数据分析专家（北京）、阿里国际-AI经营分析-杭州、服装电商数据分析师 → 砍 3 个
- **岗位性质不符**：AI数据产品经理（65-95K，是产品岗不是分析岗）→ 砍 1 个
- **薪资明显低于目标**（target_salary 25k-30k）：淘宝闪购-KA（15-25K）、
  数据分析（商业分析）（15-30K）、数据科学-中国销售业务平台（15-30K）→ 砍 3 个

薪资目标定得低于几乎所有岗位，所以这条只砍上限明显低于 30k 的，
「下限 20k 但上限 30-40k」的岗位与目标区间重叠，不砍。

### S1 建 Career

**按岗位职能切**，不按行业切——职能相同则能力要求相近，S4 的简历可复用。

一次调用读全部 JD（当前 30 岗合计 14515 字符，一次读得完），
**不是每岗一次调用**。与 `cluster_jobs.py` 当初拒绝聚类的理由不冲突：
当时是 30 个独立调用、彼此无参照系，现在是**一次调用产出全局划分**。

输出必须包含 `job_id → career` 的映射并落盘。归属结果不能每次重算：
`boss_jobs.json` 一长大重跑聚类，所有 Career 的边界都会漂。

**S1 分两步跑。** ① `build_careers.py` 只切边界，输出里 `capabilities` 字段整个
不存在；② 能力由 `extract_capabilities.py` 另跑一次、逐个 Career 补齐，读的是
**磁盘上当前的边界**。边界因此可以先按人读的判断手改，再抽能力，不必为了补能力
而接受一次边界漂移。② 尚未实现，所以现在 `data/careers.json` 的 `capabilities`
是空的——页面上「能力要求 0 条」是预期的，不是坏了。

### S2 / S3 是回环

S2 **只出追问清单和表达建议，不生成简历**。

S2 就生成简历的话，它只能在旧 persona 上做重排，
等于放弃了「挖出没写的东西」——那是本项目的核心功能之一。

### S4 简历

等 S3 之后再生成。硬约束：每行可追溯到 persona 一条事实。

### S5 面试

**job 级阶段是 diff，不是重算。** S1 已经把每个 JD 的要求归到了某个 Career，
job 级只算「这份 JD 相对本 Career 要求，多强调了什么 / 换了什么说法」。

这比每个岗位从 persona 整算一遍 `interview_strategy` 省得多，
也保证同一 Career 内 5 个岗不会讲出 5 套互相矛盾的话。

---

## 3. 三条承重约束

最容易在后续实现里被违反的三条。

### 3.1 Persona 不完备，S2 → S3 是回环

persona 是用户**自己上传的、他觉得做得好的项目集合**。它天然不完备：
- 符合岗位需求但用户根本没写的经历
- 能力足够、但因为表达没对上面试官偏好而失利的情况

项目要补的正是这两步。因此 S4 必须等 S3 之后——S4 在旧 persona 上重排，
只能拿到「重新表述过的已有内容」，拿不到「挖出来的新经历」。

### 3.2 追问问细节，不问确认

「你会 SQL 吗」必然得到「会」，零信息量。要问：

> 最近一次用 SQL 是什么时候、处理了什么表、多大数据量？

编不出来的具体性本身就是防幻觉护栏，比任何 prompt 约束都硬。

- 问题从 gap 反推，每条 gap 出 1–2 个
- 必须指向具体经历，不能指向能力名词
- **「没有」也要记录**：是信息，能防重复追问，也告诉 LLM 哪些是真空白

### 3.3 简历每行可追溯

靠 `source` 字段核对，不靠 prompt 自觉。见 §1。

---

## 4. 数据现状

- `data/boss_jobs.json` — 30 个岗位，覆盖快照，仅保留带 `jd` 的开放岗
- `data/careers.json` — S1 产物：6 个 Career，各带定位、归属判据与成员岗位。
  由 `scripts/build_careers.py` 生成，**人可编辑**，Career 页直接读它展示（见 `tech_doc.md`）
- `data/job_gaps.json` — 30 条单岗位 × persona 的分析（legacy）。
  新框架里 S2 取代它，但 `requirements_deep_dive` 可作 S1 的参考输入

---

## 5. 已知缺失：反馈闭环（S6）

**本期明确不做。**

面试完会知道市场实际问了什么，但目前没有任何东西把它写回 `persona.json`
或 Career 定义。不加投递记录，重跑管线只会得到一模一样的答案。

不做的原因：投递与面试数据尚未产生，现在设计 schema 等于凭空猜形状——
`tech_doc.md` 里作废的 Persona Schema 就是这么来的。

触发条件：S4 / S5 产物落地、且真实跑过一轮投递面试之后。
届时需要的最小记录：job_id、Career、简历版本、走到哪一轮、实际被问了什么。
届时可复用 `job_gaps.json` 已有的 `requirements_deep_dive` 作为对照基线。

---

## 6. 尚未决定（不要自行假设）

- **追问清单的载体**：CLI 脚本 / Chat UI（复用 `backend/chat.py`）/ 手工填 JSON。
  决定 S3 要不要碰 `backend/`，与 S0–S2 无关，可以最后再定。
- **Career 的数量上界**：30 个岗位预计落 4–6 个职能 Career。上界未定，
  影响 S2 和 S4 的调用次数。
- **简历版本管理**：`resumes/{career}.md` 覆盖还是留档。
  （与 `tech_doc.md` 里 `job_gaps.json` 的同一个未决问题同源。）
- **选哪几个 Career 投入 S3/S4**：由人决定，LLM 只给证据。
  Career 多了会做多份没人用的简历。
