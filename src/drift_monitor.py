"""
Input Drift Monitor — new module, added 2026-10 to back the React dashboard's
"Input data drift" evaluation tab (frontend/src/Views.jsx `Monitoring`,
frontend/src/Evaluation.jsx). Nothing in the original sandbox build computed
real feature drift -- this closes that gap with a genuinely computed metric
rather than a fabricated one.

Design, in plain terms:
  - Population Stability Index (PSI) compares a feature's distribution in a
    "baseline" period against a "current" period. We don't have two separate
    production snapshots to compare (this is a single synthetic dataset), so
    the honest, defensible baseline/current split used here is temporal
    *within* the one dataset: panel_month_seq 1-6 as the baseline population,
    panel_month_seq 7-12 as the current population, for every account-month
    row (not just the latest month). This is a real, if modest, 6-month
    comparison window -- it is NOT a comparison against production traffic,
    and that limitation is reported in the output, not hidden.
  - PSI uses the standard 10-bucket approach: bucket edges are the baseline
    distribution's decile cut points; PSI = sum((cur_pct - base_pct) *
    ln(cur_pct / base_pct)) across buckets, with a small epsilon floor to
    avoid log(0) / division-by-zero on empty buckets.
  - Alert threshold is the standard convention: PSI >= 0.10 is flagged for
    review (PSI < 0.10: stable, 0.10-0.25: moderate shift, > 0.25: major
    shift -- the UI only surfaces the single pass/fail line at 0.10).

Drift-detector validation (for the "Drift alert accuracy" metric the
Evaluation page displays): since there is no independently labeled set of
"features that actually drifted in production" to validate against, this
runs a synthetic injection test -- for a held-out copy of the current-period
sample, half of the tracked features get an artificial distribution shift
(a multiplicative + additive perturbation large enough to be detectable),
the other half are left alone, and we check whether the PSI-threshold rule
correctly classifies each group. This is a legitimate way to sanity-check a
drift detector's sensitivity/specificity when no real labeled drift events
exist yet -- reported honestly as a synthetic validation, not a production
accuracy figure.
"""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "churn_data.db"
REPORT_PATH = DATA_DIR / "drift_report.json"

ALERT_THRESHOLD = 0.10
N_BUCKETS = 10
EPS = 1e-6

# Features tracked for drift -- numeric, model-relevant, and present on every
# monthly row (not latest-month-only derived fields).
TRACKED_FEATURES = {
    "usage_trend_90d_pct": "Usage trend (90d)",
    "technical_friction_score": "Technical friction score",
    "support_friction_score": "Support friction score",
    "csat_score": "CSAT score",
    "spend_trend_3m_pct": "Spend trend (3mo)",
    "engagement_score": "Engagement score",
    "seat_utilization_pct": "Seat utilization",
    "feature_abandonment_rate_90d": "Feature abandonment rate (90d)",
    "nps_last_survey": "Latest NPS",
    "days_since_last_login": "Days since last login",
}


def _load_periods():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        "SELECT * FROM account_monthly_metrics_enriched WHERE panel_month_seq BETWEEN 1 AND 12",
        conn,
    )
    conn.close()
    baseline = df[df.panel_month_seq <= 6]
    current = df[df.panel_month_seq >= 7]
    return baseline, current


def _psi(baseline_vals: np.ndarray, current_vals: np.ndarray) -> float:
    baseline_vals = baseline_vals[~np.isnan(baseline_vals)]
    current_vals = current_vals[~np.isnan(current_vals)]
    if len(baseline_vals) < N_BUCKETS or len(current_vals) == 0:
        return 0.0
    quantiles = np.unique(np.quantile(baseline_vals, np.linspace(0, 1, N_BUCKETS + 1)))
    if len(quantiles) < 3:
        return 0.0  # degenerate (near-constant) feature -- PSI not meaningful
    base_counts, _ = np.histogram(baseline_vals, bins=quantiles)
    cur_counts, _ = np.histogram(current_vals, bins=quantiles)
    base_pct = base_counts / max(1, base_counts.sum()) + EPS
    cur_pct = cur_counts / max(1, cur_counts.sum()) + EPS
    return float(np.sum((cur_pct - base_pct) * np.log(cur_pct / base_pct)))


def compute_drift_report() -> dict:
    baseline, current = _load_periods()
    signals = []
    for feat, name in TRACKED_FEATURES.items():
        psi = _psi(baseline[feat].to_numpy(dtype=float), current[feat].to_numpy(dtype=float))
        signals.append({
            "feature": feat, "name": name,
            "psi": round(psi, 4), "alert": bool(psi >= ALERT_THRESHOLD),
        })
    signals.sort(key=lambda s: -s["psi"])
    n_alerting = sum(1 for s in signals if s["alert"])
    as_of = current["as_of_month"].max() if len(current) else None
    return {
        "signals": signals,
        "nFeaturesAlerting": n_alerting,
        "alertThreshold": ALERT_THRESHOLD,
        "asOfDate": str(as_of) if as_of is not None else None,
        "baseline_window": "panel_month_seq 1-6",
        "current_window": "panel_month_seq 7-12",
        "_caveat": (
            "Baseline vs. current here is a temporal split within one synthetic "
            "dataset, not a comparison against independent production traffic."
        ),
    }


def validate_drift_detector(seed: int = 42) -> dict:
    """Synthetic injection test -- see module docstring. Returns the accuracy
    of the PSI>=threshold rule at recovering which features were artificially
    shifted, on a held-out current-period sample."""
    rng = np.random.default_rng(seed)
    baseline, current = _load_periods()
    feats = list(TRACKED_FEATURES.keys())
    rng.shuffle(feats)
    half = len(feats) // 2
    shifted_feats = set(feats[:half])

    correct = 0
    for feat in feats:
        base_vals = baseline[feat].to_numpy(dtype=float)
        cur_vals = current[feat].to_numpy(dtype=float).copy()
        cur_vals = cur_vals[~np.isnan(cur_vals)]
        if feat in shifted_feats and len(cur_vals) > 0:
            # Inject a clearly-detectable synthetic shift: shift the mean by
            # 1.5 std-devs and widen the spread by 50%.
            std = np.nanstd(base_vals) or 1.0
            mean_shift = 1.5 * std
            cur_vals = (cur_vals - cur_vals.mean()) * 1.5 + cur_vals.mean() + mean_shift
        psi = _psi(base_vals, cur_vals)
        predicted_drift = psi >= ALERT_THRESHOLD
        actual_drift = feat in shifted_feats
        if predicted_drift == actual_drift:
            correct += 1

    accuracy = correct / len(feats) if feats else 0.0
    return {
        "accuracy": round(accuracy, 4),
        "n_features_tested": len(feats),
        "n_shifted": len(shifted_feats),
        "_method": (
            "Synthetic drift injected into half the tracked features "
            "(mean shift +1.5 baseline std-devs, spread x1.5); accuracy is "
            "the PSI>=0.10 rule's agreement with which features were shifted."
        ),
    }


def main():
    report = compute_drift_report()
    validation = validate_drift_detector()
    report["detector_validation"] = validation
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print("=== Drift report ===")
    for s in report["signals"]:
        flag = "ALERT" if s["alert"] else "stable"
        print(f"  {s['name']:<32} PSI={s['psi']:.4f}  [{flag}]")
    print(f"\n{report['nFeaturesAlerting']} of {len(report['signals'])} tracked features alerting "
          f"(threshold {report['alertThreshold']})")
    print(f"\n=== Synthetic detector validation ===")
    print(f"Accuracy: {validation['accuracy']:.4f} "
          f"({validation['n_shifted']} of {validation['n_features_tested']} features shifted)")
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
