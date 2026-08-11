# Project State

## 当前阶段

SS13 Full Local Mirror + Global Search。

## 当前赛季

SS13。

## 当前目标

基于 SS13 Raw Snapshot 改善本地阅读与跨系统全文搜索；配装模拟器功能暂缓。

## 已完成

- 创建 GitHub 私有仓库
- 完成本地 Clone
- 确定项目采用数据优先的开发方式
- 初始化项目目录和长期维护文档
- 完成“狂人·雷恩｜怒火”的原始网页采集
- 完成首版英雄事实数据解析
- 生成首版解析校验报告
- 完成 Hero Viewer v0.1
- 可以在浏览器中查看“狂人·雷恩｜怒火”的 parsed 数据
- 完成 R001 命中伤害原型实现
- R001 聚焦单元测试已通过
- A001/A002 已冻结并实现
- 当前采用可达最大值静态计算
- 建立 Manifest 驱动的数据源发现与采集基础设施
- Hero Manifest 包含 27 个唯一条目
- Help 目录页 213 个链接去重后形成 203 个唯一条目
- 完成 Hero Manifest 前 2 条抓取烟雾验证
- 完成 Hero Manifest 全部 27 个英雄特性页面采集
- 完成 27 个英雄页面的忠实结构化解析
- 生成 `data/exports/TLB_HERO_SOURCE_BUNDLE_SS13_v1.zip`，成功 27，失败 0
- Knowledge Viewer V1 已实现，可审核 27 个英雄的 Source / Structured 数据
- Slice 001 Knowledge 已完成
- Slice 001 Rule 与 Contribution Template 已完成
- `resource.rage.base_maximum` 已由 Tooltip Definition 解析为 100
- Slice 001 尚未接入 Engine
- Tooltip 提取、去重、冲突检测与 Source Bundle 工具已完成
- Hero Tooltip 扫描完成：1356 occurrences
- Hero Tooltip 去重完成：106 definitions
- Hero Tooltip conflicts：0
- 当前已知静态案例：Anger 页面“怒气”Tooltip
- Slice 001 已生成两条真实 Contribution
- Slice 002 Knowledge Review 已完成
- `resource.rage` 达到有效上限时自动激活 `state.berserk`
- `max_reachable_default` 静态配置下暴气解析为 Active
- 怒气耗尽时退出暴气已记录为 Runtime Rule，尚未计算
- Slice 002 尚未模拟怒气随时间变化，尚未接入 Engine
- Slice 003 Knowledge Review 已完成
- 暴气不修改真实怒气当前值或有效上限
- 暴气将怒气收益计算基数解析为有效怒气上限的 2 倍，当前为 200
- Slice 001 默认暴气场景解析为 44% 额外伤害和 20% 移动速度
- 原 22% / 10% 未暴气结果作为互斥对照保留
- Slice 003 尚未接入 Engine，尚未处理其他依赖怒气的词条
- AI Source 导出工作流已建立
- 后续用户不再需要手工寻找单个数据文件
- ChatGPT 可基于完整 AI Source ZIP 自行搜索和定位
- Hero 和 Help Manifest 已存在
- TLIDB 全系统发现与通用系统 Manifest 工具已建立
- 正式系统发现由用户本地运行，Codex 不运行长时间正式批次
- 当前有 31 个候选系统入口待验证
- 候选系统批量验证、分类、预览与审计报告工具已建立
- 候选验证只访问系统入口页，不下载详情页
- SS13 Raw Snapshot 已完成
- Local Wiki MVP 已完成，可从 Raw 重新构建 3921 个本地页面
- Global Search 已覆盖当前 30 个 confirmed 系统
- Local Mirror Asset Discovery 与断点续传 Fetch 工具已建立
- SS13 Raw HTML Snapshot 已完成：3921 页
- SS13 Asset Snapshot 已完成：4229 / 4229
- Asset Discovery 已收敛，Frontend Dependency Readiness 为 `ready_with_minor_gaps`
- Full Mirror Builder v1 已完成，保留完整 Raw HTML DOM 并本地化静态资源

## 进行中

- 验收 Full Mirror v1 的 canonical route 冲突与未解析内部链接
- 保留 Global Search 作为 Mirror 附加能力
- Knowledge 与 Build Simulator 后续建立在 Local Wiki 数据之上

## 下一步

1. 浏览并核对首个英雄数据
2. 修正展示或解析问题
3. 创建首版 modeled JSON
4. 再扩展到其他英雄的数据采集
5. 继续细化额外伤害分组，并在后续实现其他击中机制
6. 用狂人词条建立首批 modeled classification samples
7. 按 Manifest 生成统一 Source Bundle
8. 由 ChatGPT 基于真实 Source Bundle 进行知识审核
9. 对 Anger 的真实 effect 进行 Knowledge Review
10. 用户运行 `scripts/discover_all_sources.sh` 并确认全部系统入口
11. 根据确认结果逐系统开发 Parser 和 Source Bundle
12. 当前不进行正式全系统 Manifest 生成
13. 优先完善 Local Wiki 页面阅读与 Global Search
14. 建立后续赛季 Raw Snapshot 更新流程
15. Local Wiki 稳定后再继续 Knowledge 与 Build Simulator
16. Full Mirror v1 稳定后再推进 Knowledge、Build Simulator 与 Damage Engine

## 当前原则

- tlidb 中的 27 个英雄条目全部视为相互独立的英雄
- 不建立职业、人物或英雄特性之间的父子关系
- 每个英雄单独分析、单独建模、单独调试
- 英雄数据按赛季版本化
- 旧赛季数据永不覆盖
- 英雄发生重大重做时，视为新的英雄实现
- 原始数据、解析数据和人工建模数据分层保存
- JSON 文本数据作为 Source of Truth
- SQLite 将来只作为自动生成的查询产物
- 当前先让项目跑起来，再逐步调整数据结构
- Manifest 是数据采集的唯一入口
- Crawler 只负责忠实采集，不负责解释游戏规则
- 当前仅完成 Slice 001、Slice 002 与 Slice 003 的局部 Knowledge Review，尚未完成完整 Knowledge 或 Modeled 数据
- 当前阶段不继续扩展 Engine 或 Knowledge Slice
- Engine、Viewer 与 Knowledge 暂停扩展
