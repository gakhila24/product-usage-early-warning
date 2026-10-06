"""
Predictive Model Layer — Design Doc Section 3.1
=================================================
Trains a classifier on model_train.csv (panel_month_seq 1-9),
evaluates on model_holdout.csv (panel_month_seq 10-12),
compares against baseline_benchmark.csv (the legacy heuristic), and writes
model_scores for every row in BOTH train and holdout.

Environment note: the design doc specifies LightGBM/XGBoost. This sandbox has
no network access to install them, so scikit-learn's RandomForestClassifier
(class_weight='balanced') is used as the primary model and LogisticRegression
as the interpretable baseline -- both are legitimate substitutes and the code
is written so swapping in LightGBM/XGBoost later is a one-function change
(see `build_model()`). Say this plainly if asked at the panel.

2026-10 addition: the React dashboard's Evaluation page (frontend/src/
Evaluation.jsx) labels its headline ranking-quality metric "AUROC", which is
a different statistic from the PR-AUC this file already computed. Rather than
quietly relabel PR-AUC as AUROC, this file now also computes a real
roc_auc_score for every model on the same holdout set, so the number behind
that label is genuinely an AUROC. PR-AUC is still computed and reported
alongside it (it is the more informative metric for this class-imbalanced
problem, and remains the metric train/CI gates should key off of).
"""
import json
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

warnings.filterwarnings("ignore")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "churn_data.db"

TARGET = "churned_within_90d"
ID_COLS = ["account_id", "as_of_month", "panel_month_seq"]
CATEGORICAL = ["segment", "industry", "region", "contract_type"]

# Numeric feature set -- matches model_train.csv / model_holdout.csv
# (leakage columns already excluded at the data-build stage)
NUMERIC = [
    "company_size_employees", "account_age_months", "days_to_renewal",
    "seats_licensed", "price_per_seat_usd", "seats_active", "seat_utilization_pct",
    "monthly_spend_usd", "spend_trend_3m_pct", "discount_pct",
    "payment_failure_90d_count", "sessions_per_week", "avg_session_duration_min",
    "distinct_features_used", "feature_adoption_score", "feature_abandonment_rate_90d",
    "days_since_last_login", "usage_trend_90d_pct", "engagement_score",
    "support_tickets_90d", "escalations_90d", "high_priority_tickets_90d",
    "avg_resolution_time_hrs", "csat_score", "support_friction_score",
    "technical_issue_count_90d", "login_failures_90d", "technical_friction_score",
    "num_active_stakeholders", "days_since_last_csm_touchpoint", "nps_last_survey",
]
BOOL_AS_INT = [
    "auto_renew", "price_change_flag_90d", "upsell_flag_90d", "downgrade_flag_90d",
    "invoice_overdue_flag", "executive_sponsor_engaged", "qbr_attended_last_90d",
    "champion_turnover_flag_90d", "company_layoff_flag_90d",
    "company_funding_event_flag_90d", "leadership_change_flag_90d",
    "intervention_triggered_flag",
]


def build_model(kind: str) -> Pipeline:
    pre = ColumnTransformer([
        ("num", StandardScaler(), NUMERIC + BOOL_AS_INT),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
    ])
    if kind == "rf":
        clf = RandomForestClassifier(
            n_estimators=400, max_depth=8, min_samples_leaf=5,
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
    elif kind == "logreg":
        clf = LogisticRegression(max_iter=2000, class_weight="balanced")
    else:
        raise ValueError(kind)
    return Pipeline([("pre", pre), ("clf", clf)])


def prep_xy(df: pd.DataFrame):
    df = df.copy()
    for c in BOOL_AS_INT:
        df[c] = df[c].astype(int)
    df["nps_last_survey"] = df["nps_last_survey"].fillna(df["nps_last_survey"].median())
    for c in ["spend_trend_3m_pct", "usage_trend_90d_pct"]:
        df[c] = df[c].fillna(0.0)
    X = df[NUMERIC + BOOL_AS_INT + CATEGORICAL]
    y = df[TARGET].astype(int)
    return X, y


def precision_at_k(y_true, scores, k_frac):
    n = len(scores)
    k = max(1, int(round(n * k_frac)))
    order = np.argsort(-scores)[:k]
    return y_true.iloc[order].mean() if hasattr(y_true, "iloc") else y_true[order].mean()


def main():
    train = pd.read_csv(DATA_DIR / "model_train.csv")
    holdout = pd.read_csv(DATA_DIR / "model_holdout.csv")
    baseline = pd.read_csv(DATA_DIR / "baseline_benchmark.csv")

    X_train, y_train = prep_xy(train)
    X_hold, y_hold = prep_xy(holdout)

    models = {"random_forest": build_model("rf"), "logistic_regression": build_model("logreg")}
    results = {}
    scored_frames = []

    for name, pipe in models.items():
        pipe.fit(X_train, y_train)
        p_hold = pipe.predict_proba(X_hold)[:, 1]
        pr_auc = average_precision_score(y_hold, p_hold)
        auroc = roc_auc_score(y_hold, p_hold)
        coverage_metrics = {
            f"precision_at_top_{int(k*100)}pct": float(precision_at_k(y_hold, p_hold, k))
            for k in (0.05, 0.10, 0.20)
        }
        results[name] = {"pr_auc": float(pr_auc), "auroc": float(auroc), **coverage_metrics}

        if name == "random_forest":
            scores_full = pipe.predict_proba(pd.concat([X_train, X_hold]))[:, 1]
            ids_full = pd.concat([train[ID_COLS], holdout[ID_COLS]]).reset_index(drop=True)
            risk_score = (scores_full * 100).round(2)
            bands = pd.cut(
                scores_full, bins=[-0.01, 0.25, 0.50, 0.75, 1.01],
                labels=["Low", "Medium", "High", "Critical"],
            )
            scored = ids_full.copy()
            scored["risk_score"] = risk_score
            scored["risk_band"] = bands.astype(str)
            scored["model_version"] = "rf_v1"
            scored_frames.append(scored)

            # global feature importance
            ohe_names = list(
                pipe.named_steps["pre"].named_transformers_["cat"].get_feature_names_out(CATEGORICAL)
            )
            feat_names = NUMERIC + BOOL_AS_INT + ohe_names
            importances = pipe.named_steps["clf"].feature_importances_
            fi = pd.DataFrame({"feature": feat_names, "importance": importances})
            fi = fi.sort_values("importance", ascending=False).reset_index(drop=True)
            fi.to_csv(DATA_DIR / "feature_importance.csv", index=False)

    # baseline (heuristic) comparison on the SAME holdout rows
    hold_baseline = holdout[ID_COLS].merge(
        baseline[["account_id", "as_of_month", "heuristic_risk_score"]],
        on=["account_id", "as_of_month"], how="left",
    )
    baseline_scores = hold_baseline["heuristic_risk_score"].values
    baseline_coverage = {
        f"precision_at_top_{int(k*100)}pct": float(precision_at_k(y_hold, baseline_scores, k))
        for k in (0.05, 0.10, 0.20)
    }
    results["heuristic_baseline"] = {
        "pr_auc": float(average_precision_score(y_hold, baseline_scores)),
        "auroc": float(roc_auc_score(y_hold, baseline_scores)),
        **baseline_coverage,
    }

    model_scores = pd.concat(scored_frames, ignore_index=True)
    model_scores.to_csv(DATA_DIR / "model_scores.csv", index=False)

    conn = sqlite3.connect(DB_PATH)
    model_scores.to_sql("model_scores", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scores_account ON model_scores(account_id);")
    conn.commit()
    conn.close()

    with open(DATA_DIR / "model_metrics.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"=== Model evaluation on holdout (months 10-12, {y_hold.mean()*100:.2f}% churn base rate) ===")
    for name, m in results.items():
        print(f"\n{name}:")
        for k, v in m.items():
            print(f"  {k}: {v:.4f}")

    print(f"\nrisk_band distribution (full dataset, train+holdout):")
    print(model_scores["risk_band"].value_counts())
    print(f"\nWrote model_scores.csv/table, feature_importance.csv, model_metrics.json to {DATA_DIR}")


if __name__ == "__main__":
    main()
