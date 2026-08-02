# TASK A001/A002：静态计算基础骨架

## 目标

严格根据以下冻结文档实现最小静态计算基础：

- `architecture/A001_STATIC_BUILD_CALCULATION_MODEL.md`
- `spec/A002_MODIFIER_AND_MECHANIC_CAPABILITY_SCHEMA.md`
- `tests/spec_cases/A001_A002_static_model_cases.json`

## Fast Mode / Low Token Mode

- 只实现当前任务。
- 不扫描整个仓库。
- 只读取本任务列出的文档、`engine/damage/` 中与 R001 兼容所必需的文件，以及对应测试目录。
- 不修改 R001 冻结规范与现有 R001 行为。
- 不实现 UI、Wiki 抓取、完整词条分类、时间轴或 Runtime Simulator。
- 不安装第三方依赖。
- 不 Git commit / push。

## 必须实现

在合适的新包中实现，优先建议：

```text
engine/static_model/
```

最小能力：

1. `CalculationContext`
   - `effective_skill_tags`
   - `damage_type`

2. `Modifier`
   - 支持 `target_node`、`aggregation_key`、`operation`、`value`、`filters`、source trace。

3. Filter 匹配
   - `skill_tags_all`
   - `skill_tags_any`
   - `skill_tags_none`
   - `damage_types`
   - 标签和伤害类型必须独立判断。

4. Modifier Routing / Aggregation
   - 同一 `target_node + aggregation_key` 的 `add/subtract` 值合并。
   - 不同 aggregation_key 可输出独立组。
   - 提供一个纯函数将独立额外组转换为最终乘数：每组先 `1 + sum(group)`，组间相乘。

5. Mechanic Resolution
   - 输入 `base_maximum`、获取来源列表、maximum modifiers。
   - capability 有效时 assumed value = effective maximum。
   - capability 无效时 assumed value = 0。
   - 上限仍需正常计算并写入 trace。

6. Trace
   - 至少记录 modifier/capability 是否匹配、拒绝原因、目标节点、aggregation key、贡献值和来源原文（若存在）。

7. 中文注释
   - 核心模型和非显然逻辑使用简洁中文 docstring 或注释。

## 测试

创建最小 unittest，覆盖包内五个冻结案例及必要错误场景。

只运行：

```bash
python3 -m unittest discover -s tests/engine -p 'test_*.py'
```

如果该命令会运行仓库中过多既有测试，可将新测试放到独立目录并运行更窄的 discover 命令，同时必须再运行现有 R001 damage tests，确保兼容。

## 文档维护

更新 `PROJECT_STATE.md`，仅追加或最小修改以下状态：

- A001/A002 已冻结并实现
- 当前采用可达最大值静态计算
- 下一步：用狂人词条建立首批 modeled classification samples

不要重写已有内容。

## 完成输出

严格输出：

```text
Installed patch files:
...

Modified code files:
...

Implementation summary:
...

Test result:
command: ...
result: ...

Not executed:
build
lint
full test suite
git commit
git push
```
