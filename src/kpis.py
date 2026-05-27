"""Step 2: compute the standard people analytics measures.

Runs sql/02_kpi_queries.sql against the warehouse to build the gold marts, then
exports every gold table to dashboard/ as a Power BI ready extract and prints the
headline measures.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

import config

HOURS_PER_CAL_DAY = config.SCHEDULED_HOURS_PER_MONTH / 30.44
ABSENCE_WINDOW_DAYS = 365


def run_gold(conn: sqlite3.Connection) -> None:
    sql = (config.SQL_DIR / "02_kpi_queries.sql").read_text(encoding="utf-8")
    sql = (
        sql.replace("{AS_OF}", config.AS_OF_DATE.isoformat())
        .replace("{WINDOW_DAYS}", str(ABSENCE_WINDOW_DAYS))
        .replace("{HOURS_PER_CAL_DAY}", f"{HOURS_PER_CAL_DAY:.4f}")
        .replace("{EARLY_TENURE_DAYS}", str(config.EARLY_TENURE_DAYS))
    )
    conn.executescript(sql)
    conn.commit()


def export_extracts(conn: sqlite3.Connection) -> list[str]:
    gold = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'gold_%' ORDER BY name"
        )
    ]
    for t in gold:
        df = pd.read_sql(f"SELECT * FROM {t}", conn)
        df.to_csv(config.DASHBOARD / f"{t}.csv", index=False)
    return gold


def print_headlines(conn: sqlite3.Connection) -> None:
    def one(q):
        return conn.execute(q).fetchone()

    turn = one("SELECT turnover_pct, separations, headcount_current FROM gold_kpi_turnover WHERE segment_type='Overall'")
    absen = one("SELECT absenteeism_rate_pct, avg_absence_days FROM gold_kpi_absenteeism WHERE segment_type='Overall'")
    qoh = one("SELECT quality_of_hire, avg_time_to_fill FROM gold_kpi_quality_of_hire WHERE segment_type='Overall'")

    print("Headline measures (trailing 12 months):")
    print(f"  Annualised turnover     {turn[0]:>6}%   ({turn[1]} separations, {turn[2]} active)")
    print(f"  Absenteeism rate        {absen[0]:>6}%   ({absen[1]} avg days per employee)")
    print(f"  Quality of Hire index   {qoh[0]:>6}    (avg time to fill {qoh[1]:.0f} days)")

    print("\nTurnover by department:")
    for r in conn.execute(
        "SELECT segment, turnover_pct FROM gold_kpi_turnover WHERE segment_type='Department' ORDER BY turnover_pct DESC"
    ):
        print(f"  {r[0]:<26} {r[1]:>5}%")

    print("\nQuality of Hire by source channel:")
    for r in conn.execute(
        "SELECT segment, quality_of_hire, avg_time_to_fill FROM gold_kpi_quality_of_hire "
        "WHERE segment_type='Source channel' ORDER BY quality_of_hire DESC"
    ):
        print(f"  {r[0]:<22} QoH={r[1]:>5}   time-to-fill={r[2]:.0f}d")


def main() -> None:
    with sqlite3.connect(config.DB_PATH) as conn:
        run_gold(conn)
        gold = export_extracts(conn)
        print(f"Exported {len(gold)} gold extracts to {config.DASHBOARD}\n")
        print_headlines(conn)


if __name__ == "__main__":
    main()
