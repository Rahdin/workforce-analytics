"""Step 1: build the warehouse.

Loads the three raw inputs into a bronze layer, derives termination dates for
leavers (the IBM file carries an attrition flag but no dates), then runs
sql/01_star_schema.sql to materialise the silver dimensional model. If the raw
inputs are missing the sample generator is invoked first, so the pipeline runs
end to end from a clean checkout.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

import config
import make_sample_data


def ensure_inputs() -> None:
    need = [config.employee_source(), config.ABSENCE_CSV, config.RECRUITMENT_CSV]
    if not all(p.exists() for p in need):
        make_sample_data.main()


def load_bronze(conn: sqlite3.Connection) -> None:
    employees = pd.read_csv(config.employee_source())
    absence = pd.read_csv(config.ABSENCE_CSV)
    recruitment = pd.read_csv(config.RECRUITMENT_CSV)
    employees.to_sql("bronze_employees", conn, if_exists="replace", index=False)
    absence.to_sql("bronze_absence", conn, if_exists="replace", index=False)
    recruitment.to_sql("bronze_recruitment", conn, if_exists="replace", index=False)
    return employees, recruitment


def derive_terminations(employees: pd.DataFrame, recruitment: pd.DataFrame, conn: sqlite3.Connection) -> None:
    """Place every separation inside the trailing analysis window, never before hire."""
    rng = np.random.default_rng(config.RANDOM_SEED + 1)
    leavers = employees.loc[employees["Attrition"] == "Yes", ["EmployeeNumber"]].copy()
    hire = recruitment.set_index("EmployeeNumber")["HireDate"]
    leavers["hire_date"] = pd.to_datetime(leavers["EmployeeNumber"].map(hire))

    as_of = pd.Timestamp(config.AS_OF_DATE)
    offsets = rng.integers(0, 365, size=len(leavers))
    term = as_of - pd.to_timedelta(offsets, unit="D")
    # A leaver hired less than a year ago cannot have left before being hired.
    term = np.maximum(term.values, (leavers["hire_date"] + pd.Timedelta(days=14)).values)
    leavers["termination_date"] = pd.to_datetime(term).strftime("%Y-%m-%d")

    leavers[["EmployeeNumber", "termination_date"]].to_sql(
        "stage_termination", conn, if_exists="replace", index=False
    )


def build_silver(conn: sqlite3.Connection) -> None:
    sql = (config.SQL_DIR / "01_star_schema.sql").read_text(encoding="utf-8")
    sql = sql.replace("{AS_OF}", config.AS_OF_DATE.isoformat())
    conn.executescript(sql)


def validate(conn: sqlite3.Connection) -> None:
    tables = [
        "silver_dim_employee",
        "silver_dim_department",
        "silver_dim_job_role",
        "silver_dim_date",
        "silver_fact_employment",
        "silver_fact_absence",
        "silver_fact_recruitment",
    ]
    print("Silver layer row counts:")
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<28} {n:>8,}")

    print("\nSample 3 table join (attrition rate by department):")
    rows = conn.execute(
        """
        SELECT d.department_name,
               COUNT(*)                          AS headcount,
               SUM(f.attrition_flag)             AS leavers,
               ROUND(100.0 * AVG(f.attrition_flag), 1) AS attrition_pct
        FROM silver_fact_employment f
        JOIN silver_dim_department d ON d.department_key = f.department_key
        JOIN silver_dim_employee   e ON e.employee_key   = f.employee_key
        GROUP BY d.department_name
        ORDER BY attrition_pct DESC
        """
    ).fetchall()
    for r in rows:
        print(f"  {r[0]:<26} headcount={r[1]:>5,}  leavers={r[2]:>4}  attrition={r[3]:>5}%")


def main() -> None:
    ensure_inputs()
    config.DB_PATH.unlink(missing_ok=True)
    with sqlite3.connect(config.DB_PATH) as conn:
        employees, recruitment = load_bronze(conn)
        derive_terminations(employees, recruitment, conn)
        build_silver(conn)
        conn.commit()
        validate(conn)
    print(f"\nWarehouse built -> {config.DB_PATH}")


if __name__ == "__main__":
    main()
