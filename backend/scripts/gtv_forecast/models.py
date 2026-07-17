"""Train listing/broker/time models with baselines; produce backtest metrics and leaderboards."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import (
    average_precision_score,
    mean_absolute_error,
    roc_auc_score,
)
from sklearn.preprocessing import LabelEncoder

from .config import HORIZON_DAYS, MODEL_DIR, PARQUET_DIR, RANDOM_SEED, REPORT_DIR
from .feasibility import rolling_t0_candidates, run_feasibility_gate
from .features import build_all_samples, load_deals
from .labels import save_labels


LISTING_FEATURES = [
    "follow_num",
    "show_num",
    "heat",
    "log_heat",
    "days_since_create",
    "days_since_up",
    "area",
    "price",
    "has_rent",
    "city_hist_deal_rate",
    "mid_rent_score",
    "mid_sale_score",
    "mid_popularity",
    "need_match_cnt",
    "city_refund_rate",
    # 质量画像（与 Agent quality_score 同公式；与 heat 轻度共线可接受）
    "log_area",
    "has_elevator",
    "has_crown_block",
    "quality_score",
    "info_completeness",
]
BROKER_FEATURES = ["hist_deals", "n_listings", "port_heat", "port_show", "hist_rate"]
MODEL_BUNDLE = "gtv_bundle.joblib"


def _encode_city(train: pd.DataFrame, test: pd.DataFrame, col: str = "city_name") -> tuple[np.ndarray, np.ndarray]:
    le = LabelEncoder()
    all_vals = pd.concat([train[col].fillna("UNK"), test[col].fillna("UNK")]).astype(str)
    le.fit(all_vals)
    return le.transform(train[col].fillna("UNK").astype(str)), le.transform(test[col].fillna("UNK").astype(str))


def _listing_matrix(df: pd.DataFrame, city_code: np.ndarray) -> np.ndarray:
    X = df.reindex(columns=LISTING_FEATURES).apply(pd.to_numeric, errors="coerce")
    X = X.replace([np.inf, -np.inf], np.nan)
    arr = X.to_numpy(dtype=float)
    return np.column_stack([arr, city_code.astype(float)])


def _broker_matrix(df: pd.DataFrame) -> np.ndarray:
    X = df.reindex(columns=BROKER_FEATURES).apply(pd.to_numeric, errors="coerce").fillna(0)
    return X.to_numpy(dtype=float)


def _topk_hit(y_true: np.ndarray, scores: np.ndarray, k: int = 50) -> float:
    if len(y_true) == 0:
        return float("nan")
    k = min(k, len(scores))
    idx = np.argsort(-scores)[:k]
    return float(y_true[idx].sum() / max(y_true.sum(), 1))


def _safe_auc(y, s):
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, s))


def _safe_ap(y, s):
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(average_precision_score(y, s))


def run_backtest() -> dict:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not (PARQUET_DIR / "labels_deals.parquet").exists():
        save_labels()
    gate = run_feasibility_gate()
    deals = load_deals()
    folds = [f for f in rolling_t0_candidates(deals) if f["n_eval_deals"] >= 10]
    if not folds:
        folds = rolling_t0_candidates(deals)
    t0_list = [f["t0"] for f in folds]
    listing_df, broker_df = build_all_samples(t0_list)

    listing_metrics = []
    broker_metrics = []
    time_metrics = []
    leaderboards = {"listings": [], "brokers": []}

    # Walk-forward: train on folds before test fold
    for i, fold in enumerate(folds):
        t0 = fold["t0"]
        l_train = listing_df[listing_df["t0"] < pd.Timestamp(t0)]
        l_test = listing_df[listing_df["t0"] == pd.Timestamp(t0)]
        b_train = broker_df[broker_df["t0"] < pd.Timestamp(t0)]
        b_test = broker_df[broker_df["t0"] == pd.Timestamp(t0)]
        if len(l_train) < 50 or l_test["label"].sum() < 5:
            # cold start: use all earlier raw deals via same-fold leave? use previous calendar months in sample
            if i == 0:
                # train on synthetic: use samples from other t0s if any; else skip model use baseline only
                pass

        # Listing model
        train_mode = "walk_forward"
        if (len(l_train) < 30 or l_train["label"].sum() < 5) and len(l_test) >= 40 and l_test["label"].sum() >= 5:
            # short history: holdout within fold
            rng = np.random.RandomState(RANDOM_SEED)
            mask = rng.rand(len(l_test)) < 0.7
            # ensure both classes in train
            if l_test.loc[mask, "label"].sum() >= 3 and l_test.loc[~mask, "label"].sum() >= 3:
                l_train = l_test.loc[mask]
                l_test = l_test.loc[~mask]
                train_mode = "within_fold_holdout"

        if len(l_train) >= 30 and l_train["label"].sum() >= 5 and len(l_test):
            tr_city, te_city = _encode_city(l_train, l_test)
            Xtr = _listing_matrix(l_train, tr_city)
            Xte = _listing_matrix(l_test, te_city)
            ytr = l_train["label"].to_numpy()
            yte = l_test["label"].to_numpy()
            clf = HistGradientBoostingClassifier(max_depth=6, learning_rate=0.08, max_iter=120, random_state=RANDOM_SEED)
            clf.fit(Xtr, ytr)
            prob = clf.predict_proba(Xte)[:, 1]
            base = l_test["heat"].fillna(0).to_numpy(dtype=float)
            hist_base = l_test["city_hist_deal_rate"].fillna(0).to_numpy(dtype=float)
            listing_metrics.append(
                {
                    "t0": t0,
                    "train_mode": train_mode,
                    "n_test": int(len(yte)),
                    "n_pos": int(yte.sum()),
                    "model_auc": _safe_auc(yte, prob),
                    "model_ap": _safe_ap(yte, prob),
                    "model_top50": _topk_hit(yte, prob, 50),
                    "heat_auc": _safe_auc(yte, base),
                    "heat_ap": _safe_ap(yte, base),
                    "heat_top50": _topk_hit(yte, base, 50),
                    "cityrate_auc": _safe_auc(yte, hist_base),
                    "cityrate_top50": _topk_hit(yte, hist_base, 50),
                }
            )
            # leaderboard from last fold / all folds accumulate last
            top = l_test.assign(score=prob).sort_values("score", ascending=False).head(30)
            leaderboards["listings"] = top[
                ["listing_id", "listing_type", "city_name", "score", "label", "heat", "days_to_sign"]
            ].to_dict(orient="records")

            # time model on positives in train
            tr_pos = l_train[l_train["label"] == 1].dropna(subset=["days_to_sign"])
            te_pos = l_test[l_test["label"] == 1].dropna(subset=["days_to_sign"])
            if len(tr_pos) >= 20 and len(te_pos) >= 5:
                tr_c2, te_c2 = _encode_city(tr_pos, te_pos)
                Xtr_t = _listing_matrix(tr_pos, tr_c2)
                Xte_t = _listing_matrix(te_pos, te_c2)
                reg = HistGradientBoostingRegressor(max_depth=5, learning_rate=0.08, max_iter=100, random_state=RANDOM_SEED)
                ytr_t = tr_pos["days_to_sign"].clip(lower=1, upper=HORIZON_DAYS).to_numpy()
                yte_t = te_pos["days_to_sign"].clip(lower=1, upper=HORIZON_DAYS).to_numpy()
                reg.fit(Xtr_t, ytr_t)
                pred = reg.predict(Xte_t)
                med_base = np.full_like(yte_t, np.median(ytr_t), dtype=float)
                time_metrics.append(
                    {
                        "t0": t0,
                        "n": int(len(yte_t)),
                        "model_mae": float(mean_absolute_error(yte_t, pred)),
                        "median_baseline_mae": float(mean_absolute_error(yte_t, med_base)),
                        "pred_p50_mean": float(np.mean(pred)),
                    }
                )
                # attach p50 to listing board
                te_pos = te_pos.assign(pred_days=pred)
                pmap = te_pos.set_index("listing_id")["pred_days"]
                for row in leaderboards["listings"]:
                    row["pred_days_p50"] = float(pmap[row["listing_id"]]) if row["listing_id"] in pmap.index else None

        # Broker model
        b_train_mode = "walk_forward"
        if (len(b_train) < 30 or b_train["label"].sum() < 5) and len(b_test) >= 40 and b_test["label"].sum() >= 5:
            rng = np.random.RandomState(RANDOM_SEED)
            mask = rng.rand(len(b_test)) < 0.7
            if b_test.loc[mask, "label"].sum() >= 3 and b_test.loc[~mask, "label"].sum() >= 3:
                b_train = b_test.loc[mask]
                b_test = b_test.loc[~mask]
                b_train_mode = "within_fold_holdout"

        if len(b_train) >= 30 and b_train["label"].sum() >= 5 and len(b_test):
            Xtr = _broker_matrix(b_train)
            Xte = _broker_matrix(b_test)
            ytr = b_train["label"].to_numpy()
            yte = b_test["label"].to_numpy()
            clf = HistGradientBoostingClassifier(max_depth=5, learning_rate=0.08, max_iter=100, random_state=RANDOM_SEED)
            clf.fit(Xtr, ytr)
            prob = clf.predict_proba(Xte)[:, 1]
            hist_base = b_test["hist_rate"].fillna(0).to_numpy(dtype=float)
            broker_metrics.append(
                {
                    "t0": t0,
                    "train_mode": b_train_mode,
                    "n_test": int(len(yte)),
                    "n_pos": int(yte.sum()),
                    "model_auc": _safe_auc(yte, prob),
                    "model_top20": _topk_hit(yte, prob, 20),
                    "hist_auc": _safe_auc(yte, hist_base),
                    "hist_top20": _topk_hit(yte, hist_base, 20),
                }
            )
            topb = b_test.assign(score=prob).sort_values("score", ascending=False).head(30).copy()
            nick = topb["nick_name"] if "nick_name" in topb.columns else None
            uname = topb["user_name"] if "user_name" in topb.columns else None
            if nick is not None and uname is not None:
                topb["display_name"] = nick.fillna(uname)
            elif uname is not None:
                topb["display_name"] = uname
            elif nick is not None:
                topb["display_name"] = nick
            else:
                topb["display_name"] = None
            topb["nick_name"] = topb["display_name"]
            cols = [c for c in ["user_id", "nick_name", "score", "label", "label_deals", "hist_deals", "n_listings"] if c in topb.columns]
            leaderboards["brokers"] = topb[cols].to_dict(orient="records")

    def _mean_key(rows, key):
        vals = [r[key] for r in rows if r.get(key) == r.get(key)]
        return float(np.nanmean(vals)) if vals else float("nan")

    summary = {
        "horizon_days": HORIZON_DAYS,
        "folds_used": [f["t0"] for f in folds],
        "listing_metrics": listing_metrics,
        "broker_metrics": broker_metrics,
        "time_metrics": time_metrics,
        "listing_avg": {
            "model_auc": _mean_key(listing_metrics, "model_auc"),
            "heat_auc": _mean_key(listing_metrics, "heat_auc"),
            "model_top50": _mean_key(listing_metrics, "model_top50"),
            "heat_top50": _mean_key(listing_metrics, "heat_top50"),
            "beats_heat_auc": _mean_key(listing_metrics, "model_auc") > _mean_key(listing_metrics, "heat_auc"),
        },
        "broker_avg": {
            "model_auc": _mean_key(broker_metrics, "model_auc"),
            "hist_auc": _mean_key(broker_metrics, "hist_auc"),
            "beats_hist_auc": _mean_key(broker_metrics, "model_auc") > _mean_key(broker_metrics, "hist_auc"),
        },
        "time_avg": {
            "model_mae": _mean_key(time_metrics, "model_mae"),
            "median_baseline_mae": _mean_key(time_metrics, "median_baseline_mae"),
            "beats_median": _mean_key(time_metrics, "model_mae") < _mean_key(time_metrics, "median_baseline_mae"),
        },
        "gate_pass": gate.get("pass_gate"),
        "leaderboards": leaderboards,
    }

    # Accept if at least one main task beats baseline
    summary["accept"] = bool(
        summary["listing_avg"].get("beats_heat_auc")
        or summary["broker_avg"].get("beats_hist_auc")
        or summary["time_avg"].get("beats_median")
    )

    (REPORT_DIR / "backtest_metrics.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "leaderboards"}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (REPORT_DIR / "leaderboards.json").write_text(json.dumps(leaderboards, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def _fit_city_encoder(df: pd.DataFrame, col: str = "city_name") -> LabelEncoder:
    le = LabelEncoder()
    le.fit(df[col].fillna("UNK").astype(str))
    return le


def train_final() -> dict:
    """用全量历史样本训练房源/经纪人/时间三模型并落盘。"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not (PARQUET_DIR / "labels_deals.parquet").exists():
        save_labels()
    deals = load_deals()
    folds = rolling_t0_candidates(deals)
    t0_list = [f["t0"] for f in folds] or [str(deals["event_time"].max())]
    listing_df, broker_df = build_all_samples(t0_list)

    # 合并所有折样本做最终训练
    l_train = listing_df.copy()
    b_train = broker_df.copy()
    if len(l_train) < 30 or l_train["label"].sum() < 5:
        raise RuntimeError(f"训练样本不足: listing n={len(l_train)} pos={l_train['label'].sum()}")

    city_enc = _fit_city_encoder(l_train)
    city_code = city_enc.transform(l_train["city_name"].fillna("UNK").astype(str))
    X_l = _listing_matrix(l_train, city_code)
    y_l = l_train["label"].to_numpy()
    listing_clf = HistGradientBoostingClassifier(
        max_depth=6, learning_rate=0.08, max_iter=140, random_state=RANDOM_SEED
    )
    listing_clf.fit(X_l, y_l)

    time_reg = None
    tr_pos = l_train[l_train["label"] == 1].dropna(subset=["days_to_sign"])
    if len(tr_pos) >= 20:
        c2 = city_enc.transform(tr_pos["city_name"].fillna("UNK").astype(str))
        X_t = _listing_matrix(tr_pos, c2)
        y_t = tr_pos["days_to_sign"].clip(lower=1, upper=HORIZON_DAYS).to_numpy()
        time_reg = HistGradientBoostingRegressor(
            max_depth=5, learning_rate=0.08, max_iter=120, random_state=RANDOM_SEED
        )
        time_reg.fit(X_t, y_t)

    broker_clf = None
    if len(b_train) >= 30 and b_train["label"].sum() >= 5:
        X_b = _broker_matrix(b_train)
        y_b = b_train["label"].to_numpy()
        broker_clf = HistGradientBoostingClassifier(
            max_depth=5, learning_rate=0.08, max_iter=120, random_state=RANDOM_SEED
        )
        broker_clf.fit(X_b, y_b)

    bundle = {
        "listing_clf": listing_clf,
        "broker_clf": broker_clf,
        "time_reg": time_reg,
        "city_encoder": city_enc,
        "listing_features": LISTING_FEATURES,
        "broker_features": BROKER_FEATURES,
        "horizon_days": HORIZON_DAYS,
        "trained_at": pd.Timestamp.utcnow().isoformat(),
        "n_listing_samples": int(len(l_train)),
        "n_listing_pos": int(y_l.sum()),
        "n_broker_samples": int(len(b_train)),
        "n_broker_pos": int(b_train["label"].sum()) if len(b_train) else 0,
        "t0_list": t0_list,
    }
    out_path = MODEL_DIR / MODEL_BUNDLE
    joblib.dump(bundle, out_path)
    meta = {k: v for k, v in bundle.items() if k not in ("listing_clf", "broker_clf", "time_reg", "city_encoder")}
    meta["path"] = str(out_path)
    (MODEL_DIR / "train_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return meta


def load_model_bundle(path: Path | None = None) -> dict | None:
    path = path or (MODEL_DIR / MODEL_BUNDLE)
    if not path.exists():
        return None
    return joblib.load(path)
