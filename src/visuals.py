"""Step 4: figures for the report, the blog post, and the README.

Reads the gold marts and the study results and writes a small set of clean figures
to reports/figures/.
"""
from __future__ import annotations

import json
import sqlite3

import matplotlib.pyplot as plt
import pandas as pd

import config

plt.rcParams.update(
    {
        "figure.dpi": 130,
        "savefig.dpi": 130,
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "figure.autolayout": True,
    }
)


def _save(fig, name: str) -> None:
    path = config.FIGURES / name
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  {name}")


def fig_odds_ratios(metrics: dict) -> None:
    rows = sorted(metrics["logistic_regression"]["odds_ratios"], key=lambda r: r["odds_ratio"])
    terms = [r["term"] for r in rows]
    y = range(len(rows))
    fig, ax = plt.subplots(figsize=(8.2, 6.4))
    for i, r in enumerate(rows):
        sig = r["significant"]
        color = config.BRAND_CORAL if r["odds_ratio"] > 1 else config.BRAND_TEAL
        color = color if sig else config.BRAND_GREY
        ax.plot([r["or_low"], r["or_high"]], [i, i], color=color, lw=2, alpha=0.9 if sig else 0.5)
        ax.plot(r["odds_ratio"], i, "o", color=color, ms=7, alpha=0.95 if sig else 0.5)
    ax.axvline(1.0, color="#333333", lw=1, ls="--")
    ax.set_yticks(list(y))
    ax.set_yticklabels(terms)
    ax.set_xscale("log")
    ax.set_xlabel("Odds ratio for leaving (log scale, 95% CI)")
    ax.set_title("What independently moves the odds of attrition")
    ax.margins(y=0.02)
    _save(fig, "fig_odds_ratios.png")


def fig_attrition_drivers(conn: sqlite3.Connection) -> None:
    drivers = ["Job satisfaction", "Work-life balance", "Overtime"]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8))
    for ax, drv in zip(axes, drivers):
        d = pd.read_sql(
            "SELECT level, attrition_pct FROM gold_attrition_drivers WHERE driver=? ORDER BY level",
            conn,
            params=(drv,),
        )
        ax.bar(d["level"], d["attrition_pct"], color=config.BRAND_NAVY)
        ax.set_title(drv)
        ax.set_ylabel("Attrition %" if drv == drivers[0] else "")
        ax.tick_params(axis="x", rotation=20)
    fig.suptitle("Attrition rate by I-O construct", fontsize=14, fontweight="bold")
    _save(fig, "fig_attrition_drivers.png")


def fig_turnover_department(conn: sqlite3.Connection) -> None:
    d = pd.read_sql(
        "SELECT segment, turnover_pct FROM gold_kpi_turnover WHERE segment_type='Department' ORDER BY turnover_pct",
        conn,
    )
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ax.barh(d["segment"], d["turnover_pct"], color=config.BRAND_TEAL)
    for i, v in enumerate(d["turnover_pct"]):
        ax.text(v + 0.4, i, f"{v}%", va="center")
    ax.set_xlabel("Annualised turnover %")
    ax.set_title("Turnover by department")
    _save(fig, "fig_turnover_by_department.png")


def fig_quality_of_hire(conn: sqlite3.Connection) -> None:
    d = pd.read_sql(
        "SELECT segment, quality_of_hire, avg_time_to_fill FROM gold_kpi_quality_of_hire "
        "WHERE segment_type='Source channel' ORDER BY quality_of_hire",
        conn,
    )
    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    ax.barh(d["segment"], d["quality_of_hire"], color=config.BRAND_AMBER)
    for i, (q, t) in enumerate(zip(d["quality_of_hire"], d["avg_time_to_fill"])):
        ax.text(q + 0.4, i, f"{q}  ({t:.0f}d to fill)", va="center")
    ax.set_xlim(0, 100)
    ax.set_xlabel("Quality of Hire index")
    ax.set_title("Quality of Hire by recruiting source")
    _save(fig, "fig_quality_of_hire_by_source.png")


def fig_headcount_trend(conn: sqlite3.Connection) -> None:
    d = pd.read_sql(
        "SELECT month_start, active_headcount, separations FROM gold_headcount_monthly ORDER BY date_key",
        conn,
    )
    d["month_start"] = pd.to_datetime(d["month_start"])
    fig, ax1 = plt.subplots(figsize=(9.2, 4.0))
    ax2 = ax1.twinx()
    ax2.bar(d["month_start"], d["separations"], width=20, color=config.BRAND_GREY, alpha=0.45, label="Separations")
    ax1.plot(d["month_start"], d["active_headcount"], color=config.BRAND_NAVY, lw=2.4, marker="o", ms=3, label="Active headcount")
    ax1.set_ylabel("Active headcount")
    ax2.set_ylabel("Separations")
    ax1.set_title("Headcount and separations, trailing 24 months")
    ax1.grid(False)
    ax2.grid(False)
    _save(fig, "fig_headcount_trend.png")


def fig_absence_reason(conn: sqlite3.Connection) -> None:
    d = pd.read_sql("SELECT reason_code, absence_hours FROM gold_absence_by_reason ORDER BY absence_hours", conn)
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    ax.barh(d["reason_code"], d["absence_hours"], color=config.BRAND_CORAL)
    ax.set_xlabel("Absence hours")
    ax.set_title("Absence hours by reason")
    _save(fig, "fig_absence_by_reason.png")


def main() -> None:
    metrics = json.loads((config.REPORTS / "metrics.json").read_text(encoding="utf-8"))
    print("Writing figures:")
    with sqlite3.connect(config.DB_PATH) as conn:
        fig_odds_ratios(metrics)
        fig_attrition_drivers(conn)
        fig_turnover_department(conn)
        fig_quality_of_hire(conn)
        fig_headcount_trend(conn)
        fig_absence_reason(conn)
    print(f"Figures written to {config.FIGURES}")


if __name__ == "__main__":
    main()
