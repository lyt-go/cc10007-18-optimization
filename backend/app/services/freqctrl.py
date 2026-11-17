"""频控窗口裁量业务规则。

按进出人群生成窗口裁量表：从用于效率改进的目标人群变化记录中按受影响记录
读取触发事件，计算频控后的推送名单，形成效率优化后的频控窗口裁量明细表。

硬性约束：
- 只替换真正进入或离开目标人群的用户，保留其他用户的冷却截止时间；
- 进出人群记录与已完成动作分别记录；
- 刷新失败不改写已发送与冷却中的记录（先算后写，一次性提交）；
- 重复提交只登记一份可用于结算的频控窗口裁量核对表结果；
- 同一分流批次的推送名单只能对应一套人群快照，冲突时沿调用链抛出版本断点；
- 每一次成功刷新都按数据版本登记核对表，支持按版本回查。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

RULE_MODULE = "realtime"
PLAN_MODULE = "pushplan"
BATCH_MODULE = "pushbatch"
CHANGE_MODULE = "audiencechange"
CHECK_MODULE = "freqctrl"

DEFAULT_COOLDOWN_SECONDS = 24 * 3600
LOCKED_STATES = ("已发送", "冷却中")  # 已完成动作：任何刷新都不得改写这两类记录
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class DiscretionError(Exception):
    """裁量刷新链路异常：携带数据版本断点，便于沿原始调用链核验定位。"""

    def __init__(self, message: str, *, version_breakpoint: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.version_breakpoint = version_breakpoint


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), TIME_FORMAT)
    except ValueError:
        return None


def _cooldown_seconds(rule: dict[str, Any]) -> int:
    """读取规则冷却时间秒；历史数据里不是纯数字时回落到默认 24 小时。"""
    try:
        seconds = int(str(rule.get("冷却时间秒") or "").strip())
    except (TypeError, ValueError):
        return DEFAULT_COOLDOWN_SECONDS
    return seconds if seconds > 0 else DEFAULT_COOLDOWN_SECONDS


def _next_code(rows: list[dict[str, Any]], field: str, prefix: str) -> str:
    seq = 0
    for row in rows:
        code = str(row.get(field) or "")
        if code.startswith(prefix):
            try:
                seq = max(seq, int(code[len(prefix):]))
            except ValueError:
                continue
    return f"{prefix}{seq + 1:04d}"


class FreqctrlService:
    # ---------- 查询 ----------

    def discretion_overview(self, rule_id: int) -> dict[str, Any] | None:
        """实时决策裁量总览：批次现状、目标人群变化记录与已登记核对表。"""
        rule = store.find(RULE_MODULE, rule_id)
        if rule is None:
            return None
        rule_code = str(rule.get("规则编号"))
        batches = [b for b in store.rows(BATCH_MODULE) if b.get("关联规则") == rule_code]
        changes = [c for c in store.rows(CHANGE_MODULE) if c.get("关联规则") == rule_code]
        checklists = [c for c in store.rows(CHECK_MODULE) if c.get("关联规则") == rule_code]
        return {
            "规则编号": rule_code,
            "规则状态": rule.get("status"),
            "冷却时间秒": _cooldown_seconds(rule),
            "批次": [self._batch_view(batch) for batch in batches],
            "变化记录": changes,
            "核对表": checklists,
        }

    def checklists_by_version(
        self, rule_id: int, version: int
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """按数据版本回查裁量刷新后登记的核对表。"""
        rule = store.find(RULE_MODULE, rule_id)
        if rule is None:
            return None, []
        rule_code = str(rule.get("规则编号"))
        items = [
            row
            for row in store.rows(CHECK_MODULE)
            if row.get("关联规则") == rule_code and int(row.get("数据版本", 0)) == version
        ]
        return rule, items

    def plan_pending_details(self, plan_id: int) -> dict[str, Any] | None:
        """推送计划待处理明细：登记在案的频控窗口裁量核对表与批次现状。"""
        plan = store.find(PLAN_MODULE, plan_id)
        if plan is None:
            return None
        plan_code = str(plan.get("方案编号"))
        batches = [b for b in store.rows(BATCH_MODULE) if b.get("关联方案") == plan_code]
        checklists = [c for c in store.rows(CHECK_MODULE) if c.get("关联方案") == plan_code]
        return {
            "方案编号": plan_code,
            "方案状态": plan.get("status"),
            "实时决策状态": self.synced_rule_status(plan_code),
            "批次": [self._batch_view(batch) for batch in batches],
            "核对表": checklists,
        }

    def synced_rule_status(self, plan_code: str) -> str:
        """把关联实时决策规则的状态同步成推送计划清单可展示的文案。"""
        codes = sorted(
            {
                str(batch.get("关联规则"))
                for batch in store.rows(BATCH_MODULE)
                if batch.get("关联方案") == plan_code and batch.get("关联规则")
            }
        )
        parts: list[str] = []
        for code in codes:
            rule = next(
                (row for row in store.rows(RULE_MODULE) if row.get("规则编号") == code),
                None,
            )
            if rule is not None:
                parts.append(f"{code}:{rule.get('status')}")
        return "、".join(parts)

    # ---------- 裁量刷新 ----------

    def refresh_discretion(
        self, rule_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        """按进出人群生成窗口裁量表，并把核对表登记到推送计划待处理明细。

        返回 (核对表, 说明)；链路异常时抛出 DiscretionError（含数据版本断点），
        此时不触碰任何已发送与冷却中记录。
        """
        rule = store.find(RULE_MODULE, rule_id)
        if rule is None:
            raise DiscretionError(f"决策规则 {rule_id} 不存在或已归档")
        rule_code = str(rule.get("规则编号"))

        change_ref = str(values.get("记录编号") or "").strip()
        if not change_ref:
            raise DiscretionError("缺少目标人群变化记录编号，无法生成窗口裁量表")
        change = next(
            (c for c in store.rows(CHANGE_MODULE) if c.get("记录编号") == change_ref),
            None,
        )
        if change is None:
            raise DiscretionError(f"目标人群变化记录 {change_ref} 不存在")
        if change.get("关联规则") != rule_code:
            raise DiscretionError(f"目标人群变化记录 {change_ref} 不属于规则 {rule_code}")
        if change.get("用途") != "效率改进":
            raise DiscretionError(
                f"目标人群变化记录 {change_ref} 用途为「{change.get('用途')}」，不能用于效率改进裁量"
            )

        batch = next(
            (
                b
                for b in store.rows(BATCH_MODULE)
                if b.get("批次号") == change.get("分流批次") and b.get("关联规则") == rule_code
            ),
            None,
        )
        if batch is None:
            raise DiscretionError(
                f"分流批次 {change.get('分流批次')} 在规则 {rule_code} 下没有推送批次"
            )
        breakpoint_version = int(batch.get("数据版本", 0))

        # 重复提交拦截：同一提交指纹只登记一份可用于结算的核对表。
        fingerprint = self._fingerprint(rule_code, batch, change, values.get("提交指纹"))
        existing = self._find_checklist(fingerprint)
        if existing is not None:
            return existing, (
                f"重复提交已拦截：核对表 {existing['核对编号']} 已登记且可用于结算，"
                "本次不再重复登记"
            )

        current_snapshot = str(batch.get("人群快照版本") or "")
        old_snapshot = str(change.get("旧快照版本") or "")
        new_snapshot = str(change.get("新快照版本") or "")
        if current_snapshot == new_snapshot:
            raise DiscretionError(
                f"分流批次 {batch['批次号']} 已处于快照 {new_snapshot}，"
                f"变化记录 {change_ref} 无需重复应用",
                version_breakpoint=breakpoint_version,
            )
        if current_snapshot != old_snapshot:
            # 新旧快照同时覆盖同一分流批次：当前推送名单只能对应一套人群快照。
            raise DiscretionError(
                f"分流批次 {batch['批次号']} 当前快照 {current_snapshot} 与变化记录基准快照 "
                f"{old_snapshot} 不一致：同一分流批次的推送名单只能对应一套人群快照，"
                "请先应用基准快照对应的变化记录",
                version_breakpoint=breakpoint_version,
            )

        affected = [r for r in (change.get("受影响记录") or []) if r.get("用户ID")]
        entering = [r for r in affected if r.get("方向") == "进入"]
        leaving_ids = {str(r.get("用户ID")) for r in affected if r.get("方向") == "离开"}
        cooldown = _cooldown_seconds(rule)

        # —— 计算阶段：只读现有批次，全部结果先算好再一次性提交 ——
        new_users: list[dict[str, Any]] = []
        annotated_list: list[dict[str, Any]] = []
        inout_records: list[dict[str, Any]] = []
        completed_actions: list[dict[str, Any]] = []
        retained_trace: list[dict[str, Any]] = []
        newcomer_trace: list[dict[str, Any]] = []

        for user in batch.get("用户名单") or []:
            uid = str(user.get("用户ID"))
            if uid in leaving_ids:
                inout_records.append(
                    {
                        "用户ID": uid,
                        "方向": "离开",
                        "触发事件": self._affected_event(affected, uid),
                        "原状态": user.get("状态"),
                        "原冷却截止时间": user.get("冷却截止时间"),
                    }
                )
                if user.get("状态") in LOCKED_STATES:
                    completed_actions.append(self._completed_view(user))
                continue  # 真正离开目标人群的用户才从推送名单移除
            # 保留用户：状态与冷却截止时间原样保留，按截止时间追溯。
            kept = dict(user)
            new_users.append(kept)
            annotated_list.append({**kept, "追溯口径": "保留用户"})
            retained_trace.append({"用户ID": uid, "冷却截止时间": kept.get("冷却截止时间")})
            if kept.get("状态") in LOCKED_STATES:
                completed_actions.append(self._completed_view(kept))

        known_ids = {str(u.get("用户ID")) for u in new_users}
        for record in entering:
            uid = str(record.get("用户ID"))
            inout_records.append(
                {
                    "用户ID": uid,
                    "方向": "进入",
                    "触发事件": record.get("触发事件"),
                    "事件时间": record.get("事件时间"),
                }
            )
            if uid in known_ids:
                # 已在名单中（含已发送/冷却中）：不得再次写入，保留原状态与冷却截止时间。
                continue
            deadline = self._shift_deadline(record.get("事件时间"), cooldown)
            newcomer = {
                "用户ID": uid,
                "状态": "待发送",
                "触发事件": record.get("触发事件"),
                "发送时间": None,
                "冷却截止时间": deadline,
            }
            new_users.append(newcomer)
            known_ids.add(uid)
            annotated_list.append({**newcomer, "追溯口径": "新入用户"})
            newcomer_trace.append(
                {
                    "用户ID": uid,
                    "触发事件": record.get("触发事件"),
                    "冷却截止时间": deadline,
                }
            )

        sendable = [str(u.get("用户ID")) for u in new_users if u.get("状态") == "待发送"]
        checklist = {
            "id": max((int(c.get("id", 0)) for c in store.rows(CHECK_MODULE)), default=0) + 1,
            "status": "已登记",
            "pending": True,
            "abnormal": False,
            "核对编号": _next_code(store.rows(CHECK_MODULE), "核对编号", "FC-"),
            "关联规则": rule_code,
            "关联方案": batch.get("关联方案"),
            "分流批次": batch.get("批次号"),
            "数据版本": breakpoint_version + 1,
            "快照版本": new_snapshot,
            "基准快照版本": old_snapshot,
            "变化记录": change_ref,
            "推送名单": annotated_list,
            "进出人群记录": inout_records,
            "已完成动作": completed_actions,
            "保留用户追溯": retained_trace,
            "新入用户追溯": newcomer_trace,
            "待发送人数": len(sendable),
            "可发送名单": sendable,
            "结算状态": "可用于结算",
            "提交指纹": fingerprint,
            "登记时间": datetime.now().strftime(TIME_FORMAT),
        }

        # —— 提交阶段：一次性写回；写回失败时抛出断点，已发送与冷却中记录保持原样 ——
        try:
            batch["用户名单"] = new_users
            batch["数据版本"] = breakpoint_version + 1
            batch["人群快照版本"] = new_snapshot
            change["status"] = "已处理"
            change["pending"] = False
            store.rows(CHECK_MODULE).append(checklist)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            raise DiscretionError(
                f"裁量结果写回失败：{exc}", version_breakpoint=breakpoint_version
            ) from exc

        return checklist, (
            f"频控窗口裁量核对表 {checklist['核对编号']} 已登记到推送计划待处理明细，"
            f"分流批次 {batch['批次号']} 数据版本升至 v{breakpoint_version + 1}，可按版本回查"
        )

    # ---------- 内部工具 ----------

    def _batch_view(self, batch: dict[str, Any]) -> dict[str, Any]:
        users = batch.get("用户名单") or []
        return {
            "批次号": batch.get("批次号"),
            "关联规则": batch.get("关联规则"),
            "关联方案": batch.get("关联方案"),
            "AB分组标识": batch.get("AB分组标识"),
            "数据版本": batch.get("数据版本"),
            "人群快照版本": batch.get("人群快照版本"),
            "待发送人数": sum(1 for u in users if u.get("状态") == "待发送"),
            "用户名单": users,
        }

    def _completed_view(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            "用户ID": user.get("用户ID"),
            "动作": user.get("状态"),
            "触发事件": user.get("触发事件"),
            "时间": user.get("发送时间"),
            "冷却截止时间": user.get("冷却截止时间"),
        }

    def _shift_deadline(self, event_time: Any, cooldown_seconds: int) -> str:
        base = _parse_time(event_time) or datetime.now()
        return (base + timedelta(seconds=cooldown_seconds)).strftime(TIME_FORMAT)

    def _affected_event(self, affected: list[dict[str, Any]], uid: str) -> Any:
        for record in affected:
            if str(record.get("用户ID")) == uid:
                return record.get("触发事件")
        return None

    def _fingerprint(
        self,
        rule_code: str,
        batch: dict[str, Any],
        change: dict[str, Any],
        submit_key: Any,
    ) -> str:
        token = str(submit_key or change.get("记录编号") or "").strip()
        return "|".join(
            [
                rule_code,
                str(batch.get("批次号")),
                str(change.get("旧快照版本")),
                str(change.get("新快照版本")),
                token,
            ]
        )

    def _find_checklist(self, fingerprint: str) -> dict[str, Any] | None:
        for row in store.rows(CHECK_MODULE):
            if row.get("提交指纹") == fingerprint:
                return row
        return None
