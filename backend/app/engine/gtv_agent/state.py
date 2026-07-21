"""成交漏斗状态机（对齐 GTV project_stage；线索多经纪先签先赢）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# GTV e_sys_dict project_stage：未推进→夯实→房源匹配→带看→谈判→签约
STAGES = (
    "idle",
    "solidify",
    "match",
    "show",
    "negotiate",
    "signed",
    "lost",
)

STAGE_LABEL = {
    "idle": "未推进",
    "solidify": "夯实",
    "match": "房源匹配",
    "show": "带看",
    "negotiate": "谈判",
    "signed": "签约",
    "lost": "流失",
    "clue": "未推进",
    "project": "未推进",
    "consult": "夯实",
    "report": "房源匹配",
    "lock": "房源匹配",
    "schedule": "带看",
    "intent": "谈判",
    "direct": "谈判",
    "approve": "签约",
    "rent": "签约",
    "payment": "签约",
    "settle": "签约",
}

ROLE_LABEL = {
    "winner": "胜出",
    "contributor": "协作",
    "loser": "落败",
    "lost": "流失",
}

_TERMINAL_STAGES = frozenset({"signed", "lost"})

_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"solidify", "lost", "idle"},
    "solidify": {"solidify", "match", "lost"},
    "match": {"match", "show", "lost"},
    "show": {"show", "negotiate", "signed", "lost"},
    "negotiate": {"negotiate", "signed", "lost"},
    "signed": set(),
    "lost": set(),
}

_LEGACY_STAGE = {
    "clue": "idle",
    "project": "idle",
    "consult": "solidify",
    "report": "match",
    "lock": "match",
    "schedule": "show",
    "intent": "negotiate",
    "direct": "negotiate",
    "approve": "signed",
    "rent": "signed",
    "payment": "signed",
    "settle": "signed",
}


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
    deal_group_id: str = ""
    stage: str = "idle"
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
    coop_bias: float = 0.3
    coop_with: List[str] = field(default_factory=list)
    role_outcome: str = ""
    path: str = ""
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
    last_reason: str = ""
    persona: Dict[str, Any] = field(default_factory=dict)
    persona_label: str = ""

    def listing_label(self) -> str:
        name = (self.listing_name or "").strip() or f"{self.city_name}{self.listing_type}"
        return f"{name}（ID:{self.listing_id}）"

    def broker_label(self) -> str:
        name = (self.broker_name or "").strip() or "经纪人"
        return f"{name}（ID:{self.broker_id}）"

    def normalize_stage(self) -> str:
        if self.stage in _LEGACY_STAGE:
            self.stage = _LEGACY_STAGE[self.stage]
        if not self.deal_group_id:
            self.deal_group_id = self.clue_id or self.thread_id
        return self.stage

    def to_dict(self) -> Dict[str, Any]:
        self.normalize_stage()
        d = asdict(self)
        d["stage_label"] = STAGE_LABEL.get(self.stage, self.stage)
        d["listing_label"] = self.listing_label()
        d["broker_label"] = self.broker_label()
        d["role_outcome_label"] = ROLE_LABEL.get(self.role_outcome, self.role_outcome)
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

    def _add_coop(self, peer_id: str) -> None:
        pid = str(peer_id or "").strip()
        if pid and pid != self.broker_id and pid not in self.coop_with:
            self.coop_with.append(pid)

    def _commit(self, nxt: str) -> str:
        nxt = _LEGACY_STAGE.get(nxt, nxt)
        if nxt == self.stage or nxt in _TRANSITIONS.get(self.stage, set()):
            self.stage = nxt
        else:
            order = {s: i for i, s in enumerate(STAGES)}
            if nxt in _TERMINAL_STAGES or order.get(nxt, -1) >= order.get(self.stage, 0):
                self.stage = nxt
        if self.stage in _TERMINAL_STAGES:
            self.closed = True
            if self.stage == "lost" and not self.role_outcome:
                self.role_outcome = "lost"
        return self.stage

    def apply_action(
        self,
        action: str,
        payload: Dict[str, Any] | None = None,
        *,
        peers: Optional[List["DealThread"]] = None,
    ) -> str:
        payload = payload or {}
        if self.closed:
            return self.stage
        self.normalize_stage()

        act = (action or "").strip().lower()
        if act in ("set_rent_start", "record_payment", "settle_commission"):
            return self.stage
        if act in ("submit_report", "lock_client"):
            return self._commit("match")
        if act == "schedule_show":
            return self._commit("show")
        if act in ("express_intent", "intent"):
            return self._commit("negotiate" if self.stage in ("show", "match") else self.stage)
        if act in ("submit_sign", "approve_sign"):
            if self.contract_money is None:
                self._set_contract(payload)
            return self._commit("signed")
        if act == "reject_sign":
            return self._commit("negotiate")

        # 协作：不新增虚假 CRM 阶段
        if act in ("refer_coop", "assist_show", "handoff"):
            target_id = str(
                payload.get("target_broker_id")
                or payload.get("target_thread_id")
                or ""
            ).strip()
            peer = None
            if peers:
                for p in peers:
                    if p.closed or p.thread_id == self.thread_id:
                        continue
                    if p.deal_group_id != self.deal_group_id:
                        continue
                    if target_id and (
                        p.broker_id == target_id or p.thread_id == target_id
                    ):
                        peer = p
                        break
                if peer is None:
                    cands = [
                        p
                        for p in peers
                        if not p.closed
                        and p.thread_id != self.thread_id
                        and p.deal_group_id == self.deal_group_id
                    ]
                    if cands:
                        peer = max(cands, key=lambda x: (x.heat, x.show_count, x.follow_count))
            if peer:
                self._add_coop(peer.broker_id)
                peer._add_coop(self.broker_id)
                if act == "assist_show":
                    peer.show_count += 1
                    peer.heat += 0.6 * peer.boost_factor
                    if peer.stage in ("idle", "solidify", "match"):
                        peer._commit("show")
                    self.heat += 0.2
                elif act == "handoff":
                    peer.heat += 0.8 * peer.boost_factor
                    peer.notes.append(f"接手主谈←{self.broker_name}")
                    self.notes.append(f"交接主谈→{peer.broker_name}")
                else:  # refer_coop
                    peer.heat += 0.4
                    peer.notes.append(f"获转介←{self.broker_name}")
                    self.heat += 0.15
            # 协作后本线程小幅推进或停留
            if self.stage == "idle":
                return self._commit("solidify")
            if self.stage == "solidify" and self.follow_count >= self.min_follows:
                return self._commit("match")
            return self.stage

        nxt = self.stage

        if act in ("intake_clue", "open_project", "start_project", "open_idle"):
            nxt = "solidify" if self.stage == "idle" and act != "open_idle" else self.stage
        elif act in ("solidify", "inquire", "consult", "follow_up", "boost_touch"):
            self.follow_count += 1
            self.heat += 0.3 * self.boost_factor
            nxt = "solidify" if self.stage in ("idle", "solidify") else self.stage
        elif act in ("match_listing", "match_ok", "assign_listing"):
            nxt = "match"
            self.heat += 0.2
        elif act in ("complete_show", "show"):
            self.show_count += 1
            self.heat += 1.0 * self.boost_factor
            nxt = "show"
        elif act in ("start_negotiate", "negotiate", "counter_offer"):
            self.path = "negotiate"
            self.negotiate_enabled = True
            self.negotiate_rounds += 1
            c = float(payload.get("concession_pct") or self.concession_pct or 0.05)
            self.concession_pct = max(self.concession_pct, min(0.4, c))
            nxt = "negotiate"
        elif act in ("buy_at_list", "direct_sign", "sign_direct"):
            self.path = "direct"
            self.prefer_direct = True
            self.concession_pct = 0.0
            self._set_contract(payload)
            nxt = "signed"
        elif act in ("accept_deal", "sign", "signed", "close_deal"):
            if self.contract_money is None:
                self._set_contract(payload)
            if not self.path:
                self.path = "negotiate" if self.negotiate_enabled else "direct"
            nxt = "signed"
        elif act in ("reject", "walk_away", "lost", "timeout"):
            nxt = "lost"
        else:
            if self.stage == "idle":
                nxt = "solidify"

        return self._commit(nxt)


def close_clue_group_on_sign(
    threads: List[DealThread], winner: DealThread
) -> List[Tuple[DealThread, str, str, str]]:
    """先签先赢：关闭同线索其余线程，返回 (thread, text, reason, prev_stage)。"""
    group = winner.deal_group_id or winner.clue_id
    winner.role_outcome = "winner"
    winner.stage = "signed"
    winner.closed = True
    closed_events: List[Tuple[DealThread, str, str, str]] = []
    win_label = winner.broker_label()
    for t in threads:
        if t.thread_id == winner.thread_id:
            continue
        if (t.deal_group_id or t.clue_id) != group:
            continue
        if t.role_outcome == "winner":
            continue
        if t.closed and t.role_outcome in ("lost", "loser", "contributor"):
            continue
        prev = t.stage
        contributed = (
            winner.broker_id in (t.coop_with or [])
            or t.broker_id in (winner.coop_with or [])
        )
        t.closed = True
        t.stage = "lost"
        if contributed:
            t.role_outcome = "contributor"
            text = f"{t.broker_label()} 协作收官 · 线索 {group} 由 {win_label} 先签"
            reason = (
                f"同线索 {group} 已被 {win_label} 先签约；"
                f"本经纪曾与其协作（转介/协助/交接），记为协作贡献、非主签。"
            )
        else:
            t.role_outcome = "loser"
            text = f"{t.broker_label()} 落败 · 线索 {group} 已被 {win_label} 先签"
            reason = f"同线索 {group} 竞争中，{win_label} 先完成签约，本线程关闭落败。"
        t.last_reason = reason
        closed_events.append((t, text, reason, prev))
    return closed_events


def summarize_threads(threads: List[DealThread]) -> Dict[str, Any]:
    for t in threads:
        t.normalize_stage()
    signed = [t for t in threads if t.stage == "signed" or t.role_outcome == "winner"]
    lost = [t for t in threads if t.role_outcome in ("lost", "loser") or (t.stage == "lost" and t.role_outcome != "contributor")]
    contributors = [t for t in threads if t.role_outcome == "contributor"]
    active = [t for t in threads if not t.closed]
    direct_signed = [t for t in signed if t.path == "direct"]
    nego_signed = [t for t in signed if t.path == "negotiate"]
    money_threads = [
        t for t in threads if t.contract_money and t.role_outcome == "winner"
    ] or [t for t in threads if t.contract_money and t.stage == "signed"]

    deals = []
    by_broker: Dict[str, Dict[str, Any]] = {}
    for w in signed:
        if w.role_outcome and w.role_outcome != "winner":
            continue
        group = w.deal_group_id or w.clue_id
        coop = [
            {
                "broker_id": t.broker_id,
                "broker_name": t.broker_name,
            }
            for t in threads
            if (t.deal_group_id or t.clue_id) == group and t.role_outcome == "contributor"
        ]
        deals.append(
            {
                "clue_id": group,
                "deal_group_id": group,
                "winner_broker_id": w.broker_id,
                "winner_broker": w.broker_name,
                "coop_brokers": coop,
                "listing_id": w.listing_id,
                "listing_name": w.listing_name,
                "path": w.path,
                "contract_money": w.contract_money,
                "client_name": w.client_name,
            }
        )
        bid = w.broker_id
        by_broker.setdefault(bid, {"broker_id": bid, "broker_name": w.broker_name, "n_win": 0, "n_coop": 0})
        by_broker[bid]["n_win"] = int(by_broker[bid]["n_win"]) + 1
    for t in contributors:
        bid = t.broker_id
        by_broker.setdefault(bid, {"broker_id": bid, "broker_name": t.broker_name, "n_win": 0, "n_coop": 0})
        by_broker[bid]["n_coop"] = int(by_broker[bid]["n_coop"]) + 1

    return {
        "n_threads": len(threads),
        "n_signed": len([d for d in deals]),
        "n_clue_deals": len(deals),
        "n_lost": len(lost),
        "n_contributor": len(contributors),
        "n_active": len(active),
        "n_solidify": sum(1 for t in threads if t.stage == "solidify" or t.follow_count > 0),
        "n_match": sum(1 for t in threads if t.stage in ("match", "show", "negotiate", "signed")),
        "n_show": sum(1 for t in threads if t.show_count > 0 or t.stage in ("show", "negotiate", "signed")),
        "n_negotiate": sum(1 for t in threads if t.negotiate_rounds > 0 or t.stage == "negotiate"),
        "n_direct_signed": len(direct_signed),
        "n_nego_signed": len(nego_signed),
        "expected_contract_money": float(sum(t.contract_money or 0 for t in money_threads)),
        "expected_commission": float(sum(t.commission or 0 for t in money_threads)),
        "by_stage": {s: sum(1 for t in threads if t.stage == s) for s in STAGES},
        "deals": deals,
        "by_broker": list(by_broker.values()),
        "funnel_end": "signed",
        "funnel": "idle→solidify→match→show→negotiate→signed",
        "race_mode": "clue_first_sign_wins",
    }
