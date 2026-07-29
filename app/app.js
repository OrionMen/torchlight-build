"use strict";

const DATA_URL = "/data/parsed/heroes/ss13/rehan-anger.json";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function safeUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function externalLink(label, url) {
  const href = safeUrl(url);
  if (!href) return element("span", "empty-value", label || "未提供");
  const link = element("a", "", label || href);
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function addSourceItem(container, label, valueNode) {
  const item = element("div", "source-item");
  item.appendChild(element("span", "source-label", label));
  if (valueNode instanceof Node) {
    valueNode.classList.add("source-value");
    item.appendChild(valueNode);
  } else {
    item.appendChild(element("span", "source-value", valueNode || "未提供"));
  }
  container.appendChild(item);
}

function renderPortrait(portrait) {
  const frame = element("div", "portrait-frame");
  const fallback = element("span", "portrait-fallback", "英雄头像不可用");
  const url = safeUrl(portrait && portrait.url);
  if (!url) {
    frame.appendChild(fallback);
    return frame;
  }

  const image = document.createElement("img");
  image.src = url;
  image.alt = typeof portrait.alt === "string" && portrait.alt ? portrait.alt : "英雄头像";
  image.addEventListener("error", () => {
    image.hidden = true;
    fallback.hidden = false;
  });
  fallback.hidden = true;
  frame.append(image, fallback);
  return frame;
}

function renderHero(data) {
  const container = document.getElementById("hero");
  const layout = element("div", "hero-layout");
  layout.appendChild(renderPortrait(data.portrait || {}));

  const body = element("div", "hero-body");
  const rawName = typeof data.name === "string" ? data.name : "未知人物";
  const heroLabel = typeof data.hero_label === "string" ? data.hero_label : "未知特性";
  const personName = rawName.replace(/\|/g, "·");
  const featureName = heroLabel.split(" - ")[0] || "未知特性";
  const displayName = `${personName}｜${featureName}`;

  const titleRow = element("div", "hero-title-row");
  const title = element("h2", "hero-title", displayName);
  title.id = "hero-title";
  titleRow.appendChild(title);
  body.appendChild(titleRow);

  const rawFields = element("div", "raw-fields");
  rawFields.append(
    element("span", "", `人物：${rawName}`),
    element("span", "", `特性：${heroLabel}`)
  );
  body.appendChild(rawFields);
  body.appendChild(
    element(
      "p",
      "hero-summary",
      typeof data.summary === "string" && data.summary ? data.summary : "暂无英雄简介。"
    )
  );

  const skill = data.recommended_skill || {};
  const skillLine = element("p", "");
  skillLine.appendChild(element("strong", "", "推荐技能："));
  const skillName = typeof skill.name === "string" && skill.name ? skill.name : "未提供";
  skillLine.appendChild(externalLink(skillName, skill.url));
  body.appendChild(skillLine);
  layout.appendChild(body);
  container.appendChild(layout);

  const source = data.source || {};
  const sourceGrid = element("div", "source-grid");
  const season = typeof data.season === "string" ? data.season.toUpperCase() : "未提供";
  const hash = typeof source.sha256 === "string" ? source.sha256.slice(0, 12) : "未提供";
  addSourceItem(sourceGrid, "赛季", season);
  addSourceItem(sourceGrid, "Hero ID", data.hero_id);
  addSourceItem(sourceGrid, "抓取时间", source.fetched_at);
  addSourceItem(sourceGrid, "原始数据 SHA-256", hash);
  addSourceItem(sourceGrid, "来源网址", externalLink(source.url, source.url));
  container.appendChild(sourceGrid);
}

function renderStats(nodes) {
  const values = [
    ["节点数量", nodes.length],
    ["总等级数量", nodes.reduce((sum, node) => sum + (Array.isArray(node.levels) ? node.levels.length : 0), 0)],
    ["效果条目数量", nodes.reduce(
      (sum, node) => sum + (Array.isArray(node.levels)
        ? node.levels.reduce((levelSum, level) => levelSum + (Array.isArray(level.lines) ? level.lines.length : 0), 0)
        : 0),
      0
    )],
    ["有需求等级", nodes.filter((node) => node.required_level !== null && node.required_level !== undefined).length],
  ];

  const container = document.getElementById("stats");
  values.forEach(([label, value]) => {
    const card = element("article", "stat-card");
    card.append(element("strong", "stat-value", value), element("span", "stat-label", label));
    container.appendChild(card);
  });
}

function renderLevel(level) {
  const block = element("section", "level-block");
  const levelTitle = level.level === null || level.level === undefined
    ? "节点效果"
    : `等级 ${level.level}`;
  block.appendChild(element("h4", "level-title", levelTitle));

  const lines = Array.isArray(level.lines) ? level.lines : [];
  if (!lines.length) {
    block.appendChild(element("p", "empty-value", "暂无效果条目。"));
    return block;
  }
  const list = element("ul", "effect-list");
  lines.forEach((line) => list.appendChild(element("li", "", line)));
  block.appendChild(list);
  return block;
}

function renderNode(node, position) {
  const card = element("article", "node-card");
  const header = element("div", "node-header");
  const identity = element("div", "node-identity");
  const iconUrl = safeUrl(node.icon && node.icon.url);

  if (iconUrl) {
    const icon = document.createElement("img");
    icon.className = "node-icon";
    icon.src = iconUrl;
    icon.alt = typeof node.icon.alt === "string" && node.icon.alt ? node.icon.alt : "";
    icon.addEventListener("error", () => icon.remove());
    identity.appendChild(icon);
  }

  const labels = element("div", "");
  labels.appendChild(element("p", "node-index", `节点 ${String(position + 1).padStart(2, "0")}`));
  labels.appendChild(element("h3", "node-name", node.name || "未命名节点"));
  const requirement = node.required_level === null || node.required_level === undefined
    ? "需求等级未标明"
    : `需求等级 ${node.required_level}`;
  labels.appendChild(element("span", "level-badge", requirement));
  identity.appendChild(labels);

  const content = element("div", "node-content");
  content.id = `node-content-${position}`;
  const levels = Array.isArray(node.levels) ? node.levels : [];
  levels.forEach((level) => content.appendChild(renderLevel(level)));

  const toggle = element("button", "toggle-button", "收起");
  toggle.type = "button";
  toggle.setAttribute("aria-controls", content.id);
  toggle.setAttribute("aria-expanded", "true");
  toggle.addEventListener("click", () => {
    const expanded = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", String(!expanded));
    toggle.textContent = expanded ? "展开" : "收起";
    content.hidden = expanded;
  });

  header.append(identity, toggle);
  card.append(header, content);
  return card;
}

function renderNodes(nodes) {
  const container = document.getElementById("nodes");
  nodes.forEach((node, index) => container.appendChild(renderNode(node, index)));
  document.getElementById("node-summary").textContent = `共 ${nodes.length} 个节点`;
}

async function loadHero() {
  const loading = document.getElementById("loading");
  const error = document.getElementById("error");
  const content = document.getElementById("content");

  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (!Array.isArray(data.nodes)) throw new Error("Missing nodes");

    renderHero(data);
    renderStats(data.nodes);
    renderNodes(data.nodes);
    loading.hidden = true;
    content.hidden = false;
  } catch (loadError) {
    console.error("Hero data load failed:", loadError);
    loading.hidden = true;
    error.hidden = false;
  }
}

loadHero();
