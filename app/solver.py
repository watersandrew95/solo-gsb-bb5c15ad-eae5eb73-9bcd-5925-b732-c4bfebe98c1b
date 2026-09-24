"""管网漏点隔离求解核心。

模型：
  - 管段构成无向图；阀门绑定在某条管段上，关闭阀门即切断该管段。
  - 目标：选出总关闭代价最小的阀门集合，使得
      1) 每个漏点都与全部进水点断开（不连通）；
      2) 每个必保供水点仍至少连通一个进水点。
  - 总代价相同时，取“阀门编号升序列表”字典序最小的方案。

阀门最多 14 个，直接枚举全部 2^n 种关阀组合，保证最优且规则精确。
无解时给出具体原因（角色冲突 / 本身不连通 / 无阀门通路 / 隔离与供水冲突）。
"""

from __future__ import annotations

from collections import deque


def _norm_edge(a: str, b: str) -> tuple[str, str]:
    """无向管段的规范化表示（与端点书写顺序无关）。"""
    return (a, b) if a <= b else (b, a)


def _build_adj(nodes, edges, closed=frozenset()):
    """根据未关闭的管段构建邻接表。closed 为被切断管段的下标集合。"""
    adj = {n: set() for n in nodes}
    for i, (a, b) in enumerate(edges):
        if i in closed:
            continue
        adj[a].add(b)
        adj[b].add(a)
    return adj


def _reachable(sources, adj):
    """从全部进水点出发做 BFS，返回可达节点集合。"""
    seen = set()
    queue = deque()
    for s in sources:
        if s not in seen:
            seen.add(s)
            queue.append(s)
    while queue:
        u = queue.popleft()
        for v in adj.get(u, ()):
            if v not in seen:
                seen.add(v)
                queue.append(v)
    return seen


def _node_status(nodes, src_set, leak_set, must_set, reach):
    """汇总隔离后每个节点的供水状态。"""
    status = []
    for node in sorted(nodes):
        roles = []
        if node in src_set:
            roles.append("source")
        if node in leak_set:
            roles.append("leak")
        if node in must_set:
            roles.append("must")
        if node in leak_set:
            state = "isolated"      # 漏点已被隔离
        elif node in reach:
            state = "supplied"      # 仍连通进水点，供水正常
        else:
            state = "outage"        # 与全部进水点断开，停水
        status.append({"node": node, "roles": roles, "state": state})
    return status


def solve_scenario(scenario: dict) -> dict:
    """求解最优关阀方案。

    scenario = {
        "edges":   [[a, b], ...],                  # 无向管段
        "sources": [节点名, ...],                   # 进水点
        "leaks":   [节点名, ...],                   # 漏点
        "musts":   [节点名, ...],                   # 必保供水点
        "valves":  [{"vid": int, "a": str, "b": str, "cost": int}, ...],
    }
    """
    edges = [tuple(e) for e in scenario["edges"]]
    sources = list(dict.fromkeys(scenario["sources"]))
    leaks = list(dict.fromkeys(scenario["leaks"]))
    musts = list(dict.fromkeys(scenario["musts"]))
    valves = list(scenario["valves"])

    nodes = set(sources) | set(leaks) | set(musts)
    for a, b in edges:
        nodes.add(a)
        nodes.add(b)

    # 管段（规范化）-> 下标；阀门 -> 其绑定管段的下标
    edge_index = {}
    for i, (a, b) in enumerate(edges):
        edge_index.setdefault(_norm_edge(a, b), i)
    valve_edge = {v["vid"]: edge_index[_norm_edge(v["a"], v["b"])] for v in valves}

    src_set, leak_set, must_set = set(sources), set(leaks), set(musts)

    # ---------- 硬性无解原因（无需枚举即可判定） ----------
    reasons = []

    for x in sorted(leak_set & src_set):
        reasons.append(f"节点「{x}」既是漏点又是进水点：漏点无法与全部进水点断开。")
    for x in sorted(leak_set & must_set):
        reasons.append(f"节点「{x}」既是漏点又是必保供水点：隔离与供水要求互相冲突。")

    # 全部阀门开启时：必保点必须本来就能连到某个进水点
    reach_open = _reachable(sources, _build_adj(nodes, edges))
    for m in sorted(must_set - reach_open):
        reasons.append(f"必保供水点「{m}」与所有进水点均不连通（管网本身不连通）。")

    # 全部阀门关闭时：剩下的无阀门通路不能再让漏点碰到进水点
    valved_edges = set(valve_edge.values())
    reach_shut = _reachable(sources, _build_adj(nodes, edges, closed=valved_edges))
    for lk in sorted(leak_set & reach_shut):
        reasons.append(f"漏点「{lk}」与进水点之间存在无阀门通路，即使关闭全部阀门也无法隔离。")

    if reasons:
        return {
            "status": "infeasible",
            "reasons": reasons,
            "min_cost": None,
            "close_valves": [],
            "closed_segments": [],
            "subsets_checked": 0,
            "node_status": None,
        }

    # ---------- 枚举全部关阀组合 ----------
    n = len(valves)
    vids = [v["vid"] for v in valves]
    costs = [v["cost"] for v in valves]

    best_key = None        # (总代价, 升序编号元组)
    best_closed = None     # 被切断的管段下标集合
    best_vids: list[int] = []
    # 记录“能隔离全部漏点”的方案里，每个必保点是否至少有一次被保住（用于无解诊断）
    must_savable = {m: False for m in musts}

    for mask in range(1 << n):
        total = 0
        closed = set()
        chosen = []
        for j in range(n):
            if mask >> j & 1:
                total += costs[j]
                closed.add(valve_edge[vids[j]])
                chosen.append(vids[j])
        if best_key is not None and total > best_key[0]:
            continue
        reach = _reachable(sources, _build_adj(nodes, edges, closed))
        if leak_set & reach:            # 仍有漏点连着进水点
            continue
        unsupplied = must_set - reach
        for m in must_set - unsupplied:
            must_savable[m] = True
        if unsupplied:                  # 仍有必保点失去供水
            continue
        key = (total, tuple(sorted(chosen)))
        if best_key is None or key < best_key:
            best_key = key
            best_closed = closed
            best_vids = sorted(chosen)

    # ---------- 无解：隔离与供水冲突 ----------
    if best_key is None:
        hopeless = sorted(m for m, ok in must_savable.items() if not ok)
        if hopeless:
            reasons.append(
                "必保供水点 "
                + "、".join(f"「{m}」" for m in hopeless)
                + " 的供水与漏点隔离冲突：任何能隔离全部漏点的关阀方案都会切断其供水。"
            )
        else:
            reasons.append("无法找到同时满足“隔离全部漏点”和“保住全部必保点”的关阀组合：约束互相冲突。")
        return {
            "status": "infeasible",
            "reasons": reasons,
            "min_cost": None,
            "close_valves": [],
            "closed_segments": [],
            "subsets_checked": 1 << n,
            "node_status": None,
        }

    reach = _reachable(sources, _build_adj(nodes, edges, best_closed))
    closed_segments = sorted({tuple(edges[i]) for i in best_closed})

    return {
        "status": "ok",
        "reasons": [],
        "min_cost": best_key[0],
        "close_valves": best_vids,
        "closed_segments": [list(s) for s in closed_segments],
        "subsets_checked": 1 << n,
        "node_status": _node_status(nodes, src_set, leak_set, must_set, reach),
    }
