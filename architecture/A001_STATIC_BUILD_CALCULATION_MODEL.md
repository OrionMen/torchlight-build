# A001 静态配装计算模型

- 状态：Frozen v1.0
- 日期：2026-08-02
- 范围：第一阶段静态计算，不模拟完整运行时

## 1. 项目定位

Torchlight Build 第一阶段是知识驱动的静态配装计算引擎。它计算当前配装在默认“可达最大值”假设下的理论结果，不模拟移动、命中轨迹、怪物 AI、资源增长时间、状态覆盖率或完整战斗时间轴。

## 2. 核心数据流

```text
Wiki/Help 原文
→ Parsed Text
→ Knowledge Concept
→ Modeled Modifier / Mechanic Capability
→ Filter
→ Calculation Node
→ Static Result + Trace
```

## 3. 核心原则

1. 英雄、装备、技能、辅助、天赋、追忆等实体只提供数据，不直接承担计算。
2. Modifier 必须先经过过滤，再写入 Calculation Node。
3. Skill Tag、Damage Type、Stat 是三类独立概念，禁止互相自动推导。
4. 第一阶段的运行时机制采用“可达最大值静态计算”。
5. 若当前配装具备某机制的有效获取来源，则该机制默认按有效最大值计算；否则按 0 计算。
6. 上限提高词条不等于获取能力。只有上限、没有获取来源时，假设值仍为 0。
7. 每个结果必须可追溯到原文、来源实体、过滤原因和聚合过程。
8. 遇到无法确定的词条不得猜测，必须进入 research issue。

## 4. 第一阶段不实现

- 时间轴
- 投射物命中模拟
- 状态获得速度与衰减
- 覆盖率估算
- 怪物行为
- 玩家手动层数调整
- 快照时机模拟

这些机制可以保留扩展接口，但不得进入当前 UI 或默认计算。

## 5. 可达最大值模型

每个需要先获取的机制统一拆成：

```text
Capability（是否具备获取能力）
Base Maximum（基础上限）
Maximum Modifiers（上限增减）
Effective Maximum（最终上限）
Assumed Value（静态计算采用值）
```

规则：

```text
capability == false → assumed_value = 0
capability == true  → assumed_value = effective_maximum
```

示例：专注祝福基础上限 4，配装提供 +2 上限并存在任一获取来源，则按 6 层计算；若没有获取来源，则按 0 层计算。

## 6. 中文可读性与回溯

所有 Knowledge、Modeled Data 和 Schema 示例必须同时保留：

- 稳定机器 ID
- 中文名称
- 中文说明
- 来源实体
- Wiki/Help 原文
- 设计说明
- 置信度
- 版本
