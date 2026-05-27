"""Step 5: export the dimensional model for Power BI.

kpis.py already writes the pre aggregated gold marts to dashboard/. This step
also exports the silver star schema (clean table names) to dashboard/model/ so
the model can be imported into Power BI with real relationships, which is the
basis for the DAX measures in powerbi/dax_measures.md.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

import config

MODEL = config.DASHBOARD / "model"

# silver table -> Power BI friendly table name
TABLES = {
    "silver_dim_employee": "dim_employee",
    "silver_dim_department": "dim_department",
    "silver_dim_job_role": "dim_job_role",
    "silver_dim_date": "dim_date",
    "silver_fact_employment": "fact_employment",
    "silver_fact_absence": "fact_absence",
    "silver_fact_recruitment": "fact_recruitment",
}


def main() -> None:
    MODEL.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(config.DB_PATH) as conn:
        for src, name in TABLES.items():
            pd.read_sql(f"SELECT * FROM {src}", conn).to_csv(MODEL / f"{name}.csv", index=False)
    print(f"Exported {len(TABLES)} model tables to {MODEL}")
    print("Import these into Power BI and add the measures from powerbi/dax_measures.md.")


if __name__ == "__main__":
    main()
