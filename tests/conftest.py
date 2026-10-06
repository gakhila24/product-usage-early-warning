"""Shared fixtures.  Tests run against the real pipeline output in ../data (built by run_pipeline.py).
If it has not been built yet, the session fixture builds it once (about 1-2 minutes)."""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DATA = ROOT / "data"
sys.path.insert(0, str(SRC))


def _pipeline_ready() -> bool:
    if not (DATA / "churn_data.db").exists():
        return False
    conn = sqlite3.connect(DATA / "churn_data.db")
    try:
        names = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    finally:
        conn.close()
    need = {"accounts", "account_monthly_metrics_enriched", "model_scores", "interventions", "baseline_benchmark", "ac_followups"}
    files = ["model_metrics.json", "feature_importance.csv", "drift_report.json", "account_graph.graphml", "narrative_index.pkl", "narratives.csv"]
    return need <= names and all((DATA / f).exists() for f in files)


def _ensure_pipeline():
    if not _pipeline_ready():
        import run_pipeline
        argv, sys.argv = sys.argv, ["run_pipeline.py"]
        try:
            run_pipeline.main()
        finally:
            sys.argv = argv


def pytest_configure(config):
    """Several modules (explanation_agent, graph_rag) read pipeline output at import time, i.e. during test
    collection -- so the data must exist before collection starts, not just before the first test runs."""
    _ensure_pipeline()


@pytest.fixture(scope="session", autouse=True)
def pipeline():
    _ensure_pipeline()
    return DATA


@pytest.fixture(scope="session")
def client(pipeline):
    import api
    return api.app.test_client()


@pytest.fixture(scope="session")
def ac(pipeline):
    import action_center_service as svc
    svc.ensure_tables()
    return svc


@pytest.fixture()
def restore_action_center(ac):
    """Tests that write follow-ups / alerts / reports / settings leave the DB as they found it."""
    yield
    ac.seed_followups()
    ac.seed_alerts()
    conn = ac._conn()
    conn.execute("DELETE FROM ac_reports")
    conn.execute("DELETE FROM ac_settings")
    conn.commit()
    conn.close()
