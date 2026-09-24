"""管网漏点隔离规划台 —— FastAPI 后端。

API：
  GET  /api/scenario        读取当前方案
  PUT  /api/scenario        整体保存方案（校验后落库）
  POST /api/scenario/demo   载入内置示例方案
  POST /api/solve           对当前方案求解最优关阀组合并保存结果
  GET  /api/result          读取最近一次求解结果
页面：
  GET  /                    单页应用（原生 JS）
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database
from .solver import solve_scenario

MAX_VALVES = 14
MAX_NAME_LEN = 32


class ValveIn(BaseModel):
    vid: int
    a: str
    b: str
    cost: int


class ScenarioIn(BaseModel):
    edges: list[tuple[str, str]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    leaks: list[str] = Field(default_factory=list)
    musts: list[str] = Field(default_factory=list)
    valves: list[ValveIn] = Field(default_factory=list)


def _norm_edge(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def validate_and_normalize(payload: ScenarioIn) -> dict:
    """校验并规范化输入；不合法时抛出 422，detail 为中文错误列表。"""
    errors: list[str] = []

    def clean_name(raw: str, where: str) -> str:
        name = (raw or "").strip()
        if not name:
            errors.append(f"{where}：节点名不能为空。")
        elif any(ch.isspace() for ch in name):
            errors.append(f"{where}：节点名「{name}」不能包含空白字符。")
        elif len(name) > MAX_NAME_LEN:
            errors.append(f"{where}：节点名「{name}」超过 {MAX_NAME_LEN} 个字符。")
        return name

    # 管段
    edges: list[list[str]] = []
    seen_edges: set[tuple[str, str]] = set()
    for a_raw, b_raw in payload.edges:
        a = clean_name(a_raw, "管段")
        b = clean_name(b_raw, "管段")
        if not a or not b:
            continue
        if a == b:
            errors.append(f"管段「{a}—{b}」两端不能是同一节点。")
            continue
        key = _norm_edge(a, b)
        if key in seen_edges:
            continue  # 重复管段直接忽略
        seen_edges.add(key)
        edges.append([a, b])

    # 角色节点
    def clean_list(raws: list[str]) -> list[str]:
        out, seen = [], set()
        for raw in raws:
            name = (raw or "").strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    sources = clean_list(payload.sources)
    leaks = clean_list(payload.leaks)
    musts = clean_list(payload.musts)
    for name in sources + leaks + musts:
        clean_name(name, "角色节点")

    # 阀门
    valves: list[dict] = []
    if len(payload.valves) > MAX_VALVES:
        errors.append(f"阀门数量最多 {MAX_VALVES} 个，当前为 {len(payload.valves)} 个。")
    seen_vids: set[int] = set()
    for v in payload.valves:
        a = clean_name(v.a, f"阀门 {v.vid}")
        b = clean_name(v.b, f"阀门 {v.vid}")
        if v.vid in seen_vids:
            errors.append(f"阀门编号 {v.vid} 重复。")
            continue
        seen_vids.add(v.vid)
        if v.cost < 1:
            errors.append(f"阀门 {v.vid} 的关闭代价必须为正整数。")
        if a and b:
            if a == b:
                errors.append(f"阀门 {v.vid} 绑定的管段两端不能是同一节点。")
            elif _norm_edge(a, b) not in seen_edges:
                errors.append(f"阀门 {v.vid} 绑定的管段「{a}—{b}」不在管段列表中。")
        valves.append({"vid": v.vid, "a": a, "b": b, "cost": v.cost})

    if errors:
        raise HTTPException(status_code=422, detail=errors)

    return {
        "edges": edges,
        "sources": sources,
        "leaks": leaks,
        "musts": musts,
        "valves": sorted(valves, key=lambda v: v["vid"]),
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.init_db()  # 启动时自动建表，空库则写入示例方案
    yield


app = FastAPI(title="管网漏点隔离规划台", version="1.0.0", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "up"}


@app.get("/api/scenario")
def get_scenario():
    with database.get_conn() as conn:
        return database.load_scenario(conn)


@app.put("/api/scenario")
def put_scenario(payload: ScenarioIn):
    scenario = validate_and_normalize(payload)
    database.save_scenario(scenario)
    return scenario


@app.post("/api/scenario/demo")
def load_demo():
    database.save_scenario(database.DEMO_SCENARIO)
    return database.DEMO_SCENARIO


@app.post("/api/solve")
def solve():
    with database.get_conn() as conn:
        scenario = database.load_scenario(conn)
    if not scenario["edges"] and not scenario["sources"]:
        raise HTTPException(status_code=400, detail=["当前方案为空，请先录入管段、进水点等数据。"])
    result = solve_scenario(scenario)
    return database.save_result(result)


@app.get("/api/result")
def get_result():
    result = database.load_result()
    if result is None:
        raise HTTPException(status_code=404, detail=["尚未求解过。"])
    return result


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
