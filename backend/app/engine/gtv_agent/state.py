"""成交漏斗状态机（对齐 GTV CRM 主链路）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

# 完整 CRM 链：线索→项目→跟进→报备→锁客→约看→带看→意向→谈价|直签→审批→签约→计租→回款→佣金
STAGES = (
    "clue",
    "project",
    "consult",
    "report",
    "lock",
    "schedule",
    "show",
    "intent",
    "negotiate",
    "direct",
    "approve",
    "signed",
    "rent",
    "payment",
    "settle",
    "lost",
)

STAGE_LABEL = {
    "clue": "线索接入",
    "project": "立项跟进",
    "consult": "咨询跟进",
    "report": "报备",
    "lock": "锁客",
    "schedule": "约看",
    "show": "带看",
    "intent": "意向确认",
    "negotiate": "谈价协商",
    "direct": "不谈价直签",
    "approve": "签约审批",
    "signed": "签约生效",
    "rent": "计租",
    "payment": "回款",
    "settle": "佣金归因",
    "lost": "流失",
}

_TRANSITIONS: dict[str, set[str]] = {
    "clue": {"project", "lost", "clue"},
    "project": {"consult", "lost", "project"},
    "consult": {"consult", "report", "lost"},
    "report": {"lock", "lost", "report"},
    "lock": {"schedule", "lost", "lock"},
    "schedule": {"show", "lost", "schedule"},
    "show": {"show", "intent", "lost"},
    "intent": {"negotiate", "direct", "intent", "lost", "approve"},
    "negotiate": {"negotiate", "approve", "intent", "lost"},
    "direct": {"approve", "lost", "direct"},
    "approve": {"signed", "intent", "lost", "approve"},
    "signed": {"rent", "lost"},
    "rent": {"payment", "rent"},
    "payment": {"settle", "payment"},
    "settle": set(),
    "lost": set(),
}

_LEGACY_STAGE = {"match": "clue"}


@dataclass
class DealThread:
    thread_id: str
    listing_id: str
    listing_type: str
    listing_name: str
    city_name: str
    list_price: float
    area: float
    broker_id: str
    broker_name: str
    client_id: str
    client_name: str
    client_budget: float
    client_need: str
    landlord_name: str
    clue_id: str = ""
    project_id: str = ""
    stage: str = "clue"
    heat: float = 0.0
    follow_count: int = 0
    show_count: int = 0
    min_follows: int = 1
    min_shows: int = 2
    negotiate_rounds: int = 0
    concession_pct: float = 0.0
    contract_money: Optional[float] = None
    commission: Optional[float] = None
    notes: List[str] = field(default_factory=list)
    boost_factor: float = 1.0
    negotiate_enabled: bool = False
    prefer_direct: bool = False
    reported: bool = False
    locked: bool = False
    approve_status: str = ""
    path: str = ""
    rent_start_days: Optional[int] = None
    payment_ratio: float = 0.0
    commission_user: str = ""
    closed: bool = False
    seed_source: str = "seed"
    address: str = ""
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    quality_score: float = 0.5
    quality_highlights: str = ""
    amap_address: str = ""
    amap_poi_summary: str = ""
    listing_profile: Dict[str, Any] = field(default_factory=dict)

    def listing_label(self) -> str:
        name = (self.listing_name or "").strip() or f"{self.city_name}{self.listing_type}"
        return f"{name}（ID:{self.listing_id}）"

    def broker_label(self) -> str:
        name = (self.broker_name or "").strip() or "经纪人"
        return f"{name}（ID:{self.broker_id}）"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["stage_label"] = STAGE_LABEL.get(self.stage, self.stage)
        d["listing_label"] = self.listing_label()
        d["broker_label"] = self.broker_label()
        return d

    def _set_contract(self, payload: Dict[str, Any]) -> None:
        base = float(self.list_price or self.client_budget or 50000)
        factor = 1.0 - float(self.concession_pct or 0)
        self.contract_money = float(
            payload.get("contract_money") or base * max(0.5, factor)
        )
        self.commission = float(
            payload.get("commission") or self.contract_money * 0.03
        )
        if not self.commission_user:
            self.commission_user = self.broker_id

    def _commit(self, nxt: str) -> str:
        if nxt == self.stage or nxt in _TRANSITIONS.get(self.stage, set()):
            self.stage = nxt
        else:
            order = {s: i for i, s in enumerate(STAGES)}
            if nxt in ("lost", "settle") or order.get(nxt, -1) >= order.get(self.stage, 0):
                self.stage = nxt
        if self.stage == "settle":
            self.closed = True
        if self.stage == "lost":
            self.closed = True
        return self.stage

    def apply_action(self, action: str, payload: Dict[str, Any] | None = None) -> str:
        payload = payload or {}
        if self.closed:
            return self.stage
        if self.stage in _LEGACY_STAGE:
            self.stage = _LEGACY_STAGE[self.stage]

        act = (action or "").strip().lower()
        nxt = self.stage

        if act in ("intake_clue", "match_ok"):
            nxt = "project" if self.stage in ("clue",) else self.stage
        elif act == "open_project":
            if self.stage == "clue":
                nxt = "project"
            elif self.stage == "project":
                nxt = "consult"
            else:
                nxt = self.stage
        elif act in ("inquire", "consult"):
            if self.stage in ("clue", "project"):
                nxt = "consult"
            else:
                nxt = "consult" if self.stage == "consult" else self.stage
            if nxt == "consult":
                self.follow_count += 1
                self.heat += 0.2 * self.boost_factor
        elif act in ("follow_up", "boost_touch"):
            self.follow_count += 1
            self.heat += 0.3 * self.boost_factor
            if self.stage == "clue":
                nxt = "project"
            elif self.stage == "project":
                nxt = "consult"
            else:
                # 跟进可多次停留；报备由 submit_report 显式进入
                nxt = self.stage
        elif act == "submit_report":
            self.reported = True
            nxt = "report"
        elif act == "lock_client":
            self.locked = True
            self.reported = True
            nxt = "lock"
        elif act == "schedule_show":
            if not self.reported:
                self.reported = True
            if not self.locked:
                self.locked = True
            nxt = "schedule"
        elif act in ("complete_show", "show"):
            self.show_count += 1
            self.heat += 1.0 * self.boost_factor
            nxt = "show"
        elif act in ("express_intent", "intent"):
            nxt = "intent"
            self.heat += 0.5
        elif act in ("start_negotiate", "negotiate", "counter_offer"):
            self.path = "negotiate"
            self.negotiate_enabled = True
            self.negotiate_rounds += 1
            c = float(payload.get("concession_pct") or self.concession_pct or 0.05)
            self.concession_pct = max(self.concession_pct, min(0.4, c))
            nxt = "negotiate"
        elif act in ("buy_at_list", "direct_sign"):
            self.path = "direct"
            self.prefer_direct = True
            self.concession_pct = 0.0
            self._set_contract(payload)
            nxt = "direct"
        elif act == "accept_deal":
            if self.stage == "negotiate" or self.path == "negotiate":
                self.path = "negotiate"
                self._set_contract(payload)
                self.approve_status = "pending"
                nxt = "approve"
            elif self.prefer_direct or (not self.negotiate_enabled and self.stage in ("intent", "direct")):
                self.path = "direct"
                self._set_contract(payload)
                nxt = "direct"
            else:
                self._set_contract(payload)
                self.approve_status = "pending"
                nxt = "approve"
        elif act == "submit_sign":
            if self.contract_money is None:
                self._set_contract(payload)
            self.approve_status = "pending"
            if self.stage == "negotiate":
                self.path = self.path or "negotiate"
            elif self.stage == "direct":
                self.path = self.path or "direct"
            nxt = "approve"
        elif act in ("approve_sign", "sign", "signed"):
            if self.contract_money is None:
                self._set_contract(payload)
            self.approve_status = "approved"
            nxt = "signed"
        elif act == "reject_sign":
            self.approve_status = "rejected"
            nxt = "intent"
        elif act == "set_rent_start":
            self.rent_start_days = int(
                payload.get("rent_start_days") or self.rent_start_days or 7
            )
            nxt = "rent"
        elif act == "record_payment":
            self.payment_ratio = float(payload.get("payment_ratio") or 1.0)
            nxt = "payment"
        elif act == "settle_commission":
            if not self.commission_user:
                self.commission_user = self.broker_id
            if self.commission is None and self.contract_money:
                self.commission = float(self.contract_money) * 0.03
            nxt = "settle"
        elif act in ("reject", "walk_away", "lost", "timeout"):
            nxt = "lost"
        else:
            if self.stage == "clue":
                nxt = "project"

        return self._commit(nxt)


def summarize_threads(threads: List[DealThread]) -> Dict[str, Any]:
    closed_ok = [t for t in threads if t.stage == "settle"]
    in_pipeline = [
        t
        for t in threads
        if t.stage in ("signed", "rent", "payment", "settle")
        or t.approve_status == "approved"
    ]
    lost = [t for t in threads if t.stage == "lost"]
    active = [t for t in threads if not t.closed]
    direct_signed = [t for t in in_pipeline if t.path == "direct"]
    nego_signed = [t for t in in_pipeline if t.path == "negotiate"]
    money_threads = [
        t for t in threads if t.contract_money and t.stage not in ("lost",)
    ]
    return {
        "n_threads": len(threads),
        "n_signed": len(closed_ok) or len(
            [t for t in threads if t.stage in ("signed", "rent", "payment", "settle")]
        ),
        "n_lost": len(lost),
        "n_active": len(active),
        "n_reported": sum(1 for t in threads if t.reported),
        "n_locked": sum(1 for t in threads if t.locked),
        "n_direct_signed": len(direct_signed),
        "n_nego_signed": len(nego_signed),
        "n_approved": sum(1 for t in threads if t.approve_status == "approved"),
        "n_payment": sum(
            1 for t in threads if t.stage in ("payment", "settle") or t.payment_ratio > 0
        ),
        "expected_contract_money": float(sum(t.contract_money or 0 for t in money_threads)),
        "expected_commission": float(sum(t.commission or 0 for t in money_threads)),
        "by_stage": {s: sum(1 for t in threads if t.stage == s) for s in STAGES},
    }
