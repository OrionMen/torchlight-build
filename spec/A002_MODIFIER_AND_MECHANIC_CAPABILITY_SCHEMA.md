# A002 Modifier 与 Mechanic Capability Schema

- 状态：Frozen v1.0
- 依赖：A001

## 1. Modifier

Modifier 表示一个来源对计算系统的单次写入声明。

必需字段：

```json
{
  "id": "modifier.unique_id",
  "name_zh": "物理技能暴击伤害",
  "description_zh": "对具有物理标签的技能增加暴击伤害。",
  "source": {
    "entity_type": "equipment|hero_trait|skill|support|talent|memory|other",
    "entity_id": "stable.entity.id",
    "location": "可读的节点、词条或槽位说明",
    "original_text": "Wiki 原文"
  },
  "target_node": "stat.critical_damage",
  "aggregation_key": "stat.critical_damage",
  "operation": "add",
  "value": 0.30,
  "scope": {
    "owner": "character|skill_instance|damage_component|target",
    "selector": "当前作用对象说明"
  },
  "filters": {},
  "confidence": 1.0,
  "version": "ss13"
}
```

## 2. Filter 命名空间

### 2.1 技能标签过滤

```json
{
  "skill_tags_all": ["physical", "attack"],
  "skill_tags_any": [],
  "skill_tags_none": []
}
```

标签读取 `SkillContext.effective_tags`。标签可被辅助技能等机制增加或移除。

### 2.2 伤害类型过滤

```json
{
  "damage_types": ["fire"]
}
```

伤害类型读取当前 `DamageComponent.current_type`，不能与技能标签混用。

### 2.3 其他过滤（保留接口）

```json
{
  "skill_ids": [],
  "character_mechanics_all": [],
  "target_conditions_all": [],
  "resource_minimums": {}
}
```

第一版只要求实现 `skill_tags_all/any/none` 和 `damage_types`。

## 3. Calculation Node 与 aggregation_key

- `target_node` 表示写入哪个计算概念。
- `aggregation_key` 表示在该节点内与哪些 Modifier 合并。

示例：

- 全局暴击伤害、物理技能暴击伤害、火焰暴击伤害在过滤成功后都写入 `stat.critical_damage`，并使用同一 `aggregation_key=stat.critical_damage` 相加。
- 三个不同英雄特性的“额外伤害”可以写入 `damage.more`，但使用不同的 `aggregation_key`，组内加减、组间相乘。

## 4. Mechanic Definition

```json
{
  "id": "mechanic.focus_blessing",
  "name_zh": "专注祝福",
  "description_zh": "需要获取来源的可叠层战斗机制。",
  "base_maximum": 4,
  "maximum_node": "mechanic.focus_blessing.maximum",
  "capability_id": "capability.focus_blessing.acquire",
  "assumption_policy": "max_reachable",
  "source_notes_zh": "基础上限来源需在 Knowledge 中记录。",
  "confidence": 0.9,
  "version": "ss13"
}
```

## 5. Capability Contribution

```json
{
  "id": "capability.source.unique_id",
  "mechanic_id": "mechanic.focus_blessing",
  "capability_type": "acquire",
  "source": {
    "entity_type": "skill",
    "entity_id": "stable.entity.id",
    "original_text": "获得专注祝福"
  },
  "filters": {},
  "confidence": 0.9
}
```

任意一个有效 `acquire` 来源即可令 capability 为 true。

## 6. Maximum Modifier

机制上限修改也使用 Modifier：

```json
{
  "target_node": "mechanic.focus_blessing.maximum",
  "aggregation_key": "mechanic.focus_blessing.maximum",
  "operation": "add",
  "value": 2
}
```

## 7. Mechanic Resolution

输出必须包含：

```json
{
  "mechanic_id": "mechanic.focus_blessing",
  "capability_available": true,
  "base_maximum": 4,
  "maximum_delta": 2,
  "effective_maximum": 6,
  "assumed_value": 6,
  "policy": "max_reachable",
  "trace": []
}
```

## 8. Trace

每条参与或被排除的 Modifier 至少记录：

- modifier_id
- source original_text
- matched / rejected
- rejection_reason
- target_node
- aggregation_key
- contributed_value

## 9. 歧义处理

无法确定以下任一字段时，不得生成 confirmed modeled data：

- target_node
- aggregation_key
- filter namespace
- scope owner
- capability type

应生成 research issue 并保留候选解释。
