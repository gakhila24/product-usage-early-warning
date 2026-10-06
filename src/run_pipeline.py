"""
One-shot data + model pipeline.   python run_pipeline.py [--seed 42] [--skip-generate]

  1. generate_synthetic_data  -> data/churn_data.db, model_train/holdout/baseline CSVs   (fully synthetic)
  2. derive_fields            -> account_monthly_metrics_enriched
  3. train_model              -> model_scores, feature_importance.csv, model_metrics.json (RandomForest + LogReg)
  4. drift_monitor            -> drift_report.json (PSI)
  5. build_graph              -> account_graph.graphml   (GraphRAG: relationships)
  6. narratives               -> narratives.csv + narrative_index.pkl   (GraphRAG: retrieval)
  7. Action Center seed       -> alerts feed + follow-up board (ac_* tables)

Each step is the original, unmodified module's main() (apart from small documented patches).
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def step(n, title, fn):
    t = time.time()
    print(f"\n[{n}/7] {title} ...", flush=True)
    fn()
    print(f"      done in {time.time() - t:.1f}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-generate", action="store_true", help="reuse the existing churn_data.db raw tables")
    args = ap.parse_args()

    import generate_synthetic_data, derive_fields, train_model, drift_monitor, build_graph, narratives
    import networkx as nx
    from build_graph import DATA_DIR

    if args.skip_generate:
        print("[1/7] generate_synthetic_data skipped (--skip-generate)")
    else:
        step(1, "Generating synthetic dataset", lambda: generate_synthetic_data.main(args.seed))
    step(2, "Deriving fields", derive_fields.main)
    step(3, "Training churn models (RandomForest + LogisticRegression)", train_model.main)
    step(4, "Computing input-drift report (PSI)", drift_monitor.main)

    def graph():
        g = build_graph.build_graph()
        build_graph.demo_queries(g)
        nx.write_graphml(g, DATA_DIR / "account_graph.graphml")
    step(5, "Building the account relationship graph", graph)
    step(6, "Building narratives + TF-IDF index", narratives.main)

    def seed():
        import action_center_service as ac
        ac.invalidate_cache()
        ac.ensure_tables()
        print("      follow-ups seeded:", ac.seed_followups(), "| alerts seeded:", ac.seed_alerts())
    step(7, "Seeding Action Center (alerts + follow-up board)", seed)
    print("\nPipeline complete. Start the API with:  python api.py")


if __name__ == "__main__":
    main()
