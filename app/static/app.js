/* 管网漏点隔离规划台 —— 前端逻辑（原生 JS） */

const $ = (id) => document.getElementById(id);

/* ---------------- 输入解析 ---------------- */

function parseEdges(text) {
  const edges = [];
  const errors = [];
  text.split("\n").forEach((line, i) => {
    const t = line.trim();
    if (!t || t.startsWith("#")) return;
    const parts = t.split(/\s+/);
    if (parts.length !== 2) {
      errors.push(`管段第 ${i + 1} 行「${t}」格式应为：端点A 端点B`);
      return;
    }
    edges.push([parts[0], parts[1]]);
  });
  return { edges, errors };
}

function parseValves(text) {
  const valves = [];
  const errors = [];
  text.split("\n").forEach((line, i) => {
    const t = line.trim();
    if (!t || t.startsWith("#")) return;
    const parts = t.split(/\s+/);
    if (parts.length !== 4) {
      errors.push(`阀门第 ${i + 1} 行「${t}」格式应为：编号 端点A 端点B 关闭代价`);
      return;
    }
    const vid = Number(parts[0]);
    const cost = Number(parts[3]);
    if (!Number.isInteger(vid)) errors.push(`阀门第 ${i + 1} 行：编号「${parts[0]}」不是整数`);
    if (!Number.isInteger(cost) || cost < 1) errors.push(`阀门第 ${i + 1} 行：代价「${parts[3]}」不是正整数`);
    if (Number.isInteger(vid) && Number.isInteger(cost) && cost >= 1) {
      valves.push({ vid, a: parts[1], b: parts[2], cost });
    }
  });
  return { valves, errors };
}

function parseNames(text) {
  return text.split(/[\s,，、;；]+/).map((s) => s.trim()).filter(Boolean);
}

function readInputs() {
  const { edges, errors: e1 } = parseEdges($("edges").value);
  const { valves, errors: e2 } = parseValves($("valves").value);
  const scenario = {
    edges,
    sources: parseNames($("sources").value),
    leaks: parseNames($("leaks").value),
    musts: parseNames($("musts").value),
    valves,
  };
  return { scenario, errors: [...e1, ...e2] };
}

function fillInputs(s) {
  $("edges").value = s.edges.map((e) => e.join(" ")).join("\n");
  $("sources").value = s.sources.join(" ");
  $("leaks").value = s.leaks.join(" ");
  $("musts").value = s.musts.join(" ");
  $("valves").value = s.valves.map((v) => `${v.vid} ${v.a} ${v.b} ${v.cost}`).join("\n");
}

/* ---------------- 提示信息 ---------------- */

function showMessage(text, ok) {
  const box = $("message");
  box.hidden = false;
  box.textContent = text;
  box.className = "message " + (ok ? "ok" : "err");
}

function formatErrors(detail) {
  if (Array.isArray(detail)) return detail.join("\n");
  if (typeof detail === "string") return detail;
  return JSON.stringify(detail);
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(formatErrors(data.detail) || `请求失败（${resp.status}）`);
  return data;
}

/* ---------------- 结果渲染 ---------------- */

const ROLE_NAMES = { source: "进水点", leak: "漏点", must: "必保点" };
const STATE_TEXT = {
  supplied: "供水正常",
  isolated: "漏点 · 已隔离",
  outage: "停水",
};

function renderResult(result, scenario) {
  $("result-empty").hidden = true;
  $("result-body").hidden = false;

  const banner = $("result-banner");
  if (result.status === "ok") {
    banner.className = "ok";
    banner.textContent =
      `✅ 最优方案：总代价 ${result.min_cost}，需关闭 ${result.close_valves.length} 个阀门` +
      `（共枚举 ${result.subsets_checked} 种组合，同代价取编号升序字典序最小）`;
  } else {
    banner.className = "bad";
    banner.innerHTML = "❌ 无解：";
    const ul = document.createElement("ul");
    result.reasons.forEach((r) => {
      const li = document.createElement("li");
      li.textContent = r;
      ul.appendChild(li);
    });
    banner.appendChild(ul);
  }

  // 关阀清单
  const list = $("close-list");
  list.innerHTML = "";
  if (result.status === "ok" && result.close_valves.length) {
    const costOf = Object.fromEntries((scenario?.valves || []).map((v) => [v.vid, v.cost]));
    result.close_valves.forEach((vid) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = costOf[vid] != null ? `阀门 ${vid}（代价 ${costOf[vid]}）` : `阀门 ${vid}`;
      list.appendChild(chip);
    });
  } else {
    const chip = document.createElement("span");
    chip.className = "chip none";
    chip.textContent = result.status === "ok" ? "无需关闭任何阀门" : "—";
    list.appendChild(chip);
  }
  $("closed-segments").textContent =
    result.status === "ok" && result.closed_segments.length
      ? "被切断的管段：" + result.closed_segments.map((s) => s.join("—")).join("，")
      : "";

  // 节点状态表
  const tbody = $("node-table").querySelector("tbody");
  tbody.innerHTML = "";
  (result.node_status || []).forEach((n) => {
    const tr = document.createElement("tr");
    const roles = n.roles.map((r) => `<span class="role-tag role-${r}">${ROLE_NAMES[r]}</span>`).join("");
    tr.innerHTML = `<td><b>${escapeHtml(n.node)}</b></td><td>${roles || "—"}</td>` +
      `<td class="state-${n.state}">${STATE_TEXT[n.state]}</td>`;
    tbody.appendChild(tr);
  });

  renderGraph(scenario, result);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------------- SVG 管网图（环形布局） ---------------- */

function renderGraph(scenario, result) {
  const svg = $("graph");
  svg.innerHTML = "";
  if (!scenario || !result.node_status) return;

  const W = 640, H = 440, cx = W / 2, cy = H / 2;
  const R = Math.min(cx, cy) - 70;

  const statusOf = Object.fromEntries(result.node_status.map((n) => [n.node, n]));
  const nodes = result.node_status.map((n) => n.node);
  const pos = {};
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
    pos[n] = [cx + R * Math.cos(angle), cy + R * Math.sin(angle)];
  });

  const norm = (a, b) => (a <= b ? a + "|" + b : b + "|" + a);
  const closedSet = new Set((result.closed_segments || []).map((s) => norm(s[0], s[1])));

  const NS = "http://www.w3.org/2000/svg";
  const mk = (tag, attrs) => {
    const el = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    return el;
  };

  // 管段
  scenario.edges.forEach(([a, b]) => {
    if (!pos[a] || !pos[b]) return;
    const closed = closedSet.has(norm(a, b));
    svg.appendChild(mk("line", {
      x1: pos[a][0], y1: pos[a][1], x2: pos[b][0], y2: pos[b][1],
      class: "edge" + (closed ? " closed" : ""),
    }));
  });

  // 节点
  nodes.forEach((n) => {
    const st = statusOf[n];
    const [x, y] = pos[n];
    const cls = st.roles.includes("source") ? "source"
      : st.roles.includes("leak") ? "leak"
      : st.state === "supplied" ? "supplied" : "outage";
    if (st.roles.includes("must")) {
      svg.appendChild(mk("circle", { cx: x, cy: y, r: 17, class: "node-ring" }));
    }
    svg.appendChild(mk("circle", { cx: x, cy: y, r: 12, class: "node-circle " + cls }));
    const label = mk("text", { x, y: y - 22, class: "node-label" });
    label.textContent = n;
    svg.appendChild(label);
  });
}

/* ---------------- 事件 ---------------- */

async function saveScenario() {
  const { scenario, errors } = readInputs();
  if (errors.length) {
    showMessage(errors.join("\n"), false);
    return null;
  }
  try {
    const saved = await api("/api/scenario", { method: "PUT", body: JSON.stringify(scenario) });
    showMessage("✅ 方案已保存。", true);
    return saved;
  } catch (e) {
    showMessage(e.message, false);
    return null;
  }
}

$("btn-save").addEventListener("click", saveScenario);

$("btn-solve").addEventListener("click", async () => {
  const saved = await saveScenario();
  if (!saved) return;
  try {
    const result = await api("/api/solve", { method: "POST" });
    renderResult(result, saved);
    showMessage(result.status === "ok" ? "✅ 求解完成。" : "⚠️ 约束冲突，无解。", result.status === "ok");
  } catch (e) {
    showMessage(e.message, false);
  }
});

$("btn-demo").addEventListener("click", async () => {
  try {
    const demo = await api("/api/scenario/demo", { method: "POST" });
    fillInputs(demo);
    showMessage("✅ 已载入示例方案，可直接点击「求解最优关阀」。", true);
  } catch (e) {
    showMessage(e.message, false);
  }
});

$("btn-clear").addEventListener("click", () => {
  ["edges", "sources", "leaks", "musts", "valves"].forEach((id) => ($(id).value = ""));
  $("message").hidden = true;
});

/* ---------------- 初始化：载入已保存方案与上次结果 ---------------- */

(async function init() {
  try {
    const scenario = await api("/api/scenario");
    fillInputs(scenario);
    try {
      const result = await api("/api/result");
      renderResult(result, scenario);
    } catch { /* 尚无求解结果 */ }
  } catch (e) {
    showMessage("初始化失败：" + e.message, false);
  }
})();
