# Persona Data Structure

> **本文件由 `backend/persona_model.py` 生成，勿手改。**
> 重新生成：`conda run -n echo python -m backend.tools.export_persona_schema`

schema_version: 4

## 设计：只给锚点，内容全自由文本

服务对象是 LLM，不是传统程序。三处锚点：
1. `capabilities[].experience_ids` 引用 `experiences[].id`（能力×经历多对多）。
2. `gaps[].capability` 引用 `capabilities[].id`。
3. `gaps[].target` 引用 `targets[].id`。
LLM 只出名字和文本，id 由后端派生。时间、公司、结果全写进文本。

## 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `capabilities` | array |  |
| `experiences` | array |  |
| `gaps` | array |  |
| `interventions` | array |  |
| `profile` | Profile |  |
| `schema_version` | integer |  |
| `targets` | array |  |

## 示例实例

```yaml
schema_version: "4"
profile:
  current_roles:
    - "数据分析师"
  current_state: "在职，考虑转型"
  preferences:
    location: "上海"
    expected: "300"
    notes: ""
experiences:
  - id: "e-tmall-dashboard"
    text: "2025 年在电商公司搭建日活看板，每日 ETL + 看板维护，日活查询从 2 小时降到 10 分钟。"
  - id: "e-ab-test"
    text: "自述做过 A/B 实验，仅对话提及，未验证。"
capabilities:
  - id: "sql"
    name: "SQL"
    experience_ids:
      - "e-tmall-dashboard"
  - id: "interview-expression"
    name: "面试表达"
    experience_ids: []
targets:
  - id: "t-data-analyst"
    role: "Data Analyst"
    note: "互联网 senior"
  - id: "t-product-analyst"
    role: "Product Analyst"
    note: ""
gaps:
  - id: "g-experiment"
    target: "t-data-analyst"
    capability: "sql"
    note: "能独立跑查询，但没有独立设计过 A/B 实验。critical，先补。"
interventions:
  - id: "i-ab-test"
    action: "独立完成一次 A/B 实验设计到复盘"
    note: "critical gap 且有明确项目载体"
    serves_gaps:
      - "g-experiment"
```

## 一致性检查

`Persona.dangling_refs()` 列出所有悬空引用。
当前示例：**无悬空引用**。
