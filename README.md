# torchlight-build

这是一个以数据为核心的《火炬之光：无限》游戏外配装辅助工具。

## 当前计划

- 抓取并保存游戏资料
- 将网页数据转换为结构化数据
- 对英雄机制进行逐个建模和验证
- 建立通用技能、装备和词条规则
- 实现英雄分析器
- 后续实现配装展示与计算功能

## 当前开发阶段

- 当前只处理英雄数据
- 第一个目标英雄为“狂人·雷恩｜怒火”
- 当前不追求一次性设计完整数据模型
- 采用“先运行、再理解、再调整结构”的方式推进

## 目录说明

- `docs/`：项目研究文档与英雄机制记录
- `crawler/`：后续的数据采集代码
- `app/`：后续的应用功能
- `tests/`：后续的测试用例
- `data/raw/`：网页原始数据
- `data/parsed/`：从网页提取的结构化事实数据
- `data/modeled/`：人工理解和分类后的语义数据
- `data/reports/`：数据处理与验证报告

## Manifest 数据采集

- Manifest 是数据采集的唯一入口。
- Crawler 只负责忠实发现和采集网页数据，不负责解释游戏规则。
- Hero Manifest 包含 27 个唯一条目。
- Help 目录页包含 213 个列表链接，去重后 Help Manifest 包含 203 个唯一条目；重复情况保留在发现报告中。
- SS13 的 27 个英雄特性页面已全部采集并完成忠实结构化解析。
- 全英雄 Source Bundle：`data/exports/TLB_HERO_SOURCE_BUNDLE_SS13_v1.zip`。
- 下一步由 ChatGPT 基于真实 Source Bundle 进行知识审核；当前尚未完成 Knowledge 或 Modeled 数据。

## Tooltip 采集

Codex 只开发和验证 Tooltip 工具；正式批次由用户在本地运行。提取结果忠实保留 Tooltip 出现位置，Definition 只是按内容去重后的候选，不等于 Knowledge Concept。

Hero 缓存提取：

```bash
python3 -m crawler.extract_tooltips --season ss13 --manifest sources/hero_manifest.json --raw-dir data/raw/manifests/hero/raw_html --meta-dir data/raw/manifests/hero/meta --output data/extracted/tooltips/ss13/hero
```

Help 缓存提取：

```bash
python3 -m crawler.extract_tooltips --season ss13 --manifest sources/help_manifest.json --raw-dir data/raw/manifests/help/raw_html --meta-dir data/raw/manifests/help/meta --output data/extracted/tooltips/ss13/help
```

合并、去重与冲突检测：

```bash
python3 -m crawler.merge_tooltips --season ss13 --input data/extracted/tooltips/ss13/hero --input data/extracted/tooltips/ss13/help --output data/extracted/tooltips/ss13/merged
```

构建 Tooltip Source Bundle：

```bash
python3 -m crawler.build_tooltip_bundle --season ss13 --merged-dir data/extracted/tooltips/ss13/merged --occurrence-dir data/extracted/tooltips/ss13/hero --occurrence-dir data/extracted/tooltips/ss13/help --output data/exports/TLB_TOOLTIP_SOURCE_BUNDLE_SS13_v1.zip
```

不同赛季分别输出 `definitions.json`，未来可在独立流程中比较；当前工具不执行跨赛季差异分析。

## 全系统数据源发现

系统发现：

```bash
python3 -m crawler.discover_systems \
  --url https://tlidb.com/cn/ \
  --output sources/system_manifest.json
```

生成单个系统 Manifest：

```bash
python3 -m crawler.discover_system_manifest \
  --system-manifest sources/system_manifest.json \
  --system-id <system_id> \
  --output sources/<system_id>_manifest.json
```

用户本地批量发现：

```bash
./scripts/discover_all_sources.sh
```

本阶段只发现目录与 URL，不下载详情页正文。Manifest 是后续正式抓取的唯一入口；标记为 `candidate` 的系统需要人工确认后，才能进入正式批量发现与抓取。

## 候选系统验证

只生成验证报告：

```bash
./scripts/verify_candidate_systems.sh
```

查看中文摘要：`data/reports/system-discovery/candidate-verification-summary.md`。

应用可信分类：

```bash
./scripts/verify_candidate_systems.sh --apply
```

`--apply` 会先备份原 `sources/system_manifest.json`。验证流程只请求系统入口页，不下载详情页；`needs_review` 项不会自动升级。应用并审核分类后，再运行全系统 Manifest 发现。

## Knowledge Viewer V1

运行：

```bash
cd ~/Documents/torchlight-build
python3 -m http.server 8000
```

浏览器打开：

http://localhost:8000/app/

说明：

- 这是用于审核 27 个英雄特性 Source / Structured 数据的只读内部工具。
- 当前只展示忠实采集的 Source 与网页结构化结果。
- Knowledge、Rule 和 Contribution 尚未建模，界面仅保留明确的空状态。
- 该 Viewer 不代表最终产品界面。

## 导出 AI Source

运行：

```bash
./scripts/export_ai_source.sh
```

默认输出：`Torchlight-ai-source.zip`。

该快照用于提供给 ChatGPT 做项目搜索、数据审核、规则建模和 Code Review。包内包含代码、结构化数据、Tooltip、Knowledge 和报告，但不包含 raw HTML、Git 历史、缓存、环境或凭据。

每次重要开发完成后，可以重新运行脚本并上传新的 AI Source ZIP。

## Local Wiki

旧 Local Wiki MVP 仍保留在 `local_wiki/ss13/pages/` 与 `local_wiki/app/`。

### Full Mirror

Full Mirror 直接以完整 Raw HTML Snapshot 为页面基础，将 Raw Asset Snapshot 复制到本地并执行确定性的 HTML/CSS/内部导航 URL Rewrite。构建过程不会修改 Source Snapshot。

构建：

```bash
./scripts/build_full_wiki_mirror.sh
```

启动：

```bash
./scripts/serve_local_wiki.sh
```

镜像：<http://localhost:8000/local_wiki/ss13/site/cn/>

全文搜索：<http://localhost:8000/local_wiki/ss13/site/_local/search/>

Global Search 作为 Full Mirror 的附加能力保留，搜索结果指向 canonical Mirror Route，并支持命中词高亮。

### Local Mirror Assets

当前资源流程：`Raw HTML → Asset Discovery → Asset Fetch → Full Mirror Build`。

```bash
./scripts/discover_wiki_assets.sh
./scripts/fetch_wiki_assets.sh
```

静态资源正式发现与下载批次由用户在本地运行；Codex 只维护工具和 fixture/mock 测试。下载结果保存在 `data/raw/assets/`，与 Raw HTML 一样作为 Source Snapshot。
