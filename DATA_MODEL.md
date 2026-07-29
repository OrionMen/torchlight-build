# Data Model

## 数据层级

### Raw

保存原始网页快照。

示例：

`data/raw/heroes/ss13/rehan-anger.html`

### Parsed

保存从网页中提取出的事实数据，不解释游戏语义。

建议字段示例：

- hero_id
- name
- season
- source_url
- source_text
- nodes
- fetched_at

### Modeled

保存人工分类和理解后的语义数据。

当前已确定的最小实体类型：

- Hero
- Attribute
- Status
- Skill
- Rule

## Hero

每个英雄都是完全独立的个体。

英雄必须绑定具体赛季版本。

## Attribute

表示可拥有数值的属性或资源。

当前示例：

- 怒气
- 生命
- 护盾
- 护甲
- 抗性

## Status

表示角色当前是否处于某种状态，或者带持续时间的效果。

当前示例：

- 暴气

## Skill

表示可造成效果、伤害或被触发的技能对象。

当前示例：

- 爆裂

爆裂虽然是英雄专属触发技能，但仍进入统一 Skill 体系。

## Rule

表示实体之间的条件、事件和结果关系。

当前只记录概念，不设计完整 Rule Schema。

每条 Rule 后续需要同时保留：

- 原始描述
- 结构化语义
- 解析状态
- 人工确认状态
