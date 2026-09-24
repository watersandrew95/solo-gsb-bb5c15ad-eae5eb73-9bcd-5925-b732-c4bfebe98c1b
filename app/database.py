"""SQLite 数据访问层：方案（管段/阀门/角色）与最近一次求解结果。"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "..", "data"))
DB_PATH = os.environ.get("DB_PATH", os.path.join(DATA_DIR, "pwnet.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    a  TEXT NOT NULL,
    b  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS valves (
    vid  INTEGER PRIMARY KEY,
    a    TEXT NOT NULL,
    b    TEXT NOT NULL,
    cost INTEGER NOT NULL CHECK (cost > 0)
);
CREATE TABLE IF NOT EXISTS roles (
    node TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('source', 'leak', 'must')),
    PRIMARY KEY (node, role)
);
CREATE TABLE IF NOT EXISTS results (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    payload   TEXT NOT NULL,
    solved_at TEXT NOT NULL
);
"""

# 内置示例方案：首次启动（数据库为空）时自动写入，方便直接体验。
DEMO_SCENARIO = {
    "edges": [
        ["S1", "A"], ["A", "B"], ["B", "L1"], ["L1", "C"], ["C", "H1"],
        ["A", "D"], ["D", "H2"], ["S2", "D"], ["D", "C"], ["B", "E"],
        ["E", "H3"],
    ],
    "sources": ["S1", "S2"],
    "leaks": ["L1"],
    "musts": ["H1", "H2", "H3"],
    "valves": [
        {"vid": 1, "a": "S1", "b": "A", "cost": 4},
        {"vid": 2, "a": "A", "b": "B", "cost": 3},
        {"vid": 3, "a": "B", "b": "L1", "cost": 2},
        {"vid": 4, "a": "L1", "b": "C", "cost": 2},
        {"vid": 5, "a": "C", "b": "H1", "cost": 6},
        {"vid": 6, "a": "A", "b": "D", "cost": 5},
        {"vid": 7, "a": "S2", "b": "D", "cost": 4},
        {"vid": 8, "a": "D", "b": "C", "cost": 3},
        {"vid": 9, "a": "B", "b": "E", "cost": 2},
        {"vid": 10, "a": "E", "b": "H3", "cost": 7},
    ],
}


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """建表；若库为空则写入示例方案。"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        empty = conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"] == 0
        if empty:
            _save_scenario(conn, DEMO_SCENARIO)


def load_scenario(conn: sqlite3.Connection) -> dict:
    edges = [[r["a"], r["b"]] for r in conn.execute("SELECT a, b FROM edges ORDER BY id")]
    valves = [
        {"vid": r["vid"], "a": r["a"], "b": r["b"], "cost": r["cost"]}
        for r in conn.execute("SELECT vid, a, b, cost FROM valves ORDER BY vid")
    ]
    roles: dict[str, list[str]] = {"source": [], "leak": [], "must": []}
    for r in conn.execute("SELECT node, role FROM roles ORDER BY node"):
        roles[r["role"]].append(r["node"])
    return {
        "edges": edges,
        "sources": roles["source"],
        "leaks": roles["leak"],
        "musts": roles["must"],
        "valves": valves,
    }


def _save_scenario(conn: sqlite3.Connection, scenario: dict) -> None:
    conn.execute("DELETE FROM edges")
    conn.execute("DELETE FROM valves")
    conn.execute("DELETE FROM roles")
    conn.executemany(
        "INSERT INTO edges (a, b) VALUES (?, ?)",
        [(a, b) for a, b in scenario["edges"]],
    )
    conn.executemany(
        "INSERT INTO valves (vid, a, b, cost) VALUES (?, ?, ?, ?)",
        [(v["vid"], v["a"], v["b"], v["cost"]) for v in scenario["valves"]],
    )
    conn.executemany(
        "INSERT INTO roles (node, role) VALUES (?, ?)",
        [(n, "source") for n in scenario["sources"]]
        + [(n, "leak") for n in scenario["leaks"]]
        + [(n, "must") for n in scenario["musts"]],
    )


def save_scenario(scenario: dict) -> None:
    with get_conn() as conn:
        _save_scenario(conn, scenario)


def save_result(result: dict) -> dict:
    solved_at = datetime.now(timezone.utc).isoformat()
    payload = dict(result, solved_at=solved_at)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO results (id, payload, solved_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, solved_at = excluded.solved_at",
            (json.dumps(payload, ensure_ascii=False), solved_at),
        )
    return payload


def load_result() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT payload FROM results WHERE id = 1").fetchone()
    return json.loads(row["payload"]) if row else None
