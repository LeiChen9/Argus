# Argus

>See the landscape. Know yourself. Move forward.

Argus 是一个 AI-native Career Development Copilot。

它持续观察招聘市场、理解个人能力与职业目标，并将两者连接起来，帮助用户找到职业发展中的关键差距，制定可执行的成长路径，并通过持续训练逐步接近目标职业。

职业发展是一片复杂而不断变化的大陆。Argus 希望成为用户探索这片大陆时长期同行的工具。

---

## Core Idea

每个人都拥有一个持续变化的 **Career Persona**，由 Experience、Skills、Knowledge、Projects、Domain Expertise、Communication、Career Preferences、Strengths、Weaknesses、Evidence、Goals 构成。

招聘市场同样存在一个持续变化的 **Market Persona**，来自大量真实岗位与招聘信息，包括 Roles、Skills、Experience、Domains、Responsibilities、Seniority、Companies、Industries、Locations、Compensation。

Argus 持续观察二者之间的距离：

```text
                  Career Goal
                       │
                       ▼
               Ideal Career Model
                       │
                 Gap Analysis
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
      Knowledge       Skill       Experience
         Gap           Gap           Gap
         │             │             │
         └─────────────┼─────────────┘
                       ▼
                  Intervention
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
       Learn        Practice        Build
         │             │             │
         └─────────────┼─────────────┘
                       ▼
                  Reassessment
                       │
                       ▼
               Updated Persona
```

目标是找到真正影响职业机会的关键变量，然后用有限的时间解决它们。

---

## What Argus Does

### 1. Understand You

Argus 通过持续对话理解用户，关注的不是简历关键词，而是：

- 做过什么，真正擅长什么，为什么擅长
- 哪些能力有真实证据，哪些只是了解
- 做过哪些有价值的项目，对什么领域有深入理解
- 希望进入什么职业方向，希望工作的环境和条件
- 当前职业发展的约束

最终形成一个具有证据链的 Career Persona：

```text
Claim
  ↓
Evidence
  ↓
Confidence
```

例如：

```text
Skill: Experiment Design
Confidence: High
Evidence:
- Designed A/B experiments
- Defined primary metrics
- Analyzed experiment results
- Made business decisions based on results
```

Persona 会随着新的对话、训练、项目和面试反馈持续更新。

### 2. Observe the Market

Argus 广泛收集招聘市场信息，将不同来源的 JD 统一解析成结构化信息：

```text
Job
├── Role
├── Company
├── Seniority
├── Responsibilities
├── Required Skills
├── Preferred Skills
├── Domain
├── Experience
├── Education
├── Location
└── Compensation
```

大量 JD 经过归一化、去重和聚类后，可以形成更加稳定的职业模型。例如：

```text
Data Analyst
│
├── Growth Analytics
├── Product Analytics
├── Strategy Analytics
├── Risk Analytics
└── Business Intelligence
```

Argus 关注的是招聘市场背后的能力结构。

### 3. Build Career Models

Argus 根据目标职业和真实招聘市场建立 **Ideal Career Model**。一个职业方向可能包含：

- Core Skills
- Domain Knowledge
- Typical Projects
- Expected Experience
- Communication Patterns
- Interview Topics
- Common Career Paths

这些模型来自大量招聘信息、行业资料、项目案例和实际反馈，并持续变化。

### 4. Find the Critical Gaps

Argus 将 Current Persona 与 Ideal Career Model 对比，重点关注：

- **Knowledge Gap**：需要理解的概念、方法和领域知识。
- **Skill Gap**：已经知道概念，但尚未形成稳定能力。
- **Experience Gap**：缺乏可以证明能力的真实项目或案例。
- **Communication Gap**：能力存在，但无法在简历、沟通或面试中有效表达。
- **Interview Gap**：知识和经验具备，但在特定面试场景下表现不足。

Argus 会进一步判断 Gap 的性质：

- Impact：Critical / Important / Minor
- Difficulty：Easy / Moderate / Hard
- Time to Improve：Days / Weeks / Months

这样用户可以把时间投入到真正重要的地方。

### 5. Turn Gaps Into Action

每一个重要 Gap 都应该对应一个 Intervention：

```text
Gap
 ↓
Diagnosis
 ↓
Action
 ↓
Practice
 ↓
Evidence
 ↓
Reassessment
```

Intervention 可以包括：

- 学习一个特定领域，阅读指定资料，分析真实案例
- 完成一个项目，修改项目表达
- 练习特定类型的面试题，进行模拟面试
- 重新组织简历中的证据
- 准备针对特定岗位的沟通材料

Argus 更关注完成之后发生了什么变化。

### 6. Prepare for Real Opportunities

当用户开始接近目标职业模型后，Argus 可以针对真实岗位提供具体准备：

```text
Job
 ↓
Candidate Fit
 ↓
Strengths
 ↓
Risks
 ↓
Gaps
 ↓
Preparation
```

生成：

- **Resume**：突出与岗位最相关的真实经历和证据。
- **Outreach**：生成符合岗位和个人背景的沟通内容。
- **Learning**：针对岗位要求补充必要知识。
- **Practice**：针对岗位和个人短板生成训练内容。
- **Interview**：生成可能出现的面试问题，并根据用户的回答继续训练。

---

## The Career Loop

Argus 的核心工作循环：

```text
Observe
    ↓
Understand
    ↓
Model
    ↓
Diagnose
    ↓
Intervene
    ↓
Practice
    ↓
Measure
    ↓
Update
    ↺
```

用户每一次行为都可能产生新的信息：学习、项目、练习、投递、面试、拒绝、通过、Offer。这些反馈进入 Persona，进一步改变下一轮建议。

因此 Career Persona 是一个动态状态，而不是一份静态档案。

---

## MVP

Argus 的第一阶段聚焦于验证核心闭环。

### Phase 1

**Candidate Persona**

通过聊天建立：Career Goal、Experience、Skills、Projects、Strengths、Weaknesses、Preferences、Evidence。

**Job Intelligence**

收集一批真实 JD：

```text
Collect
 ↓
Parse
 ↓
Normalize
 ↓
Deduplicate
 ↓
Cluster
```

**Career Gap Analysis**

建立：

```text
Current Persona
         ↓
Ideal Career Model
         ↓
Gap Analysis
```

**Career Plan**

针对关键 Gap 给出：

```text
Priority
 ↓
Why
 ↓
What to Learn
 ↓
What to Practice
 ↓
What to Build
```

**Interview Preparation**

根据 Persona + Career Model + Specific JD 生成针对性的面试问题。

第一阶段重点验证：用户是否能通过 Argus 更清楚地理解自己的职业位置，并知道下一步最值得做什么。

---

## Architecture

早期版本保持简单。

```text
                     ┌───────────────┐
                     │   User Chat   │
                     └───────┬───────┘
                             │
                             ▼
                     ┌───────────────┐
                     │ Persona Engine│
                     └───────┬───────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         User Evidence    Career Goal    Preferences
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                     ┌───────────────┐
                     │ Career Model  │
                     └───────┬───────┘
                             ▲
                             │
                     ┌───────┴───────┐
                     │ Job Intelligence│
                     └───────┬───────┘
                             │
                        Job Sources
                             │
                             ▼
                     ┌───────────────┐
                     │ Gap Analysis  │
                     └───────┬───────┘
                             │
                             ▼
                     ┌───────────────┐
                     │ Intervention  │
                     └───────┬───────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
           Learning       Practice       Interview
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                        New Evidence
                             │
                             └──────────────► Persona
```

---

## Design Principles

- **Evidence First**：职业判断尽可能建立在具体证据上。Claim → Evidence → Confidence。避免仅凭对话中的印象给用户贴标签。
- **Market Grounded**：Career Model 来自真实招聘市场和行业资料。
- **Actionable**：每一次分析都应该能够产生下一步行动。
- **Small Interventions**：优先解决能够在较短时间内显著改善职业机会的关键问题。
- **Continuous**：Persona、Career Model 和 Career Plan 都是动态的。
- **Human in the Loop**：用户始终参与重要的职业选择和行动决策。

---

## Long-Term Vision

Argus 希望逐渐形成一个完整的 Career Intelligence System：

```text
Personal Intelligence
         ×
Market Intelligence
         ×
Learning
         ×
Practice
         ×
Real-world Feedback
```

最终，用户可以在 Argus 中持续回答几个核心问题：

- Where am I?
- Where can I go?
- What stands between me and there?
- What is worth fixing?
- What should I do this week?
- Am I getting better?

Argus 持续观察世界，也持续理解你。

一百只眼睛，看见职业世界。
一步一步，陪你走进去。
```