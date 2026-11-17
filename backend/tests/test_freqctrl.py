"""REAL-0001 主核对样例：频控窗口裁量端到端核验。

覆盖：
- 原始调用链异常修复（扁平 action 提交）与 REAL-0001 状态同步到推送计划清单；
- 按进出人群生成窗口裁量表，只替换真正进出人群的用户；
- 已发送用户不被重新触达、冷却中用户不被再次写入、冷却截止时间保留；
- 进出人群记录与已完成动作分别记录；
- 刷新失败不改写已发送与冷却中记录，并给出数据版本断点；
- 重复提交只登记一份可用于结算的核对表；
- 新旧快照同时覆盖同一分流批次时，推送名单只对应一套人群快照；
- 未变化批次没有无依据刷新；
- 频控窗口刷新可按数据版本回查；
- 推送计划待处理明细登记核对表，兼容既有 FC-0001 业务记录。
"""
from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from app.main import app
from app.seed import SEED_ROWS
from app.store import store

client = TestClient(app)


def reset_store() -> None:
    """每个用例前重置内存仓库，深拷贝避免污染种子数据。"""
    store._tables = {name: copy.deepcopy(rows) for name, rows in SEED_ROWS.items()}


def _pushplan(code: str) -> dict:
    plans = client.get("/api/pushplan").json()["items"]
    return next(item for item in plans if item["方案编号"] == code)


def _batch(overview: dict, batch_no: str) -> dict:
    return next(item for item in overview["批次"] if item["批次号"] == batch_no)


def test_action_call_chain_and_status_sync() -> None:
    """扁平 action 提交的原始调用链修复后，REAL-0001 状态同步到推送计划清单。"""
    reset_store()
    assert "REAL-0001:草稿" in _pushplan("PUSH-0001")["实时决策状态"]

    resp = client.post("/api/realtime/1/actions", json={"action": "生效规则"})
    assert resp.json()["ok"], resp.json()["message"]
    assert resp.json()["entry"]["status"] == "已生效"

    assert "REAL-0001:已生效" in _pushplan("PUSH-0001")["实时决策状态"]


def test_real_0001_discretion_scenario() -> None:
    """REAL-0001 主核对样例：裁量刷新、幂等、版本回查与待处理明细登记。"""
    reset_store()

    # 初始总览：B-01 待发送 2 人，B-02 待发送 1 人
    overview = client.get("/api/realtime/1/discretion").json()
    assert _batch(overview, "B-01")["数据版本"] == 1
    assert _batch(overview, "B-01")["待发送人数"] == 2

    # 版本断点：AC-0002 基准快照 SNAP-02 与当前 SNAP-01 不一致，必须失败且不改写任何记录
    before = copy.deepcopy(client.get("/api/realtime/1/discretion").json())
    resp = client.post("/api/realtime/1/discretion/refresh", json={"values": {"记录编号": "AC-0002"}})
    payload = resp.json()
    assert not payload["ok"]
    assert "数据版本断点：v1" in payload["message"]
    assert "只能对应一套人群快照" in payload["message"]
    after = client.get("/api/realtime/1/discretion").json()
    assert before == after, "刷新失败不得改写已发送与冷却中记录"

    # 应用 AC-0001：只替换真正进出人群的用户
    resp = client.post("/api/realtime/1/discretion/refresh", json={"values": {"记录编号": "AC-0001"}})
    payload = resp.json()
    assert payload["ok"], payload["message"]
    checklist = payload["entry"]
    assert checklist["核对编号"] == "FC-0002"
    assert checklist["数据版本"] == 2
    assert checklist["结算状态"] == "可用于结算"

    users = {user["用户ID"]: user for user in checklist["推送名单"]}
    assert set(users) == {"U1002", "U1003", "U1005", "U1006"}
    assert "U1001" not in users, "已发送用户不被重新触达"
    # 保留用户冷却截止时间原样保留
    assert users["U1002"]["状态"] == "冷却中"
    assert users["U1002"]["冷却截止时间"] == "2026-11-18 08:00:00"
    assert users["U1002"]["追溯口径"] == "保留用户"
    # 新入用户按事件时间 + 冷却时间秒追溯
    assert users["U1005"]["追溯口径"] == "新入用户"
    assert users["U1005"]["冷却截止时间"] == "2026-11-17 09:00:00"
    assert users["U1006"]["冷却截止时间"] == "2026-11-17 09:05:00"
    assert checklist["待发送人数"] == 3
    assert checklist["可发送名单"] == ["U1003", "U1005", "U1006"]

    # 进出人群记录与已完成动作分别记录
    assert {r["用户ID"] for r in checklist["进出人群记录"]} == {"U1001", "U1004", "U1005", "U1006"}
    assert {a["用户ID"] for a in checklist["已完成动作"]} == {"U1001", "U1002"}
    sent = next(a for a in checklist["已完成动作"] if a["用户ID"] == "U1001")
    assert sent["动作"] == "已发送"
    assert sent["冷却截止时间"] == "2026-11-12 10:00:00"

    # 重复提交只登记一份可用于结算的核对表，版本不重复推进
    resp = client.post("/api/realtime/1/discretion/refresh", json={"values": {"记录编号": "AC-0001"}})
    payload = resp.json()
    assert payload["ok"]
    assert payload["entry"]["核对编号"] == "FC-0002"
    overview = client.get("/api/realtime/1/discretion").json()
    assert len(overview["核对表"]) == 2  # 既有 FC-0001 + 新登记 FC-0002
    assert _batch(overview, "B-01")["数据版本"] == 2

    # 应用 AC-0002：冷却中用户 U1002 出现在进入记录中也不得再次写入
    resp = client.post("/api/realtime/1/discretion/refresh", json={"values": {"记录编号": "AC-0002"}})
    payload = resp.json()
    assert payload["ok"], payload["message"]
    checklist = payload["entry"]
    assert checklist["核对编号"] == "FC-0003"
    assert checklist["数据版本"] == 3
    users = {user["用户ID"]: user for user in checklist["推送名单"]}
    assert set(users) == {"U1002", "U1005", "U1006", "U1007"}
    assert users["U1002"]["状态"] == "冷却中"
    assert users["U1002"]["冷却截止时间"] == "2026-11-18 08:00:00", "冷却中用户不被再次写入"
    assert users["U1007"]["冷却截止时间"] == "2026-11-17 10:00:00"

    # 未变化批次没有无依据刷新
    overview = client.get("/api/realtime/1/discretion").json()
    batch_b02 = _batch(overview, "B-02")
    assert batch_b02["数据版本"] == 1
    assert batch_b02["人群快照版本"] == "SNAP-01"

    # 同一分流批次的推送名单只对应一套人群快照
    batch_b01 = _batch(overview, "B-01")
    assert batch_b01["人群快照版本"] == "SNAP-03"
    assert batch_b01["数据版本"] == 3

    # 按数据版本回查
    v2 = client.get("/api/realtime/1/discretion/versions/2").json()
    assert [item["核对编号"] for item in v2["items"]] == ["FC-0002"]
    v3 = client.get("/api/realtime/1/discretion/versions/3").json()
    assert [item["核对编号"] for item in v3["items"]] == ["FC-0003"]

    # 推送计划待处理明细登记核对表，兼容既有 FC-0001 业务记录
    details = client.get("/api/pushplan/1/pending-details").json()
    assert [item["核对编号"] for item in details["核对表"]] == ["FC-0001", "FC-0002", "FC-0003"]
    assert "REAL-0001" in details["实时决策状态"]


def test_refresh_failure_keeps_locked_records() -> None:
    """链路异常一律不改写已发送与冷却中记录。"""
    reset_store()
    before = copy.deepcopy(client.get("/api/realtime/1/discretion").json())

    # 缺少记录编号
    resp = client.post("/api/realtime/1/discretion/refresh", json={"values": {}})
    assert not resp.json()["ok"]
    # 记录不存在
    resp = client.post("/api/realtime/1/discretion/refresh", json={"values": {"记录编号": "AC-9999"}})
    assert not resp.json()["ok"]
    # 规则不存在
    resp = client.post("/api/realtime/999/discretion/refresh", json={"values": {"记录编号": "AC-0001"}})
    assert not resp.json()["ok"]

    after = client.get("/api/realtime/1/discretion").json()
    assert before == after
