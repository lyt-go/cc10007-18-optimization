"""实时决策接口：维护决策规则，覆盖提交规则评审、生效规则、暂停规则等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.freqctrl import DiscretionError, FreqctrlService
from app.services.realtime import RealtimeService

router = APIRouter(prefix="/api/realtime", tags=["实时决策"])

service = RealtimeService()
freqctrl = FreqctrlService()

LIST_FIELDS = ["规则编号", "触发事件", "决策条件", "执行动作", "冷却时间秒", "优先级", "分流比例", "生效时段"]
STATUSES = ["草稿", "规则评审中", "已生效", "已暂停"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    status: str | None = Query(default=None, description="草稿、规则评审中、已生效、已暂停"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按规则编号与状态过滤实时决策列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条决策规则明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"决策规则 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条决策规则，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="决策规则已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条决策规则执行提交规则评审、生效规则、暂停规则；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}/discretion")
def discretion_overview(entry_id: int) -> dict[str, Any]:
    """频控窗口裁量总览：推送批次现状、目标人群变化记录与已登记核对表。"""
    overview = freqctrl.discretion_overview(entry_id)
    if overview is None:
        raise HTTPException(status_code=404, detail=f"决策规则 {entry_id} 不存在或已归档")
    return overview


@router.post("/{entry_id}/discretion/refresh", response_model=ActionResult)
def refresh_discretion(entry_id: int, payload: EntryPayload) -> ActionResult:
    """按进出人群生成窗口裁量表；链路异常时返回数据版本断点，且不改写已发送与冷却中记录。"""
    try:
        checklist, message = freqctrl.refresh_discretion(entry_id, payload.values)
    except DiscretionError as error:
        detail = error.message
        if error.version_breakpoint is not None:
            detail = f"{detail}（数据版本断点：v{error.version_breakpoint}）"
        return ActionResult(ok=False, message=detail)
    return ActionResult(ok=True, message=message, entry=checklist)


@router.get("/{entry_id}/discretion/versions/{version}")
def discretion_by_version(entry_id: int, version: int) -> dict[str, Any]:
    """按数据版本回查裁量刷新后登记的频控窗口裁量核对表。"""
    rule, items = freqctrl.checklists_by_version(entry_id, version)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"决策规则 {entry_id} 不存在或已归档")
    return {
        "规则编号": rule.get("规则编号"),
        "数据版本": version,
        "items": items,
        "total": len(items),
    }


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出实时决策清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "realtime", "total": total, "items": items}
