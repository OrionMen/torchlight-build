"use strict";

const MANIFEST_URL = "/sources/hero_manifest.json";
const STRUCTURED_ROOT = "/data/structured/heroes/ss13";
const DEFAULT_TRAIT = "Anger";
const KNOWLEDGE_REVIEW_PATHS = {
  "ss13.hero.Anger.node.0.level.1.effect.2": "/knowledge/review/hero/Anger/slice_001.json",
  "ss13.hero.Anger.node.0.level.1.effect.3": "/knowledge/review/hero/Anger/slice_002.json",
};
const SUPPLEMENTAL_REVIEW_PATHS = {
  "hero.Anger.slice_003": "/knowledge/review/hero/Anger/slice_003.json",
};

const state = {
  manifest: [],
  groups: [],
  expandedGroups: new Set(),
  selectedTrait: DEFAULT_TRAIT,
  currentEntry: null,
  currentData: null,
  selectedEffect: null,
  openNodes: new Set(),
  knowledgeReviews: new Map(),
  loadToken: 0,
  loadError: null,
};

function byId(id) {
  return document.getElementById(id);
}

function create(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function displayValue(value) {
  return value === null || value === undefined || value === "" ? "未提供" : String(value);
}

function validUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function linkNode(label, value) {
  const href = validUrl(value);
  if (!href) return create("span", "", displayValue(label || value));
  const link = create("a", "", label || href);
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function splitName(name) {
  const raw = typeof name === "string" ? name : "";
  const separator = raw.indexOf("|");
  if (separator < 0) return { hero: "未分组", trait: raw || "未命名" };
  return {
    hero: raw.slice(0, separator).trim() || "未分组",
    trait: raw.slice(separator + 1).trim() || "未命名",
  };
}

function groupEntries(entries) {
  const groups = new Map();
  entries.forEach((entry) => {
    const names = splitName(entry.name_zh);
    const enriched = { ...entry, heroName: names.hero, traitName: names.trait };
    if (!groups.has(names.hero)) groups.set(names.hero, []);
    groups.get(names.hero).push(enriched);
  });
  return Array.from(groups, ([heroName, traits]) => ({ heroName, traits }));
}

function countEffects(data) {
  return (data.nodes || []).reduce(
    (total, node) => total + (node.levels || []).reduce(
      (levelTotal, level) => levelTotal + (level.effects || []).length,
      0
    ),
    0
  );
}

function firstEffect(data) {
  for (const node of data.nodes || []) {
    for (const level of node.levels || []) {
      if (Array.isArray(level.effects) && level.effects.length) {
        return { effect: level.effects[0], node, level };
      }
    }
  }
  return null;
}

function renderTree() {
  const tree = byId("hero-tree");
  const query = byId("hero-search").value.trim().toLocaleLowerCase("zh-CN");
  tree.replaceChildren();
  let visibleCount = 0;

  state.groups.forEach((group) => {
    const traits = group.traits.filter((entry) => {
      const haystack = `${entry.heroName} ${entry.traitName} ${entry.slug || entry.id}`.toLocaleLowerCase("zh-CN");
      return !query || haystack.includes(query);
    });
    if (!traits.length) return;
    visibleCount += traits.length;

    const section = create("section", "hero-group");
    const expanded = query ? true : state.expandedGroups.has(group.heroName);
    const toggle = create("button", "group-toggle");
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.append(
      create("span", "group-chevron", expanded ? "▼" : "▶"),
      create("span", "group-name", group.heroName),
      create("span", "group-count", traits.length)
    );
    toggle.addEventListener("click", () => {
      if (state.expandedGroups.has(group.heroName)) state.expandedGroups.delete(group.heroName);
      else state.expandedGroups.add(group.heroName);
      renderTree();
    });
    section.appendChild(toggle);

    const list = create("div", "trait-list");
    list.hidden = !expanded;
    traits.forEach((entry) => {
      const button = create("button", "trait-item");
      button.type = "button";
      button.dataset.traitId = entry.id;
      button.classList.toggle("selected", entry.id === state.selectedTrait);
      button.setAttribute("aria-current", entry.id === state.selectedTrait ? "page" : "false");
      button.append(
        create("span", "trait-name", entry.traitName),
        create("span", "trait-slug", entry.slug || entry.id)
      );
      button.addEventListener("click", () => loadTrait(entry));
      list.appendChild(button);
    });
    section.appendChild(list);
    tree.appendChild(section);
  });

  byId("search-count").textContent = `显示 ${visibleCount} / ${state.manifest.length} 条特性`;
  if (!visibleCount) tree.appendChild(create("p", "inline-state", "没有匹配的英雄特性。"));
}

function renderDefinitionList(container, pairs) {
  container.replaceChildren();
  pairs.forEach(([label, value, type]) => {
    container.appendChild(create("dt", "", label));
    const item = create("dd", "");
    if (type === "link") item.appendChild(linkNode(value, value));
    else item.textContent = displayValue(value);
    container.appendChild(item);
  });
}

function renderInspectorList(container, pairs) {
  container.replaceChildren();
  pairs.forEach(([label, value, className]) => {
    const row = create("div", "");
    row.append(create("dt", "", label), create("dd", className || "", displayValue(value)));
    container.appendChild(row);
  });
}

function structuredPath(entry) {
  return `${STRUCTURED_ROOT}/${encodeURIComponent(entry.slug || entry.id)}.json`;
}

function displayIdentifier(value) {
  return String(value || "")
    .split(/[._]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function isStateResolutionReview(review) {
  return Boolean(review && review.rule && review.rule.rule_type === "resource_threshold_state_activation");
}

function bonusBasisReview(review) {
  if (!review || review.effect_id !== "ss13.hero.Anger.node.0.level.1.effect.2") return null;
  return state.knowledgeReviews.get("hero.Anger.slice_003") || null;
}

async function loadKnowledgeReviews(entry) {
  const reviews = new Map();
  const prefix = `ss13.hero.${entry.id}.`;
  const configured = Object.entries(KNOWLEDGE_REVIEW_PATHS).filter(([effectId]) => effectId.startsWith(prefix));
  for (const [effectId, path] of configured) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`Knowledge review ${path}：HTTP ${response.status}`);
    const review = await response.json();
    if (review.effect_id !== effectId) throw new Error(`Knowledge review effect_id 不一致：${path}`);
    reviews.set(effectId, review);
  }
  const supplementalPrefix = `hero.${entry.id}.`;
  const supplemental = Object.entries(SUPPLEMENTAL_REVIEW_PATHS).filter(([sliceId]) => sliceId.startsWith(supplementalPrefix));
  for (const [sliceId, path] of supplemental) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`Knowledge review ${path}：HTTP ${response.status}`);
    const review = await response.json();
    if (review.slice_id !== sliceId) throw new Error(`Knowledge review slice_id 不一致：${path}`);
    reviews.set(sliceId, review);
  }
  return reviews;
}

function renderKnowledge(review) {
  const container = byId("knowledge-content");
  container.replaceChildren();
  if (!review) {
    const empty = create("div", "empty-section");
    empty.append(
      create("strong", "", "尚未建模"),
      create("p", "", "该 effect 尚无人工 Knowledge Review。")
    );
    container.appendChild(empty);
    return;
  }

  if (isStateResolutionReview(review)) {
    const concepts = create("div", "review-card-list");
    ((review.knowledge && review.knowledge.concepts) || []).forEach((concept) => {
      const card = create("article", "review-card");
      card.appendChild(create("h3", "review-card-title", concept.name_zh));
      const fields = create("dl", "field-grid");
      renderDefinitionList(fields, [
        ["Concept", concept.concept_id],
        ["类型", concept.concept_type === "resource" ? "资源" : concept.concept_type === "state" ? "状态" : displayIdentifier(concept.concept_type)],
      ]);
      card.appendChild(fields);
      concepts.appendChild(card);
    });
    container.append(create("h3", "knowledge-subheading", "Concepts"), concepts);
    const relation = create("div", "contribution-note", "怒气达到有效上限时，自动激活暴气状态");
    container.append(create("h3", "knowledge-subheading", "Relation"), relation);
    const runtimeRule = Array.isArray(review.runtime_rules) ? review.runtime_rules[0] : null;
    const runtimeFields = create("dl", "field-grid");
    renderDefinitionList(runtimeFields, [
      ["已识别 Runtime 规则", runtimeRule ? `${runtimeRule.condition_zh}时，${runtimeRule.effect_zh}` : "无"],
      ["当前处理", "仅记录，不进行时间轴模拟"],
    ]);
    container.append(create("h3", "knowledge-subheading", "Runtime Notes"), runtimeFields);
    container.appendChild(create("h3", "knowledge-subheading", "Notes"));
    const notes = create("ul", "knowledge-notes");
    (review.notes || []).forEach((note) => notes.appendChild(create("li", "", note)));
    container.appendChild(notes);
    return;
  }

  const knowledge = review.knowledge || {};
  const summary = create("dl", "field-grid knowledge-summary");
  renderDefinitionList(summary, [
    ["Resource", knowledge.resource_name_zh],
    ["Rule Type", displayIdentifier(knowledge.rule_type)],
  ]);
  container.appendChild(summary);

  const outputsHeading = create("h3", "knowledge-subheading", "Outputs");
  const outputs = create("div", "knowledge-outputs");
  (knowledge.outputs || []).forEach((output, index) => {
    const card = create("article", "knowledge-output");
    const title = create("div", "knowledge-output-title");
    title.append(
      create("span", "knowledge-output-index", ["①", "②", "③", "④", "⑤"][index] || `${index + 1}.`),
      create("strong", "", displayIdentifier(output.target))
    );
    const value = Number(output.coefficient);
    card.append(
      title,
      create("p", "", `每1${knowledge.resource_name_zh}：+${Number.isFinite(value) ? value.toFixed(2) : displayValue(output.coefficient)}%`)
    );
    outputs.appendChild(card);
  });
  container.append(outputsHeading, outputs);

  const resolution = review.concept_resolution;
  if (resolution) {
    container.appendChild(create("h3", "knowledge-subheading", "Concept Resolution"));
    const source = review.rule && review.rule.input && review.rule.input.resolution_source
      ? review.rule.input.resolution_source
      : {};
    const resolutionFields = create("dl", "field-grid concept-resolution");
    renderDefinitionList(resolutionFields, [
      ["概念", resolution.concept_name_zh],
      ["属性", resolution.property === "base_maximum" ? "基础上限" : displayIdentifier(resolution.property)],
      ["解析值", `${displayValue(resolution.resolved_value)} 点`],
      ["来源", "Tooltip Definition"],
      ["Definition ID", resolution.source_definition_id],
      ["引用次数", source.occurrence_count],
      ["引用页面", (source.source_entity_ids || []).join("、")],
      ["来源原文", resolution.source_text_zh],
    ]);
    const sourceText = resolutionFields.lastElementChild;
    if (sourceText) sourceText.classList.add("source-text-multiline");
    container.appendChild(resolutionFields);
  }

  const basisReview = bonusBasisReview(review);
  if (basisReview) {
    const basisRule = basisReview.rule || {};
    const basisFields = create("dl", "field-grid");
    renderDefinitionList(basisFields, [
      ["状态", "暴气"],
      ["影响", "修改怒气收益计算基数"],
      ["真实怒气当前值", "100"],
      ["有效怒气上限", basisRule.input && basisRule.input.resolved_value],
      ["怒气收益计算基数", basisRule.output && basisRule.output.resolved_value],
    ]);
    container.append(create("h3", "knowledge-subheading", "Slice 003 · Berserk Bonus Basis"), basisFields);
    container.appendChild(create("div", "contribution-note", "真实怒气值没有变为 200。200 仅用于计算“基于怒气获得的加成”。"));
  }

  container.appendChild(create("h3", "knowledge-subheading", "Notes"));
  const notes = create("ul", "knowledge-notes");
  (review.notes || []).forEach((note) => notes.appendChild(create("li", "", note)));
  container.appendChild(notes);
}

function renderPending(container, message) {
  container.replaceChildren();
  const empty = create("div", "empty-section");
  empty.append(create("strong", "", "Pending"), create("p", "", message));
  container.appendChild(empty);
}

function valueSourceLabel(value) {
  if (value === "static_max_reachable_assumption") return "可达最大值静态假设";
  return displayIdentifier(value) || "未提供";
}

function renderRule(review) {
  const container = byId("rule-content");
  const rule = review && review.rule;
  if (!rule) {
    renderPending(container, "尚未定义 Rule。");
    return;
  }

  if (isStateResolutionReview(review)) {
    const evaluation = review.static_evaluation || {};
    const condition = rule.condition || {};
    container.replaceChildren();
    const summary = create("dl", "field-grid review-summary");
    renderDefinitionList(summary, [
      ["规则类型", "资源阈值激活状态"],
      ["Evaluation Mode", "Static"],
      ["条件结果", evaluation.condition_result ? "成立" : "不成立"],
      ["自动进入", rule.automatic ? "是" : "否"],
      ["依据", "原文明确写明“自动进入暴气状态”"],
      ["结果", `${rule.effect && rule.effect.target_name_zh ? rule.effect.target_name_zh : "状态"} = ${evaluation.condition_result ? "Active" : "Inactive"}`],
    ]);
    container.appendChild(summary);
    const threshold = create("div", "threshold-condition");
    threshold.append(
      create("span", "threshold-value", `当前怒气 ${displayValue(condition.left_value)}`),
      create("strong", "condition-operator", "≥"),
      create("span", "threshold-value", `有效怒气上限 ${displayValue(condition.right_value)}`)
    );
    container.appendChild(threshold);
    return;
  }

  container.replaceChildren();
  const input = rule.input || {};
  const summary = create("dl", "field-grid review-summary");
  const resolved = input.resolution_status === "resolved";
  renderDefinitionList(summary, [
    ["状态", resolved ? "Resolved" : displayIdentifier(rule.status)],
    ["输入", input.name_zh],
    ["输入来源", valueSourceLabel(input.value_source)],
    ["当前值", input.resolved_value === null || input.resolved_value === undefined ? "尚未解析" : `${input.resolved_value} 点`],
    ["解析状态", displayIdentifier(input.resolution_status)],
    ["来源依据", input.resolution_source ? `${input.resolution_source.title_zh} Tooltip 定义` : "未提供"],
    ["步长", `每 ${displayValue(input.step)} 点${displayValue(input.name_zh)}`],
  ]);
  container.appendChild(summary);
  container.appendChild(create("h3", "knowledge-subheading", "输出规则"));

  const outputs = create("div", "review-card-list");
  (rule.outputs || []).forEach((output, index) => {
    const card = create("article", "review-card");
    card.appendChild(create("h3", "review-card-title", `${index + 1}. ${displayValue(output.target_name_zh)}`));
    card.appendChild(create("p", "review-formula", `${displayValue(input.name_zh)}值 × ${displayValue(output.display_coefficient)}`));
    const fields = create("dl", "field-grid mono-values");
    renderDefinitionList(fields, [
      ["target node", output.target_node],
      ["aggregation key", output.aggregation_key],
    ]);
    card.appendChild(fields);
    outputs.appendChild(card);
  });
  container.appendChild(outputs);

  const basisReview = bonusBasisReview(review);
  if (basisReview) {
    const basisRule = basisReview.rule || {};
    const basisFields = create("dl", "field-grid");
    renderDefinitionList(basisFields, [
      ["条件", "暴气 = Active"],
      ["计算", `有效怒气上限 ${basisRule.input.resolved_value} × ${basisRule.operation.multiplier}`],
      ["结果", `怒气收益计算基数 = ${basisRule.output.resolved_value}`],
      ["Evaluation Mode", "Static"],
    ]);
    container.append(create("h3", "knowledge-subheading", "Slice 003 · 暴气收益基数规则"), basisFields);
  }
}

function contributionStatusLabel(status) {
  if (status === "waiting_for_input") return "等待输入";
  return displayIdentifier(status) || "Pending";
}

function scenarioResultCard(scenario, heading) {
  const card = create("article", "review-card scenario-card");
  card.appendChild(create("h3", "review-card-title", heading));
  const fields = create("dl", "field-grid");
  const contributions = Array.isArray(scenario.resolved_contributions) ? scenario.resolved_contributions : [];
  renderDefinitionList(fields, [
    ["额外伤害", contributions.find((item) => item.target_node === "damage.more")?.display_value],
    ["移动速度", contributions.find((item) => item.target_node === "stat.movement_speed")?.display_value],
    ["计算基数", scenario.rage_bonus_evaluation_value],
    ["来源", scenario.source_slice_id ? "Slice 003 暴气双倍最大怒气收益" : "Slice 001 普通满怒求值"],
  ]);
  card.appendChild(fields);
  return card;
}

function renderContribution(review) {
  const container = byId("contribution-content");
  if (isStateResolutionReview(review)) {
    const resolvedState = review.static_evaluation && Array.isArray(review.static_evaluation.resolved_states)
      ? review.static_evaluation.resolved_states[0]
      : null;
    container.replaceChildren();
    const fields = create("dl", "field-grid");
    renderDefinitionList(fields, [
      ["Type", "State Resolution"],
      ["状态", resolvedState && resolvedState.state_name_zh],
      ["结果", resolvedState && resolvedState.value === "active" ? "Active" : displayIdentifier(resolvedState && resolvedState.value)],
      ["激活原因", resolvedState && resolvedState.reason_zh],
      ["Calculation Node", "无"],
    ]);
    container.appendChild(fields);
    container.appendChild(create("div", "contribution-note", "该状态解析结果可供后续“暴气状态下”规则使用。"));
    return;
  }
  if (review && Array.isArray(review.evaluation_scenarios) && review.scenario_resolution) {
    const selectedId = review.scenario_resolution.selected_scenario;
    const selected = review.evaluation_scenarios.find((item) => item.scenario_id === selectedId);
    const alternative = review.evaluation_scenarios.find((item) => item.scenario_id !== selectedId);
    container.replaceChildren();
    container.appendChild(create("div", "scenario-selected-label", "默认采用：暴气激活"));
    if (selected) container.appendChild(scenarioResultCard(selected, selected.name_zh || "暴气激活"));
    const details = create("details", "scenario-comparison");
    details.appendChild(create("summary", "", "未应用暴气收益倍率（互斥对照）"));
    if (alternative) details.appendChild(scenarioResultCard(alternative, alternative.name_zh || "未暴气"));
    container.appendChild(details);
    const notice = create("ul", "knowledge-notes scenario-notes");
    [
      "两组结果不会同时累加。",
      "当前默认采用暴气场景。",
      "44% 是独立额外伤害组贡献，不等于最终总伤害提升。",
    ].forEach((item) => notice.appendChild(create("li", "", item)));
    container.appendChild(notice);
    return;
  }
  const resolved = review && Array.isArray(review.resolved_contributions)
    ? review.resolved_contributions
    : [];
  const templates = review && Array.isArray(review.contribution_templates)
    ? review.contribution_templates
    : [];
  if (!resolved.length && !templates.length) {
    renderPending(container, "尚未生成 Contribution。");
    return;
  }

  container.replaceChildren();
  const cards = create("div", "review-card-list");
  (resolved.length ? resolved : templates).forEach((contribution) => {
    const card = create("article", "review-card");
    card.appendChild(create("h3", "review-card-title", contribution.target_name_zh));
    const fields = create("dl", "field-grid");
    const rows = resolved.length ? [
      ["结果", contribution.display_value],
      ["公式", contribution.derivation && contribution.derivation.formula_zh],
      ["Calculation Node", contribution.target_node],
      ["Aggregation Key", contribution.aggregation_key],
      ["来源 effect", contribution.source_effect_id],
      ["状态", displayIdentifier(contribution.status)],
    ] : [
      ["当前状态", contributionStatusLabel(contribution.status)],
      ["公式", contribution.formula_zh],
      ["当前结果", contribution.resolved_value === null || contribution.resolved_value === undefined ? "尚未计算" : contribution.resolved_value],
      ["来源", contribution.source_effect_id],
      ["Calculation Node", contribution.target_node],
    ];
    renderDefinitionList(fields, rows);
    card.appendChild(fields);
    cards.appendChild(card);
  });
  container.appendChild(cards);

  if (resolved.length) {
    const notice = create("div", "contribution-note");
    notice.textContent = "22% 表示该独立额外伤害组的贡献，不代表角色最终总伤害提升。";
    container.appendChild(notice);
  } else {
    const blocking = (review.unresolved_inputs || []).filter((item) => item.blocking);
    if (!blocking.length) return;
    const notice = create("div", "blocking-notice");
    notice.append(
      create("strong", "", "阻塞项："),
      create("p", "", `${blocking.map((item) => item.name_zh).join("、")}尚未确认，因此不能生成最终贡献值。`)
    );
    container.appendChild(notice);
  }
}

function appendTraceSteps(container, steps) {
  const trace = create("ol", "trace-list");
  steps.forEach(([label, value, fullValue]) => {
    const item = create("li", "trace-step");
    const valueNode = create("span", "trace-value", value);
    if (fullValue) valueNode.title = fullValue;
    item.append(create("span", "trace-label", label), valueNode);
    trace.appendChild(item);
  });
  container.appendChild(trace);
}

function renderTrace(review, effect, node) {
  const container = byId("trace-content");
  const basisReview = bonusBasisReview(review);
  if (basisReview) {
    const basisRule = basisReview.rule || {};
    const selectedId = review.scenario_resolution && review.scenario_resolution.selected_scenario;
    const selected = (review.evaluation_scenarios || []).find((item) => item.scenario_id === selectedId);
    const contributions = selected && Array.isArray(selected.resolved_contributions) ? selected.resolved_contributions : [];
    container.replaceChildren();
    const branches = create("div", "trace-branches");
    const tooltipBranch = create("section", "trace-branch");
    tooltipBranch.appendChild(create("h3", "trace-branch-title", "暴气 Tooltip Definition"));
    appendTraceSteps(tooltipBranch, [
      ["Definition", basisReview.source.definition_id.slice(0, 31) + "…", basisReview.source.definition_id],
      ["State Description", basisReview.source.original_text_zh.split("\n")[0]],
    ]);
    const dependencyBranch = create("section", "trace-branch");
    dependencyBranch.appendChild(create("h3", "trace-branch-title", "Slice Dependencies"));
    appendTraceSteps(dependencyBranch, [
      ["Slice 002", "state.berserk = Active"],
      ["Slice 001", `rage.effective_maximum = ${basisRule.input.resolved_value}`],
    ]);
    branches.append(tooltipBranch, dependencyBranch);
    container.appendChild(branches);

    const merge = create("section", "trace-merge");
    merge.appendChild(create("h3", "trace-branch-title", "Berserk Bonus Basis Rule"));
    appendTraceSteps(merge, [
      ["Basis Rule", basisRule.rule_id],
      ["Calculation", `${basisRule.input.resolved_value} × ${basisRule.operation.multiplier}`],
      ["Resolved Value", `resource.rage.bonus_evaluation_value = ${basisRule.output.resolved_value}`],
      ["Slice 001 Per Resource Rule", `${basisRule.output.resolved_value} × 0.22% → ${contributions.find((item) => item.target_node === "damage.more")?.display_value} damage.more`],
      ["Slice 001 Per Resource Rule", `${basisRule.output.resolved_value} × 0.10% → ${contributions.find((item) => item.target_node === "stat.movement_speed")?.display_value} movement speed`],
      ["Engine", "尚未接入"],
    ]);
    container.appendChild(merge);
    return;
  }
  if (isStateResolutionReview(review)) {
    const evaluation = review.static_evaluation || {};
    const resolutions = Array.isArray(review.concept_resolutions) ? review.concept_resolutions : [];
    const rageResolution = resolutions.find((item) => item.concept_id === "resource.rage") || {};
    const berserkResolution = resolutions.find((item) => item.concept_id === "state.berserk") || {};
    const resolvedState = Array.isArray(evaluation.resolved_states) ? evaluation.resolved_states[0] : null;
    container.replaceChildren();

    const branches = create("div", "trace-branches");
    const dependencyBranch = create("section", "trace-branch");
    dependencyBranch.appendChild(create("h3", "trace-branch-title", "Slice 001 依赖"));
    appendTraceSteps(dependencyBranch, [
      ["Dependency", (review.provenance.dependencies || []).join("、")],
      ["当前怒气", evaluation.current_rage],
      ["Rage Tooltip Definition", `${(rageResolution.source_definition_id || "未提供").slice(0, 31)}…`, rageResolution.source_definition_id],
      ["有效怒气上限", evaluation.effective_maximum_rage],
    ]);
    const effectBranch = create("section", "trace-branch");
    effectBranch.appendChild(create("h3", "trace-branch-title", "Hero effect 来源"));
    appendTraceSteps(effectBranch, [
      ["Effect", effect.effect_id],
      ["Original Text", effect.text],
      ["Rule", review.rule.rule_id],
    ]);
    branches.append(dependencyBranch, effectBranch);
    container.appendChild(branches);

    const tooltip = create("section", "trace-merge");
    tooltip.appendChild(create("h3", "trace-branch-title", "Berserk Tooltip 来源"));
    appendTraceSteps(tooltip, [
      ["Tooltip Definition", `${(berserkResolution.source_definition_id || "未提供").slice(0, 31)}…`, berserkResolution.source_definition_id],
      ["State Description", (berserkResolution.source_text_zh || "").split("\n")[0]],
      ["Runtime Exit", (berserkResolution.source_text_zh || "").split("\n")[1]],
    ]);
    container.appendChild(tooltip);

    const merge = create("section", "trace-merge");
    merge.appendChild(create("h3", "trace-branch-title", "Sources Merge"));
    appendTraceSteps(merge, [
      ["Threshold Evaluation", `当前怒气 ${evaluation.current_rage} ≥ 有效怒气上限 ${evaluation.effective_maximum_rage}`],
      ["Condition", evaluation.condition_result ? "Matched" : "Not Matched"],
      ["State Resolution", resolvedState ? `${resolvedState.state_id} = ${displayIdentifier(resolvedState.value)}` : "无"],
      ["Engine", "尚未接入"],
    ]);
    container.appendChild(merge);
    return;
  }
  if (!review || !review.rule || !Array.isArray(review.contribution_templates)) {
    renderPending(container, "尚未生成 Knowledge Rule Trace。");
    return;
  }

  container.replaceChildren();
  const resolution = review.concept_resolution;
  const source = review.rule.input && review.rule.input.resolution_source
    ? review.rule.input.resolution_source
    : {};
  const resolved = Array.isArray(review.resolved_contributions) ? review.resolved_contributions : [];
  if (!resolution || !resolved.length) {
    appendTraceSteps(container, [
      ["Hero Manifest", state.currentEntry.id],
      ["Structured Hero", structuredPath(state.currentEntry)],
      ["Effect", effect.effect_id],
      ["Rule", review.rule.rule_id],
      ["Contribution Template", review.contribution_templates.map((item) => item.contribution_id).join("；")],
      ["Engine", "尚未接入"],
    ]);
    return;
  }

  const branches = create("div", "trace-branches");
  const heroBranch = create("section", "trace-branch");
  heroBranch.appendChild(create("h3", "trace-branch-title", "Hero effect 来源"));
  appendTraceSteps(heroBranch, [
    ["Hero Manifest", state.currentEntry.id],
    ["Structured Hero", structuredPath(state.currentEntry)],
    ["Effect", effect.effect_id],
    ["Rule Coefficients", review.rule.outputs.map((item) => `${item.output_id}: ${item.coefficient}`).join("；")],
  ]);
  const tooltipBranch = create("section", "trace-branch");
  tooltipBranch.appendChild(create("h3", "trace-branch-title", "Tooltip 来源"));
  const definitionId = resolution.source_definition_id || "未提供";
  appendTraceSteps(tooltipBranch, [
    ["Tooltip Occurrence", `${displayValue(source.occurrence_count)} 次 · ${(source.source_entity_ids || []).join("、")}`],
    ["Tooltip Definition", `${definitionId.slice(0, 31)}…`, definitionId],
    ["Concept Property", `${resolution.concept_id}.base_maximum = ${resolution.resolved_value}`],
  ]);
  branches.append(heroBranch, tooltipBranch);
  container.appendChild(branches);

  const merge = create("section", "trace-merge");
  merge.appendChild(create("h3", "trace-branch-title", "Sources Merge"));
  appendTraceSteps(merge, [
    ["Rule Evaluation", review.rule.rule_id],
    ["Resolved Contributions", resolved.map((item) => item.contribution_id).join("；")],
    ["Calculation Nodes", resolved.map((item) => item.target_node).join("；")],
    ["Engine", "尚未接入"],
  ]);
  container.appendChild(merge);
}

function dataWarnings(data) {
  const warnings = Array.isArray(data && data.parse_warnings) ? [...data.parse_warnings] : [];
  if (!data || !data.name_zh) warnings.push("缺少 name_zh");
  if (!data || !data.page_url) warnings.push("缺少 page_url");
  if (!data || !data.raw_html_sha256) warnings.push("缺少 raw_html_sha256");
  if (!data || !data.portrait || !data.portrait.url) warnings.push("缺少 portrait.url");
  if (!data || !data.recommended_skill || !data.recommended_skill.name) warnings.push("缺少 recommended_skill.name");
  if (!data || !Array.isArray(data.nodes) || !data.nodes.length) warnings.push("缺少 nodes");
  if (state.loadError) warnings.push(state.loadError);
  return warnings;
}

function renderTraitHeader() {
  const data = state.currentData;
  const header = byId("trait-header");
  header.replaceChildren();
  const heading = create("div", "trait-heading-row");
  const portraitUrl = validUrl(data.portrait && data.portrait.url);
  if (portraitUrl) {
    const image = create("img", "trait-portrait");
    image.src = portraitUrl;
    image.alt = (data.portrait && data.portrait.alt) || `${data.name_zh} 头像`;
    image.addEventListener("error", () => image.remove());
    heading.appendChild(image);
  }
  const titleWrap = create("div", "trait-title-wrap");
  titleWrap.append(
    create("h1", "trait-title", data.name_zh || "未命名英雄特性"),
    create("p", "trait-id", `entity_id: ${displayValue(data.entity_id)}`)
  );
  heading.appendChild(titleWrap);
  header.appendChild(heading);
  header.appendChild(create("p", "trait-summary", data.summary || "未提供简介"));

  const metrics = create("div", "trait-meta");
  const values = [
    ["节点数量", data.nodes.length],
    ["效果数量", countEffects(data)],
    ["头像", portraitUrl ? "有" : "无"],
    ["推荐技能", data.recommended_skill && data.recommended_skill.name ? "有" : "无"],
  ];
  values.forEach(([label, value]) => {
    const metric = create("div", "metric");
    metric.append(create("span", "metric-label", label), create("span", "metric-value", value));
    metrics.appendChild(metric);
  });
  header.appendChild(metrics);

  const links = create("div", "trait-links");
  links.appendChild(create("span", "mono", `SHA-256: ${(data.raw_html_sha256 || "未提供").slice(0, 12)}`));
  links.appendChild(linkNode(data.page_url || "页面 URL 未提供", data.page_url));
  const skill = data.recommended_skill || {};
  const skillWrap = create("span", "");
  skillWrap.append("推荐技能：", linkNode(skill.name || "未提供", skill.url));
  links.appendChild(skillWrap);
  header.appendChild(links);

  byId("node-list-summary").textContent = `${data.nodes.length} 节点 · ${countEffects(data)} 效果`;
}

function renderNodes() {
  const container = byId("node-list");
  container.replaceChildren();
  const selectedId = state.selectedEffect && state.selectedEffect.effect.effect_id;

  state.currentData.nodes.forEach((node, position) => {
    const card = create("article", "node-card");
    const open = state.openNodes.has(node.index);
    const nodeEffectCount = (node.levels || []).reduce(
      (sum, level) => sum + (level.effects || []).length,
      0
    );
    const toggle = create("button", "node-toggle");
    toggle.type = "button";
    toggle.dataset.nodeIndex = String(node.index);
    toggle.setAttribute("aria-expanded", String(open));
    const titleWrap = create("span", "node-title-wrap");
    titleWrap.append(
      create("span", "node-title", `${String(position + 1).padStart(2, "0")} · ${node.name || "未命名节点"}`),
      create(
        "span",
        "node-subtitle",
        node.required_level === null || node.required_level === undefined
          ? "required_level: 未提供"
          : `required_level: ${node.required_level}`
      )
    );
    toggle.append(
      create("span", "node-chevron", open ? "▼" : "▶"),
      titleWrap,
      create("span", "node-level-count", `${(node.levels || []).length} levels · ${nodeEffectCount} effects`)
    );
    toggle.addEventListener("click", () => {
      if (state.openNodes.has(node.index)) state.openNodes.delete(node.index);
      else state.openNodes.add(node.index);
      renderNodes();
    });
    card.appendChild(toggle);

    const content = create("div", "node-content");
    content.hidden = !open;
    (node.levels || []).forEach((level) => {
      const levelGroup = create("section", "level-group");
      const levelLabel = level.level === null || level.level === undefined ? "等级未指定" : `等级 ${level.level}`;
      const effects = Array.isArray(level.effects) ? level.effects : [];
      const levelHeading = create("div", "level-heading");
      levelHeading.append(create("span", "", levelLabel), create("span", "mono", `${effects.length} effects`));
      levelGroup.appendChild(levelHeading);
      effects.forEach((effect) => {
        const row = create("button", "effect-row");
        row.type = "button";
        row.dataset.effectId = effect.effect_id || "";
        row.classList.toggle("selected", effect.effect_id === selectedId);
        const reviewed = state.knowledgeReviews.has(effect.effect_id);
        const reviewDot = create("span", `review-dot ${reviewed ? "reviewed" : "pending"}`);
        reviewDot.title = reviewed ? "Knowledge Reviewed" : "Knowledge Pending";
        reviewDot.setAttribute("aria-label", reviewDot.title);
        row.append(
          reviewDot,
          create("span", "effect-index", `#${effect.source && effect.source.effect_index !== undefined ? effect.source.effect_index : "?"}`),
          create("span", "effect-id", effect.effect_id || "未提供 effect_id"),
          create("span", "effect-text", effect.text || "未提供原文"),
          create("span", "effect-status", "Source Ready")
        );
        row.addEventListener("click", () => selectEffect(effect, node, level));
        levelGroup.appendChild(row);
      });
      content.appendChild(levelGroup);
    });
    card.appendChild(content);
    container.appendChild(card);
  });
}

function highlightSelectedEffect() {
  const selectedId = state.selectedEffect && state.selectedEffect.effect.effect_id;
  document.querySelectorAll(".effect-row").forEach((row) => {
    row.classList.toggle("selected", row.dataset.effectId === selectedId);
  });
}

function renderEffectPanels() {
  const selection = state.selectedEffect;
  if (!selection) {
    byId("source-text").textContent = "请选择一条效果。";
    byId("inspector-empty").hidden = false;
    byId("inspector-content").hidden = true;
    return;
  }
  const { effect, node, level } = selection;
  const source = effect.source || {};
  const review = state.knowledgeReviews.get(effect.effect_id) || null;
  const names = splitName(state.currentEntry.name_zh);
  byId("source-text").textContent = effect.text || "未提供";
  renderDefinitionList(byId("source-fields"), [
    ["所属英雄特性", state.currentData.name_zh],
    ["节点名称", source.node_name || node.name],
    ["trait level", source.trait_level],
    ["网页 URL", source.url || state.currentData.page_url, "link"],
  ]);
  renderDefinitionList(byId("structured-fields"), [
    ["effect_id", effect.effect_id],
    ["entity_id", state.currentData.entity_id],
    ["node_index", source.node_index],
    ["node_name", source.node_name || node.name],
    ["trait_level", source.trait_level],
    ["effect_index", source.effect_index],
    ["raw_html_sha256", source.raw_html_sha256 || state.currentData.raw_html_sha256],
  ]);
  renderKnowledge(review);
  renderRule(review);
  renderContribution(review);
  renderTrace(review, effect, node);

  const warnings = dataWarnings(state.currentData);
  const rule = review && review.rule;
  const templates = review && Array.isArray(review.contribution_templates) ? review.contribution_templates : [];
  const resolvedContributions = review && Array.isArray(review.resolved_contributions) ? review.resolved_contributions : [];
  const blockingInputs = review && Array.isArray(review.unresolved_inputs)
    ? review.unresolved_inputs.filter((item) => item.blocking)
    : [];
  const stateResolution = isStateResolutionReview(review);
  const resolvedState = stateResolution && review.static_evaluation && Array.isArray(review.static_evaluation.resolved_states)
    ? review.static_evaluation.resolved_states[0]
    : null;
  const runtimeRules = stateResolution && Array.isArray(review.runtime_rules) ? review.runtime_rules : [];
  const basis = bonusBasisReview(review);
  renderDefinitionList(byId("notes-fields"), [
    ["数据状态", "Source Ready"],
    ["Knowledge 状态", review ? "Reviewed" : "Pending"],
    ["Rule 状态", stateResolution ? "Resolved" : rule ? displayIdentifier(rule.status) : "Pending"],
    ["Contribution 状态", stateResolution ? "State Resolution" : basis ? "Scenario Resolved" : resolvedContributions.length ? "Resolved" : templates.length ? "Waiting for Input" : "Pending"],
    ["Confidence", review && review.provenance ? review.provenance.confidence : "未评估"],
    ["Warning", warnings.length ? warnings.join("；") : "无"],
  ]);

  byId("inspector-empty").hidden = true;
  byId("inspector-content").hidden = false;
  renderInspectorList(byId("inspector-selection"), [
    ["英雄", names.hero],
    ["特性", names.trait],
    ["节点", node.name],
    ["等级", level.level === null || level.level === undefined ? "未指定" : level.level],
    ["effect index", source.effect_index],
  ]);
  renderInspectorList(byId("inspector-identity"), [
    ["effect_id", effect.effect_id],
    ["entity_id", state.currentData.entity_id],
  ]);
  renderInspectorList(byId("inspector-trace"), [
    ["Manifest ID", state.currentEntry.id],
    ["Structured 文件", structuredPath(state.currentEntry)],
    ["URL", source.url || state.currentData.page_url],
    ["SHA-256", (source.raw_html_sha256 || state.currentData.raw_html_sha256 || "未提供").slice(0, 12)],
  ]);
  const inspectorStatus = stateResolution ? [
    ["Source", "Ready", "status-ready"],
    ["Knowledge Status", "Reviewed", "status-ready"],
    ["Rule Status", "Resolved", "status-ready"],
    ["Result Type", "State Resolution", "status-ready"],
    ["Resolved State", resolvedState ? resolvedState.state_name_zh : "无"],
    ["State Value", resolvedState && resolvedState.value === "active" ? "Active" : displayIdentifier(resolvedState && resolvedState.value), "status-ready"],
    ["Evaluation Mode", "Static"],
    ["Automatic", rule && rule.automatic ? "Yes" : "No"],
    ["Dependencies", review.provenance && Array.isArray(review.provenance.dependencies) ? review.provenance.dependencies.length : 0],
    ["Runtime Rules", `${runtimeRules.length} Recorded`],
    ["Engine", "Not Integrated", "status-pending"],
    ["Blocking Inputs", 0],
  ] : basis ? [
    ["Source", "Ready", "status-ready"],
    ["Knowledge Status", "Reviewed", "status-ready"],
    ["Rule Status", "Resolved", "status-ready"],
    ["Selected Scenario", "Berserk", "status-ready"],
    ["Scenario Contributions", 2],
    ["Alternative Scenario", "Available"],
    ["Evaluation Mode", "Static"],
    ["Required State", "暴气"],
    ["State Value", "Active", "status-ready"],
    ["Actual Rage", 100],
    ["Effective Maximum", basis.rule.input.resolved_value],
    ["Bonus Evaluation Value", basis.rule.output.resolved_value, "status-ready"],
    ["Dependent Slices", basis.provenance.dependencies.length],
    ["Engine Status", "Not Integrated", "status-pending"],
    ["Blocking Inputs", 0],
  ] : [
    ["Source", "Ready", "status-ready"],
    ["Knowledge Status", review ? "Reviewed" : "Pending", review ? "status-ready" : "status-pending"],
    ["Rule Status", rule ? displayIdentifier(rule.status) : "Pending", rule ? "status-ready" : "status-pending"],
    ["Contribution Status", resolvedContributions.length ? "Resolved" : templates.length ? "Waiting for Input" : "Pending", resolvedContributions.length ? "status-ready" : templates.length ? "status-waiting" : "status-pending"],
    ["Blocking Inputs", blockingInputs.length, blockingInputs.length ? "status-waiting" : ""],
    ["Blocking Detail", blockingInputs.length ? blockingInputs.map((item) => item.name_zh).join("、") : "无"],
    ["Resolved Input", rule && rule.input && rule.input.resolution_status === "resolved" ? `${rule.input.name_zh} = ${rule.input.resolved_value}` : "无"],
    ["Resolved Contributions", resolvedContributions.length],
    ["Concept Source", review && review.concept_resolution ? "Tooltip Definition" : "无"],
    ["Engine Status", "Not Integrated", "status-pending"],
  ];
  renderInspectorList(byId("inspector-status"), inspectorStatus);
  const warningContainer = byId("inspector-warnings");
  warningContainer.replaceChildren();
  if (!warnings.length) warningContainer.appendChild(create("p", "warning-none", "无"));
  else warnings.forEach((warning) => warningContainer.appendChild(create("p", "warning-item", warning)));
}

function selectEffect(effect, node, level) {
  state.selectedEffect = { effect, node, level };
  document.body.dataset.selectedEffect = effect.effect_id || "";
  highlightSelectedEffect();
  renderEffectPanels();
}

function renderTrait() {
  renderTraitHeader();
  renderNodes();
  if (state.selectedEffect) renderEffectPanels();
  else renderEffectPanels();
}

async function loadTrait(entry) {
  const token = ++state.loadToken;
  state.currentEntry = entry;
  state.selectedTrait = entry.id;
  state.currentData = null;
  state.selectedEffect = null;
  state.loadError = null;
  state.knowledgeReviews = new Map();
  state.expandedGroups.add(entry.heroName);
  document.body.dataset.selectedTrait = entry.id;
  document.body.dataset.selectedEffect = "";
  renderTree();
  byId("detail-loading").textContent = `正在加载 ${entry.slug || entry.id}…`;
  byId("detail-loading").hidden = false;
  byId("detail-error").hidden = true;
  byId("detail-content").hidden = true;
  byId("inspector-empty").hidden = false;
  byId("inspector-content").hidden = true;

  const path = structuredPath(entry);
  try {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data.nodes)) throw new Error("缺少 nodes 数组");
    const knowledgeReviews = await loadKnowledgeReviews(entry);
    if (token !== state.loadToken) return;
    state.currentData = data;
    state.knowledgeReviews = knowledgeReviews;
    state.openNodes = new Set(data.nodes.length ? [data.nodes[0].index] : []);
    state.selectedEffect = firstEffect(data);
    if (state.selectedEffect) {
      document.body.dataset.selectedEffect = state.selectedEffect.effect.effect_id || "";
    }
    byId("detail-loading").hidden = true;
    byId("detail-content").hidden = false;
    renderTrait();
  } catch (error) {
    if (token !== state.loadToken) return;
    const message = error instanceof Error ? error.message : String(error);
    state.loadError = `${path}：${message}`;
    byId("detail-loading").hidden = true;
    byId("detail-error").textContent = `无法加载 structured JSON\n文件：${path}\n错误：${message}`;
    byId("detail-error").hidden = false;
  }
}

async function loadManifest() {
  try {
    const response = await fetch(MANIFEST_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const manifest = await response.json();
    if (!Array.isArray(manifest.entries)) throw new Error("缺少 entries 数组");
    state.manifest = manifest.entries;
    state.groups = groupEntries(state.manifest);
    if (state.groups.length) state.expandedGroups.add(state.groups[0].heroName);
    byId("hero-count").textContent = state.manifest.length;
    byId("manifest-state").hidden = true;
    byId("hero-tree").hidden = false;
    renderTree();
    const defaultEntry = state.groups.flatMap((group) => group.traits).find(
      (entry) => entry.id === DEFAULT_TRAIT
    ) || (state.groups[0] && state.groups[0].traits[0]);
    if (!defaultEntry) throw new Error("Manifest 没有可选英雄特性");
    await loadTrait(defaultEntry);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    byId("manifest-state").textContent = `无法读取 Hero Manifest：${MANIFEST_URL}（${message}）`;
    byId("manifest-state").classList.add("error-state");
    byId("detail-loading").hidden = true;
    byId("detail-error").textContent = `无法启动 Knowledge Viewer：${message}`;
    byId("detail-error").hidden = false;
  }
}

byId("hero-search").addEventListener("input", renderTree);
loadManifest();
