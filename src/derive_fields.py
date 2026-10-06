"""
Derived & Cleaned Fields Layer — Design Doc Section 2.2
=========================================================
Applies, once, in the ingestion job, before anything else reads the data:
  1. arr_run_rate_usd        = monthly_spend_usd * 12          (derived ARR)
  2. revenue_movement_bucket = Churned / Mixed / Upsell / Downgrade / Flat
  3. age_bucket              = cleaned account_age_months, with negative
                                (pre-signup placeholder) rows bucketed
                                separately instead of poisoning a numeric bucket
  4. intervention_type_clean = intervention_type, restricted to the 4 values
                                that actually occur in the data (documented
                                5th value, "Executive Business Review", never
                                appears — kept as a documented zero-count
                                category rather than silently dropped)
Writes account_monthly_metrics_enriched.csv/table.
"""
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "churn_data.db"

ALL_INTERVENTION_TYPES = [
    "Training & Enablement Session",
    "Technical / Support Health Check",
    "Champion Re-engagement Outreach",
    "Commercial Discount Review",
    "Executive Business Review",  # documented, never occurs in this dataset
]

AGE_BUCKET_EDGES = [0, 12, 24, 48, 96, np.inf]
AGE_BUCKET_LABELS = ["0-12mo", "13-24mo", "25-48mo", "49-96mo", "96mo+"]


def revenue_movement(row) -> str:
    if int(row["churned_within_90d"]) == 1:
        return "Churned"
    up, down = bool(row["upsell_flag_90d"]), bool(row["downgrade_flag_90d"])
    if up and down:
        return "Mixed"
    if up:
        return "Upsell"
    if down:
        return "Downgrade"
    return "Flat"


def age_bucket(age_months) -> str:
    if age_months < 0:
        return "Pre-signup"
    idx = np.searchsorted(AGE_BUCKET_EDGES, age_months, side="right") - 1
    idx = min(idx, len(AGE_BUCKET_LABELS) - 1)
    return AGE_BUCKET_LABELS[idx]


def main():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM account_monthly_metrics", conn)

    # 1. ARR run-rate (derived, NOT a real contract value — label everywhere)
    df["arr_run_rate_usd"] = (df["monthly_spend_usd"] * 12).round(2)

    # 2. Revenue movement bucket, with explicit precedence rule
    df["revenue_movement_bucket"] = df.apply(revenue_movement, axis=1)

    # 3. Cleaned age bucket (negative tenure -> "Pre-signup", never a numeric bucket)
    df["age_bucket"] = df["account_age_months"].apply(age_bucket)

    # 4. intervention_type is left as-is (already only the 4 real values) —
    #    ALL_INTERVENTION_TYPES above is the canonical 5-value legend the UI
    #    should render (with the 5th at a documented zero count), not a filter
    #    applied to the data itself.

    df.to_sql("account_monthly_metrics_enriched", conn, if_exists="replace", index=False)
    df.to_csv(DATA_DIR / "account_monthly_metrics_enriched.csv", index=False)

    # ---- sanity checks ----
    print("=== Derived field sanity checks ===")
    print("revenue_movement_bucket distribution:")
    print(df["revenue_movement_bucket"].value_counts())
    print()
    print("age_bucket distribution:")
    print(df["age_bucket"].value_counts())
    print()
    print("ARR run-rate, mean/median/max ($):", df["arr_run_rate_usd"].mean().round(0),
          df["arr_run_rate_usd"].median().round(0), df["arr_run_rate_usd"].max().round(0))
    print()
    mixed_check = df[(df["upsell_flag_90d"] == 1) & (df["downgrade_flag_90d"] == 1)]
    assert (mixed_check["revenue_movement_bucket"].isin(["Mixed", "Churned"])).all(), \
        "Mixed-flag rows must resolve to Mixed or Churned"
    print(f"Rows with both upsell+downgrade flagged, correctly bucketed: {len(mixed_check)}")

    conn.close()
    print(f"\nWrote enriched table + CSV to {DATA_DIR}")


if __name__ == "__main__":
    main()
