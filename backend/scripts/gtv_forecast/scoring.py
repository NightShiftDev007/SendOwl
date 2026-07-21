"""在线打分：三榜 + 期望合同额/佣金；支持干预 what-if；无模型回退缓存。"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import (
    DEFAULT_NEGO_SUCCESS_RATE,
    HORIZON_DAYS,
    REPORT_DIR,
)
from .features import build_scoring_universe
from .interventions import (
    apply_direct_levers,
    apply_negotiate_branch,
    blend_branch_results,
    extract_gtv_levers,
)
from .models import (
    BROKER_FEATURES,
    LISTING_FEATURES,
    _broker_matrix,
    _listing_matrix,
    load_model_bundle,
)

# 懒加载单例：多方案打分复用同一 bundle
_BUNDLE_CACHE: dict[str, Any] | None = None


def get_model_bundle(*, force_reload: bool = False) -> dict[str, Any] | None:
    global _BUNDLE_CACHE
    if force_reload:
        _BUNDLE_CACHE = None
    if _BUNDLE_CACHE is not None:
        return _BUNDLE_CACHE
    loaded = load_model_bundle()
    if loaded is not None:
        _BUNDLE_CACHE = loaded
    return loaded


def json_safe(obj: Any) -> Any:
    """把 NaN/Inf/pandas NA 转成 null，避免浏览器 JSON.parse 失败。"""
    if obj is None:
        return None
    if isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(obj, (np.ndarray,)):
        return json_safe(obj.tolist())
    return obj


def _records(df: pd.DataFrame, cols: list[str]) -> list[dict[str, Any]]:
    keep = [c for c in cols if c in df.columns]
    if df is None or len(df) == 0 or not keep:
        return []
    return json_safe(df[keep].replace({np.nan: None}).to_dict(orient="records"))


def _safe_city_codes(encoder, series: pd.Series) -> np.ndarray:
    vals = series.fillna("UNK").astype(str)
    known = set(encoder.classes_)
    mapped = vals.where(vals.isin(known), other="UNK")
    if "UNK" not in known:
        # encoder 无 UNK：映射到第一个类
        fallback = encoder.classes_[0]
        mapped = vals.where(vals.isin(known), other=fallback)
    return encoder.transform(mapped)


def _econ_summary(listing_scored: pd.DataFrame, top_n: int = 50) -> dict[str, Any]:
    df = listing_scored.sort_values("score", ascending=False).head(top_n).copy()
    p = pd.to_numeric(df["score"], errors="coerce").fillna(0).clip(0, 1)
    contract = pd.to_numeric(df.get("prior_contract_money"), errors="coerce").fillna(0)
    commission = pd.to_numeric(df.get("prior_commission"), errors="coerce").fillna(0)
    refund = pd.to_numeric(df.get("city_refund_rate"), errors="coerce").fillna(0.5)
    expected_deals = float(p.sum())
    expected_contract = float((p * contract).sum())
    expected_commission = float((p * commission).sum())
    # 个人佣金粗估：总额 × 城市回款兑现代理 × 典型分成 10%
    expected_personal = float((p * commission * refund * 0.10).sum())
    rent_days = pd.to_numeric(df.get("prior_days_to_rent"), errors="coerce")
    pred_days = pd.to_numeric(df.get("pred_days_p50"), errors="coerce")
    return {
        "expected_deals": expected_deals,
        "expected_contract_money": expected_contract,
        "expected_commission": expected_commission,
        "expected_personal_commission": expected_personal,
        "median_pred_days_p50": float(pred_days.median()) if pred_days.notna().any() else None,
        "median_days_sign_to_rent": float(rent_days.median()) if rent_days.notna().any() else None,
        "top_n": int(len(df)),
    }


def _score_frames(
    listing_df: pd.DataFrame,
    broker_df: pd.DataFrame,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    import warnings

    listing_df = listing_df.copy()
    broker_df = broker_df.copy()
    # 旧 bundle 用其训练时的特征列；缺列填 0，多出的新列忽略（不 500）
    feat_cols = list(bundle.get("listing_features") or LISTING_FEATURES)
    if feat_cols != LISTING_FEATURES:
        warnings.warn(
            f"bundle listing_features ({len(feat_cols)}) ≠ 当前 LISTING_FEATURES "
            f"({len(LISTING_FEATURES)})，按 bundle 列 reindex(fill_value=0) 兼容打分",
            UserWarning,
            stacklevel=2,
        )
    for c in feat_cols:
        if c not in listing_df.columns:
            listing_df[c] = 0.0 if c != "city_refund_rate" else 0.5
    listing_df = listing_df.copy()
    for c in BROKER_FEATURES:
        if c not in broker_df.columns:
            broker_df[c] = 0.0

    city_enc = bundle["city_encoder"]
    city_code = _safe_city_codes(city_enc, listing_df["city_name"])
    X_feat = listing_df.reindex(columns=feat_cols).apply(pd.to_numeric, errors="coerce")
    X_feat = X_feat.replace([np.inf, -np.inf], np.nan).fillna(0)
    X_l = np.column_stack([X_feat.to_numpy(dtype=float), city_code.astype(float)])
    clf = bundle["listing_clf"]
    prob = clf.predict_proba(X_l)[:, 1]
    listing_df["score"] = prob

    time_reg = bundle.get("time_reg")
    if time_reg is not None:
        try:
            listing_df["pred_days_p50"] = time_reg.predict(X_l)
        except Exception:
            listing_df["pred_days_p50"] = np.nan
    else:
        listing_df["pred_days_p50"] = np.nan

    broker_clf = bundle.get("broker_clf")
    if broker_clf is not None and len(broker_df):
        X_b = _broker_matrix(broker_df)
        broker_df["score"] = broker_clf.predict_proba(X_b)[:, 1]
    else:
        broker_df["score"] = pd.to_numeric(broker_df.get("hist_rate"), errors="coerce").fillna(0)

    top_l = listing_df.sort_values("score", ascending=False).head(30)
    listing_rows = _records(
        top_l,
        [
            "listing_id",
            "listing_type",
            "listing_name",
            "city_name",
            "address",
            "longitude",
            "latitude",
            "quality_score",
            "score",
            "label",
            "heat",
            "days_to_sign",
            "pred_days_p50",
            "prior_contract_money",
            "prior_commission",
            "prior_days_to_rent",
            "maintain_person_id",
        ],
    )

    top_b = broker_df.sort_values("score", ascending=False).head(30).copy()
    if "nick_name" in top_b.columns:
        top_b["nick_name"] = top_b["nick_name"].fillna(top_b.get("user_name"))
    broker_rows = _records(
        top_b,
        [
            "user_id",
            "nick_name",
            "score",
            "label",
            "label_deals",
            "hist_deals",
            "n_listings",
            "hist_rate",
            "port_heat",
            "port_show",
        ],
    )
    for br in broker_rows:
        if br.get("hist_rate") is None:
            try:
                hd = float(br.get("hist_deals") or 0)
                nl = float(br.get("n_listings") or 0)
                br["hist_rate"] = hd / (nl + 1.0)
            except Exception:
                br["hist_rate"] = 0.0

    # 时间榜：按预测成交天数升序（越快越前）
    timing = (
        listing_df.dropna(subset=["pred_days_p50"])
        .sort_values("pred_days_p50", ascending=True)
        .head(30)
    )
    timing_rows = _records(
        timing,
        [
            "listing_id",
            "listing_type",
            "listing_name",
            "city_name",
            "address",
            "quality_score",
            "pred_days_p50",
            "score",
            "prior_days_to_rent",
        ],
    )

    summary = _econ_summary(listing_df)
    summary["horizon_days"] = bundle.get("horizon_days") or HORIZON_DAYS
    return {
        "mode": "model",
        "listings": listing_rows,
        "brokers": broker_rows,
        "timing": timing_rows,
        "summary": summary,
        "listing_scored": listing_df,
        "broker_scored": broker_df,
    }


def _cache_fallback(notes: list[str] | None = None) -> dict[str, Any]:
    path = REPORT_DIR / "leaderboards.json"
    notes = list(notes or [])
    notes.append("缓存模式：未找到训练产物，回退 leaderboards.json")
    if not path.exists():
        return {
            "mode": "cache",
            "listings": [],
            "brokers": [],
            "timing": [],
            "summary": {
                "expected_deals": 0,
                "expected_contract_money": 0,
                "expected_commission": 0,
                "expected_personal_commission": 0,
            },
            "notes": notes,
            "cache_path": str(path),
        }
    raw = json.loads(path.read_text(encoding="utf-8"))
    listings = list(raw.get("listings") or [])
    brokers = list(raw.get("brokers") or [])
    # 粗估经济量
    scores = [float(x.get("score") or 0) for x in listings]
    summary = {
        "expected_deals": float(sum(scores)),
        "expected_contract_money": None,
        "expected_commission": None,
        "expected_personal_commission": None,
        "median_pred_days_p50": None,
        "median_days_sign_to_rent": None,
        "top_n": len(listings),
        "cache": True,
    }
    return {
        "mode": "cache",
        "listings": listings,
        "brokers": brokers,
        "timing": [
            {
                "listing_id": x.get("listing_id"),
                "listing_type": x.get("listing_type"),
                "city_name": x.get("city_name"),
                "pred_days_p50": x.get("pred_days_p50"),
                "score": x.get("score"),
            }
            for x in listings
            if x.get("pred_days_p50") is not None
        ],
        "summary": summary,
        "notes": notes,
        "cache_path": str(path),
    }


def score_universe(
    listing_df: pd.DataFrame,
    broker_df: pd.DataFrame,
    *,
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = bundle if bundle is not None else get_model_bundle()
    if bundle is None:
        return _cache_fallback()
    return _score_frames(listing_df, broker_df, bundle)


def score_with_intervention(
    intervention: dict[str, Any] | None = None,
    *,
    t0: pd.Timestamp | None = None,
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对单一干预配置打分（含两段式谈价期望）。"""
    bundle = bundle if bundle is not None else get_model_bundle()
    notes: list[str] = []
    if bundle is None:
        return _cache_fallback(["无模型，干预未生效"])

    listing_df, broker_df, t0_used = build_scoring_universe(t0=t0)
    gtv = extract_gtv_levers(intervention)
    listing_df, broker_df, lever_notes = apply_direct_levers(listing_df, broker_df, gtv)
    notes.extend(lever_notes)

    nego = gtv.get("negotiate_deal") or {}
    if isinstance(nego, dict) and nego.get("enabled"):
        p = float(nego.get("success_rate") if nego.get("success_rate") is not None else DEFAULT_NEGO_SUCCESS_RATE)
        l_ok, meta_ok = apply_negotiate_branch(listing_df, gtv, success=True)
        l_fail, meta_fail = apply_negotiate_branch(listing_df, gtv, success=False)
        r_ok = _score_frames(l_ok, broker_df, bundle)
        r_fail = _score_frames(l_fail, broker_df, bundle)
        blended = blend_branch_results(r_ok, r_fail, p)
        # 榜单用期望分支加权后的成功侧展示，并附注
        blended["listings"] = r_ok["listings"]
        blended["brokers"] = r_ok["brokers"]
        blended["timing"] = r_ok["timing"]
        blended["notes"] = notes + [
            meta_ok.get("disclaimer") or "",
            f"谈价成功率 p={p:.0%}（人工假设）",
            f"谈成合同因子={meta_ok.get('contract_factor')}",
        ]
        blended["t0"] = str(t0_used)
        blended["gtv"] = gtv
        # 去掉巨大 DataFrame
        blended.pop("listing_scored", None)
        blended.pop("broker_scored", None)
        return blended

    result = _score_frames(listing_df, broker_df, bundle)
    result["notes"] = notes
    result["t0"] = str(t0_used)
    result["gtv"] = gtv
    result.pop("listing_scored", None)
    result.pop("broker_scored", None)
    return result


def _is_baseline(scenario: dict[str, Any]) -> bool:
    kind = str(scenario.get("kind") or "")
    name = str(scenario.get("name") or "")
    return "baseline" in kind.lower() or "baseline" in name.lower()


def _delta_vs_baseline(scenario_result: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    ss = scenario_result.get("summary") or {}
    bs = baseline.get("summary") or {}

    def d(key):
        try:
            a = float(ss.get(key) or 0)
            b = float(bs.get(key) or 0)
            return {"abs": a - b, "pct": ((a - b) / b) if b else None}
        except (TypeError, ValueError):
            return {"abs": None, "pct": None}

    # 榜单升降：以 listing_id 排名差
    base_rank = {
        str(r.get("listing_id")): i for i, r in enumerate(baseline.get("listings") or [])
    }
    rank_moves = []
    for i, r in enumerate(scenario_result.get("listings") or []):
        lid = str(r.get("listing_id"))
        if lid in base_rank:
            rank_moves.append(
                {
                    "listing_id": lid,
                    "listing_name": r.get("listing_name") or "",
                    "rank": i + 1,
                    "baseline_rank": base_rank[lid] + 1,
                    "delta_rank": base_rank[lid] - i,
                    "score": r.get("score"),
                }
            )
    rank_moves.sort(key=lambda x: -abs(x.get("delta_rank") or 0))
    return {
        "expected_deals": d("expected_deals"),
        "expected_contract_money": d("expected_contract_money"),
        "expected_commission": d("expected_commission"),
        "expected_personal_commission": d("expected_personal_commission"),
        "top_rank_moves": rank_moves[:10],
    }


def score_scenarios(scenarios: list[dict[str, Any]], *, t0: pd.Timestamp | None = None) -> dict[str, Any]:
    """多方案打分 + 相对 Baseline 差分。"""
    if not scenarios:
        scenarios = [{"name": "Baseline·不干预", "kind": "baseline", "intervention": {}}]

    bundle = get_model_bundle()
    results = []
    for i, sc in enumerate(scenarios):
        iv = sc.get("intervention") or {}
        scored = score_with_intervention(iv, t0=t0, bundle=bundle)
        results.append(
            {
                "scenario_id": sc.get("id") or sc.get("scenario_id") or f"sc_{i}",
                "name": sc.get("name") or f"方案{i + 1}",
                "kind": sc.get("kind") or "custom",
                "color": sc.get("color"),
                "mode": scored.get("mode"),
                "notes": scored.get("notes") or [],
                "summary": scored.get("summary") or {},
                "listings": scored.get("listings") or [],
                "brokers": scored.get("brokers") or [],
                "timing": scored.get("timing") or [],
                "t0": scored.get("t0"),
                "negotiate_blended": scored.get("negotiate_blended", False),
            }
        )

    baseline = next((r for r in results if _is_baseline(r)), results[0])
    for r in results:
        if r is baseline or r.get("scenario_id") == baseline.get("scenario_id"):
            r["delta_vs_baseline"] = None
            r["is_baseline"] = True
        else:
            r["delta_vs_baseline"] = _delta_vs_baseline(r, baseline)
            r["is_baseline"] = False

    return json_safe(
        {
            "engine": "gtv_forecast",
            "mode": results[0].get("mode") if results else "cache",
            "baseline_scenario_id": baseline.get("scenario_id"),
            "scenarios": results,
        }
    )


_TYPE_ZH = {
    "plant": "厂房",
    "warehouse": "仓库",
    "office": "办公",
    "厂房": "厂房",
    "仓库": "仓库",
    "办公": "办公",
}


def _listing_type_zh(raw: Any) -> str:
    """内部码 plant/warehouse/office → 厂房/仓库/办公。"""
    key = str(raw or "").strip().lower()
    if not key:
        return "—"
    return _TYPE_ZH.get(key) or _TYPE_ZH.get(str(raw).strip()) or "—"


def _md_cell(s: Any, *, max_len: int = 48) -> str:
    """Markdown 表格单元格：去管道符、适当截断。"""
    t = str(s or "").replace("|", "｜").replace("\n", " ").strip()
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t or "—"


def _listing_label(row: dict[str, Any]) -> str:
    """房源展示：名称 + 完整 ID（禁止截成后 8 位）。"""
    lid = str(row.get("listing_id") or "").strip()
    name = str(row.get("listing_name") or "").strip()
    if name and lid:
        return f"{_md_cell(name, max_len=36)}（ID:{lid}）"
    if name:
        return _md_cell(name, max_len=48)
    return lid or "—"


def render_compare_markdown(multi: dict[str, Any]) -> str:
    """由多方案打分结果生成 Step4 对比报告正文。"""
    lines = [
        "# 商业模板 · GTV 成交推演（在线打分 / what-if）",
        "",
        f"> 引擎模式：`{multi.get('mode')}` · 敏感性分析，非因果推断 · 谈价≠公司单方改挂牌价",
        "",
        "## 方案经济量对比",
        "",
        "| 方案 | 预期成交数 | 期望合同金额 | 期望预估佣金 | 较 Baseline 合同额 |",
        "|---|---:|---:|---:|---:|",
    ]
    for sc in multi.get("scenarios") or []:
        s = sc.get("summary") or {}
        d = (sc.get("delta_vs_baseline") or {}).get("expected_contract_money") or {}
        delta = d.get("abs")
        delta_s = "—" if sc.get("is_baseline") or delta is None else f"{delta:+,.0f}"
        lines.append(
            "| {name} | {deals:.2f} | {cm:,.0f} | {cc:,.0f} | {delta} |".format(
                name=sc.get("name") or "",
                deals=float(s.get("expected_deals") or 0),
                cm=float(s.get("expected_contract_money") or 0),
                cc=float(s.get("expected_commission") or 0),
                delta=delta_s,
            )
        )
    lines += ["", "## 各方案三榜摘要", ""]
    for sc in multi.get("scenarios") or []:
        lines.append(f"### {sc.get('name')}")
        if sc.get("notes"):
            for n in sc["notes"]:
                if n:
                    lines.append(f"- 注：{n}")
        nego = (sc.get("summary") or {}).get("negotiate")
        if nego:
            lines.append(
                f"- 谈价两分支：p={float(nego.get('success_rate') or 0):.0%} · "
                f"{nego.get('disclaimer')}"
            )
            sb = nego.get("success_branch") or {}
            fb = nego.get("fail_branch") or {}
            lines.append(
                f"  - 谈成：期望合同 {float(sb.get('expected_contract_money') or 0):,.0f} / "
                f"佣金 {float(sb.get('expected_commission') or 0):,.0f}"
            )
            lines.append(
                f"  - 谈不成：期望合同 {float(fb.get('expected_contract_money') or 0):,.0f} / "
                f"佣金 {float(fb.get('expected_commission') or 0):,.0f}"
            )
        lines.append("")
        lines.append("#### 房源榜（Top10）")
        lines.append("")
        lines.append("| 排名 | 房源 | 房源类型 | 城市 | 地址 | 质量分 | 成交分 | 期望合同先验 |")
        lines.append("|---:|---|---|---|---|---:|---:|---:|")
        for i, row in enumerate((sc.get("listings") or [])[:10]):
            q = row.get("quality_score")
            lines.append(
                "| {rank} | {label} | {lt} | {city} | {addr} | {q} | {score:.3f} | {cm} |".format(
                    rank=i + 1,
                    label=_listing_label(row),
                    lt=_listing_type_zh(row.get("listing_type")),
                    city=_md_cell(row.get("city_name"), max_len=16),
                    addr=_md_cell(row.get("address") or row.get("amap_address"), max_len=28),
                    q=f"{float(q):.2f}" if q is not None else "—",
                    score=float(row.get("score") or 0),
                    cm=(
                        f"{float(row['prior_contract_money']):,.0f}"
                        if row.get("prior_contract_money") is not None
                        else "—"
                    ),
                )
            )
        lines.append("")
        lines.append("#### 经纪人榜（Top10）")
        lines.append("")
        lines.append("| 排名 | 经纪人 | 用户ID | 成交分 | 历史开单 | 在管房源 |")
        lines.append("|---:|---|---|---:|---:|---:|")
        for i, row in enumerate((sc.get("brokers") or [])[:10]):
            nick = _md_cell(row.get("nick_name") or row.get("user_name") or "经纪人", max_len=24)
            uid = str(row.get("user_id") or "")
            lines.append(
                "| {rank} | {nick} | `{uid}` | {score:.3f} | {hd} | {nl} |".format(
                    rank=i + 1,
                    nick=nick,
                    uid=uid,
                    score=float(row.get("score") or 0),
                    hd=int(row.get("hist_deals") or 0),
                    nl=int(row.get("n_listings") or 0),
                )
            )
        lines.append("")
        dlt = sc.get("delta_vs_baseline")
        if dlt and dlt.get("top_rank_moves"):
            lines.append("相对 Baseline 榜单升降（节选）：")
            for m in dlt["top_rank_moves"][:5]:
                label = _listing_label(m) if m.get("listing_name") else str(m.get("listing_id") or "")
                lines.append(
                    f"- {label} "
                    f"#{m.get('baseline_rank')}→#{m.get('rank')} "
                    f"（Δrank={m.get('delta_rank'):+d}）"
                )
            lines.append("")
    lines += [
        "## 口径说明",
        "",
        "- **合同金额**：`e_project_sign.contract_money` 历史先验 × 成交概率",
        "- **预估佣金**：`contract_forecast_money` 历史先验 × 成交概率",
        "- **计租时间**：租赁场景附 `rent_start_time` 派生的签约→起租天数先验",
        "- **谈价干预**：发起与业主协商；期望 = p×谈成 + (1−p)×谈不成",
        "",
    ]
    return "\n".join(lines)


def write_score_artifacts(multi: dict[str, Any], out_dir: Path | None = None) -> dict[str, str]:
    out_dir = Path(out_dir or REPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 序列化时去掉不可 JSON 的内容
    payload = deepcopy(multi)
    for sc in payload.get("scenarios") or []:
        sc.pop("listing_scored", None)
        sc.pop("broker_scored", None)
    json_path = out_dir / "scenario_scores.json"
    md_path = out_dir / "compare_whatif.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md = render_compare_markdown(payload)
    md_path.write_text(md, encoding="utf-8")
    # 同步更新「默认」三榜为 baseline 或第一方案
    base = next((s for s in payload.get("scenarios") or [] if s.get("is_baseline")), None)
    if base is None and payload.get("scenarios"):
        base = payload["scenarios"][0]
    if base:
        (out_dir / "leaderboards.json").write_text(
            json.dumps(
                {
                    "listings": base.get("listings") or [],
                    "brokers": base.get("brokers") or [],
                    "timing": base.get("timing") or [],
                    "summary": base.get("summary") or {},
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    return {"json": str(json_path), "markdown": str(md_path)}
