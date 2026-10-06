"""
MCP Server — Tool Catalog — Design Doc Section 3.2
=====================================================
Each function below is written as the implementation behind one MCP tool:
typed inputs/outputs, read-only except `log_intervention`, structured errors
instead of stack traces, and every call logged (see `_audit_log`) for the
Day-9 audit requirement.

Environment note: this sandbox has no network access to install the `mcp`
Python SDK, so these are plain, directly-callable Python functions rather
than a running MCP server process. To actually expose them over the MCP
protocol, wrap each function with `@server.tool()` from the `mcp` package --
the function bodies below don't need to change at all. This file is imported
directly by api.py in the meantime, which is the honest state of "MCP-shaped
code, not yet MCP-protocol-wrapped."
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "churn_data.db"
AUDIT_LOG_PATH = DATA_DIR / "mcp_audit_log.jsonl"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _audit_log(tool: str, args: dict, caller: str = "system"):
    entry = {"ts": time.time(), "tool": tool, "args": args, "caller": caller}
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


class ToolError(Exception):
    """Structured error — the agent sees {"error": "..."} not a stack trace."""


def get_account_profile(account_id: str) -> dict:
    _audit_log("get_account_profile", {"account_id": account_id})
    conn = _conn()
    cur = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise ToolError(f"unknown account_id: {account_id}")
    return dict(row)


def get_account_history(account_id: str, n_months: int = 12) -> list[dict]:
    _audit_log("get_account_history", {"account_id": account_id, "n_months": n_months})
    conn = _conn()
    cur = conn.execute(
        """SELECT * FROM account_monthly_metrics_enriched
           WHERE account_id = ? ORDER BY panel_month_seq DESC LIMIT ?""",
        (account_id, n_months),
    )
    rows = _rows(cur)
    conn.close()
    return list(reversed(rows))


def get_model_score(account_id: str, as_of_month: Optional[str] = None) -> dict:
    """The single source of truth for the badge color -- see design doc 2.2."""
    _audit_log("get_model_score", {"account_id": account_id, "as_of_month": as_of_month})
    conn = _conn()
    if as_of_month:
        cur = conn.execute(
            "SELECT * FROM model_scores WHERE account_id=? AND as_of_month=?",
            (account_id, as_of_month),
        )
    else:
        cur = conn.execute(
            """SELECT * FROM model_scores WHERE account_id=?
               ORDER BY panel_month_seq DESC LIMIT 1""",
            (account_id,),
        )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise ToolError(f"no model score for account_id: {account_id}")
    return dict(row)


def get_commercial_summary(account_id: str) -> dict:
    _audit_log("get_commercial_summary", {"account_id": account_id})
    conn = _conn()
    cur = conn.execute(
        """SELECT as_of_month, monthly_spend_usd, arr_run_rate_usd, spend_trend_3m_pct,
                  discount_pct, payment_failure_90d_count, invoice_overdue_flag,
                  revenue_movement_bucket
           FROM account_monthly_metrics_enriched
           WHERE account_id=? ORDER BY panel_month_seq DESC LIMIT 1""",
        (account_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise ToolError(f"unknown account_id: {account_id}")
    return dict(row)


def get_support_summary(account_id: str) -> dict:
    _audit_log("get_support_summary", {"account_id": account_id})
    conn = _conn()
    cur = conn.execute(
        """SELECT as_of_month, support_tickets_90d, escalations_90d, high_priority_tickets_90d,
                  avg_resolution_time_hrs, csat_score, support_friction_score,
                  technical_issue_count_90d, technical_friction_score
           FROM account_monthly_metrics_enriched
           WHERE account_id=? ORDER BY panel_month_seq DESC LIMIT 1""",
        (account_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise ToolError(f"unknown account_id: {account_id}")
    return dict(row)


def get_stakeholder_summary(account_id: str) -> dict:
    _audit_log("get_stakeholder_summary", {"account_id": account_id})
    conn = _conn()
    cur = conn.execute(
        """SELECT as_of_month, num_active_stakeholders, executive_sponsor_engaged,
                  qbr_attended_last_90d, days_since_last_csm_touchpoint,
                  champion_turnover_flag_90d, nps_last_survey
           FROM account_monthly_metrics_enriched
           WHERE account_id=? ORDER BY panel_month_seq DESC LIMIT 1""",
        (account_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise ToolError(f"unknown account_id: {account_id}")
    return dict(row)


def get_intervention_history(account_id: str) -> list[dict]:
    _audit_log("get_intervention_history", {"account_id": account_id})
    conn = _conn()
    cur = conn.execute(
        "SELECT * FROM interventions WHERE account_id=? ORDER BY as_of_month", (account_id,)
    )
    rows = _rows(cur)
    conn.close()
    return rows


def list_at_risk_accounts(
    segment: Optional[str] = None, region: Optional[str] = None,
    industry: Optional[str] = None, csm_owner: Optional[str] = None,
    band: Optional[str] = None, min_score: Optional[float] = None,
    limit: int = 50, offset: int = 0,
) -> dict:
    _audit_log("list_at_risk_accounts", {
        "segment": segment, "region": region, "industry": industry,
        "csm_owner": csm_owner, "band": band, "min_score": min_score,
    })
    where = ["s.panel_month_seq = 12"]
    params: list = []
    if segment:
        where.append("a.segment = ?"); params.append(segment)
    if region:
        where.append("a.region = ?"); params.append(region)
    if industry:
        where.append("a.industry = ?"); params.append(industry)
    if csm_owner:
        where.append("a.csm_owner = ?"); params.append(csm_owner)
    if band:
        where.append("s.risk_band = ?"); params.append(band)
    if min_score is not None:
        where.append("s.risk_score >= ?"); params.append(min_score)
    where_clause = " AND ".join(where)
    conn = _conn()
    total = conn.execute(
        f"""SELECT COUNT(*) c FROM model_scores s
            JOIN accounts a ON a.account_id = s.account_id
            WHERE {where_clause}""", params,
    ).fetchone()["c"]
    cur = conn.execute(
        f"""SELECT a.account_id, a.segment, a.region, a.industry, a.csm_owner,
                   a.contract_type, s.risk_score, s.risk_band,
                   m.arr_run_rate_usd, m.days_to_renewal,
                   m.days_since_last_csm_touchpoint, m.days_since_last_login
            FROM model_scores s
            JOIN accounts a ON a.account_id = s.account_id
            JOIN account_monthly_metrics_enriched m
                 ON m.account_id = s.account_id AND m.panel_month_seq = 12
            WHERE {where_clause}
            ORDER BY s.risk_score DESC LIMIT ? OFFSET ?""",
        params + [limit, offset],
    )
    rows = _rows(cur)
    conn.close()
    return {"total": total, "accounts": rows}


def get_cohort_accounts(account_id: str, limit: int = 5) -> list[dict]:
    """Graph-backed: same industry+segment peers. See build_graph.py for the
    full traversal; this is the MCP-tool-facing, DB-backed equivalent."""
    _audit_log("get_cohort_accounts", {"account_id": account_id})
    conn = _conn()
    prof = conn.execute(
        "SELECT industry, segment FROM accounts WHERE account_id=?", (account_id,)
    ).fetchone()
    if prof is None:
        conn.close()
        raise ToolError(f"unknown account_id: {account_id}")
    cur = conn.execute(
        """SELECT a.account_id, s.risk_score, s.risk_band
           FROM accounts a JOIN model_scores s
                ON s.account_id = a.account_id AND s.panel_month_seq = 12
           WHERE a.industry=? AND a.segment=? AND a.account_id != ?
           ORDER BY s.risk_score DESC LIMIT ?""",
        (prof["industry"], prof["segment"], account_id, limit),
    )
    rows = _rows(cur)
    conn.close()
    return rows


def get_baseline_score(account_id: str) -> dict:
    """Legacy baseline, NOT model input -- see design doc 2.1/2.2."""
    _audit_log("get_baseline_score", {"account_id": account_id})
    conn = _conn()
    cur = conn.execute(
        """SELECT heuristic_risk_score, heuristic_risk_band FROM baseline_benchmark
           WHERE account_id=? ORDER BY panel_month_seq DESC LIMIT 1""",
        (account_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise ToolError(f"unknown account_id: {account_id}")
    return {**dict(row), "_warning": "legacy baseline, not model input"}


def log_intervention(account_id: str, intervention_type: str, owner: str) -> dict:
    """The only write path. Scoped, audited."""
    _audit_log("log_intervention", {
        "account_id": account_id, "intervention_type": intervention_type, "owner": owner,
    }, caller="csm_ui")
    conn = _conn()
    exists = conn.execute(
        "SELECT 1 FROM accounts WHERE account_id=?", (account_id,)
    ).fetchone()
    if exists is None:
        conn.close()
        raise ToolError(f"unknown account_id: {account_id}")
    conn.execute(
        """INSERT INTO interventions
           (account_id, as_of_month, intervention_type, intervention_owner,
            intervention_date, intervention_status, intervention_outcome, usage_change_after_30d_pct)
           VALUES (?, date('now'), ?, ?, date('now'), 'Scheduled', NULL, NULL)""",
        (account_id, intervention_type, owner),
    )
    conn.commit()
    conn.close()
    return {"status": "logged", "account_id": account_id, "intervention_type": intervention_type}


if __name__ == "__main__":
    sample = list_at_risk_accounts(band="Critical", limit=3)
    print("=== list_at_risk_accounts(band='Critical', limit=3) ===")
    print(json.dumps(sample, indent=2, default=str))
    acct_id = sample["accounts"][0]["account_id"]
    print(f"\n=== get_model_score('{acct_id}') ===")
    print(json.dumps(get_model_score(acct_id), indent=2, default=str))
    print(f"\n=== get_cohort_accounts('{acct_id}') ===")
    print(json.dumps(get_cohort_accounts(acct_id), indent=2, default=str))
