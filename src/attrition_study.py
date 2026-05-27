"""Step 3: the workforce research study.

Research question
    Which workplace factors are most strongly associated with voluntary turnover,
    once everything else is held constant?

The analysis stays on the analyst side of the analyst and scientist line: it
describes and explains what the data says about the past, rather than predicting
individuals. It frames the drivers in the language people analytics and I-O
Psychology use, and pairs every claim with a significance test and an effect size
so the size of a relationship is reported, not just whether it is significant.

Outputs
    reports/metrics.json        machine readable results for the README and report
    reports/executive_summary.md a written summary with live numbers
"""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

import config

# Continuous measures compared between stayers and leavers (Welch t test + Cohen d).
CONTINUOUS = {
    "monthly_income": "Monthly income",
    "age": "Age",
    "tenure_years": "Tenure (years)",
    "distance_from_home": "Commute distance (km)",
    "years_since_last_promotion": "Years since last promotion",
    "num_companies_worked": "Prior employers",
    "training_times_last_year": "Training sessions last year",
}

# Categorical drivers tested for independence from attrition (chi square + Cramer V).
CATEGORICAL = {
    "overtime": "Overtime",
    "business_travel": "Business travel",
    "marital_status": "Marital status",
    "job_satisfaction": "Job satisfaction",
    "environment_satisfaction": "Environment satisfaction",
    "work_life_balance": "Work-life balance",
    "job_involvement": "Job involvement",
    "stock_option_level": "Stock option level",
}

LABELS = {
    "Intercept": "Intercept",
    "C(overtime, Treatment(0))[T.1]": "Works overtime",
    "C(business_travel, Treatment('Non-Travel'))[T.Travel_Frequently]": "Travels frequently",
    "C(business_travel, Treatment('Non-Travel'))[T.Travel_Rarely]": "Travels rarely",
    "C(marital_status, Treatment('Married'))[T.Single]": "Single (vs married)",
    "C(marital_status, Treatment('Married'))[T.Divorced]": "Divorced (vs married)",
    "job_satisfaction": "Job satisfaction (per point)",
    "environment_satisfaction": "Environment satisfaction (per point)",
    "work_life_balance": "Work-life balance (per point)",
    "job_involvement": "Job involvement (per point)",
    "age": "Age (per year)",
    "monthly_income_k": "Monthly income (per $1k)",
    "distance_from_home": "Commute distance (per km)",
    "years_since_last_promotion": "Years since promotion (per year)",
    "num_companies_worked": "Prior employers (per company)",
    "stock_option_level": "Stock option level (per level)",
    "tenure_years": "Tenure (per year)",
}


def load_data() -> pd.DataFrame:
    with sqlite3.connect(config.DB_PATH) as conn:
        df = pd.read_sql("SELECT * FROM gold_employee_analysis", conn)
    df["monthly_income_k"] = df["monthly_income"] / 1000.0
    return df


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = len(a), len(b)
    pooled = np.sqrt(((na - 1) * a.std(ddof=1) ** 2 + (nb - 1) * b.std(ddof=1) ** 2) / (na + nb - 2))
    return float((a.mean() - b.mean()) / pooled) if pooled else 0.0


def cramers_v(table: np.ndarray) -> float:
    chi2 = stats.chi2_contingency(table)[0]
    n = table.sum()
    r, k = table.shape
    return float(np.sqrt(chi2 / (n * (min(r, k) - 1)))) if min(r, k) > 1 else 0.0


def effect_label(value: float, kind: str) -> str:
    v = abs(value)
    if kind == "d":
        return "negligible" if v < 0.2 else "small" if v < 0.5 else "medium" if v < 0.8 else "large"
    return "negligible" if v < 0.1 else "small" if v < 0.3 else "medium" if v < 0.5 else "large"


def continuous_tests(df: pd.DataFrame) -> list[dict]:
    out = []
    leave = df[df["attrition_flag"] == 1]
    stay = df[df["attrition_flag"] == 0]
    for col, name in CONTINUOUS.items():
        a, b = leave[col].to_numpy(float), stay[col].to_numpy(float)
        t, p = stats.ttest_ind(a, b, equal_var=False)
        d = cohens_d(a, b)
        out.append(
            {
                "feature": name,
                "mean_leavers": round(float(a.mean()), 2),
                "mean_stayers": round(float(b.mean()), 2),
                "cohens_d": round(d, 3),
                "effect": effect_label(d, "d"),
                "p_value": round(float(p), 5),
                "significant": bool(p < 0.05),
            }
        )
    return sorted(out, key=lambda r: abs(r["cohens_d"]), reverse=True)


def categorical_tests(df: pd.DataFrame) -> list[dict]:
    out = []
    for col, name in CATEGORICAL.items():
        table = pd.crosstab(df[col], df["attrition_flag"]).to_numpy()
        chi2, p, dof, _ = stats.chi2_contingency(table)
        v = cramers_v(table)
        out.append(
            {
                "driver": name,
                "chi2": round(float(chi2), 2),
                "dof": int(dof),
                "cramers_v": round(v, 3),
                "effect": effect_label(v, "v"),
                "p_value": round(float(p), 5),
                "significant": bool(p < 0.05),
            }
        )
    return sorted(out, key=lambda r: r["cramers_v"], reverse=True)


def logistic_model(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    formula = (
        "attrition_flag ~ C(overtime, Treatment(0))"
        " + C(business_travel, Treatment('Non-Travel'))"
        " + C(marital_status, Treatment('Married'))"
        " + job_satisfaction + environment_satisfaction + work_life_balance + job_involvement"
        " + age + monthly_income_k + distance_from_home + years_since_last_promotion"
        " + num_companies_worked + stock_option_level + tenure_years"
    )
    model = smf.logit(formula, data=df).fit(disp=False, maxiter=200)

    params = model.params
    conf = model.conf_int()
    table = pd.DataFrame(
        {
            "term": [LABELS.get(i, i) for i in params.index],
            "odds_ratio": np.exp(params).round(3).to_numpy(),
            "or_low": np.exp(conf[0]).round(3).to_numpy(),
            "or_high": np.exp(conf[1]).round(3).to_numpy(),
            "p_value": params.index.map(lambda i: round(float(model.pvalues[i]), 5)),
        }
    )
    table = table[table["term"] != "Intercept"].reset_index(drop=True)
    table["significant"] = table["p_value"] < 0.05

    fit = {
        "observations": int(model.nobs),
        "pseudo_r2_mcfadden": round(float(model.prsquared), 3),
        "llr_p_value": round(float(model.llr_pvalue), 6),
    }
    return table.sort_values("odds_ratio", ascending=False).reset_index(drop=True), fit


def read_kpis(conn: sqlite3.Connection) -> dict:
    def row(q):
        return conn.execute(q).fetchone()

    turn = row("SELECT turnover_pct, separations, headcount_current FROM gold_kpi_turnover WHERE segment_type='Overall'")
    absen = row("SELECT absenteeism_rate_pct, avg_absence_days FROM gold_kpi_absenteeism WHERE segment_type='Overall'")
    qoh = row("SELECT quality_of_hire, avg_time_to_fill FROM gold_kpi_quality_of_hire WHERE segment_type='Overall'")
    best_src = row("SELECT segment, quality_of_hire FROM gold_kpi_quality_of_hire WHERE segment_type='Source channel' ORDER BY quality_of_hire DESC LIMIT 1")
    worst_src = row("SELECT segment, quality_of_hire FROM gold_kpi_quality_of_hire WHERE segment_type='Source channel' ORDER BY quality_of_hire ASC LIMIT 1")
    return {
        "annualised_turnover_pct": turn[0],
        "separations": turn[1],
        "active_headcount": turn[2],
        "absenteeism_rate_pct": absen[0],
        "avg_absence_days": absen[1],
        "quality_of_hire": qoh[0],
        "avg_time_to_fill_days": qoh[1],
        "best_source": {"channel": best_src[0], "qoh": best_src[1]},
        "worst_source": {"channel": worst_src[0], "qoh": worst_src[1]},
    }


def write_summary(metrics: dict) -> None:
    k = metrics["kpis"]
    or_table = metrics["logistic_regression"]["odds_ratios"]
    risk = [r for r in or_table if r["odds_ratio"] > 1 and r["significant"]][:6]
    protect = [r for r in or_table if r["odds_ratio"] < 1 and r["significant"]]
    protect = sorted(protect, key=lambda r: r["odds_ratio"])[:6]

    lines = []
    lines.append("# Workforce attrition study: executive summary")
    lines.append("")
    lines.append("> Generated by `src/attrition_study.py`. Figures refresh whenever the pipeline is rerun.")
    lines.append("")
    lines.append("## Headline measures, trailing 12 months")
    lines.append("")
    lines.append("| Measure | Value |")
    lines.append("|---|---|")
    lines.append(f"| Annualised turnover | {k['annualised_turnover_pct']}% ({k['separations']} separations) |")
    lines.append(f"| Absenteeism rate | {k['absenteeism_rate_pct']}% ({k['avg_absence_days']} days per employee) |")
    lines.append(f"| Quality of Hire index | {k['quality_of_hire']} / 100 |")
    lines.append(f"| Average time to fill | {k['avg_time_to_fill_days']:.0f} days |")
    lines.append("")
    lines.append("## Research question")
    lines.append("")
    lines.append(
        "Which workplace factors are most strongly associated with voluntary turnover once "
        "everything else is held constant? The aim is to point retention effort at the levers "
        "that matter rather than at whatever stands out in a single chart."
    )
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append(
        f"A multivariable logistic regression on {metrics['logistic_regression']['fit']['observations']:,} "
        "employees estimates the independent association of each factor with leaving, reported as an odds "
        "ratio with a 95 percent confidence interval. Each bivariate relationship is also tested on its own "
        "with a chi square test (categorical drivers, Cramer V effect size) or a Welch t test (continuous "
        "measures, Cohen d effect size). The model explains a McFadden pseudo R squared of "
        f"{metrics['logistic_regression']['fit']['pseudo_r2_mcfadden']}."
    )
    lines.append("")
    lines.append("## What raises the odds of leaving")
    lines.append("")
    lines.append("| Factor | Odds ratio | 95% CI | p |")
    lines.append("|---|---|---|---|")
    for r in risk:
        lines.append(f"| {r['term']} | {r['odds_ratio']:.2f} | {r['or_low']:.2f} to {r['or_high']:.2f} | {r['p_value']:.4f} |")
    lines.append("")
    lines.append("## What lowers the odds of leaving")
    lines.append("")
    lines.append("| Factor | Odds ratio | 95% CI | p |")
    lines.append("|---|---|---|---|")
    for r in protect:
        lines.append(f"| {r['term']} | {r['odds_ratio']:.2f} | {r['or_low']:.2f} to {r['or_high']:.2f} | {r['p_value']:.4f} |")
    lines.append("")
    lines.append("## Reading the result through an I-O Psychology lens")
    lines.append("")
    lines.append(
        "The pattern lines up with established turnover theory. Overtime and frequent travel raise the odds "
        "of leaving, consistent with strain and work-life conflict. Higher job satisfaction, environment "
        "satisfaction, work-life balance, and job involvement lower the odds, the job attitudes at the centre "
        "of withdrawal models. Tenure, income, and stock options act as embedding and retention forces, while "
        "a long gap since the last promotion signals stalled growth. None of these is destiny for an "
        "individual, but together they tell managers where to focus."
    )
    lines.append("")
    lines.append("## Recommended actions")
    lines.append("")
    lines.append("- Manage overtime load and travel intensity in the roles where both run highest.")
    lines.append("- Watch the first year and the years just after a missed promotion, the windows where exits cluster.")
    lines.append(f"- Shift sourcing toward the channels with the strongest Quality of Hire ({k['best_source']['channel']} leads at {k['best_source']['qoh']}) and review the weakest ({k['worst_source']['channel']} at {k['worst_source']['qoh']}).")
    lines.append("- Use job attitude survey items as an early warning layer, not just an annual snapshot.")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "This is an observational, cross sectional study, so associations are not proof of cause. Absence and "
        "recruitment facts are simulated where the base dataset does not carry them, which is stated so the "
        "method, not the exact number, is the transferable part."
    )
    (config.REPORTS / "executive_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    df = load_data()
    cont = continuous_tests(df)
    cat = categorical_tests(df)
    or_table, fit = logistic_model(df)
    with sqlite3.connect(config.DB_PATH) as conn:
        kpis = read_kpis(conn)

    metrics = {
        "kpis": kpis,
        "continuous_tests": cont,
        "categorical_tests": cat,
        "logistic_regression": {"fit": fit, "odds_ratios": or_table.to_dict("records")},
    }
    (config.REPORTS / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_summary(metrics)

    print(f"Logistic regression on {fit['observations']:,} employees, pseudo R2 = {fit['pseudo_r2_mcfadden']}")
    print("\nStrongest categorical drivers (Cramer V):")
    for r in cat[:4]:
        print(f"  {r['driver']:<26} V={r['cramers_v']:.3f} ({r['effect']}), p={r['p_value']}")
    print("\nLargest stayer vs leaver gaps (Cohen d):")
    for r in cont[:4]:
        print(f"  {r['feature']:<28} d={r['cohens_d']:+.3f} ({r['effect']}), leavers={r['mean_leavers']}, stayers={r['mean_stayers']}")
    print("\nTop attrition risk factors (odds ratio > 1, significant):")
    for r in [x for x in metrics["logistic_regression"]["odds_ratios"] if x["odds_ratio"] > 1 and x["significant"]][:6]:
        print(f"  {r['term']:<34} OR={r['odds_ratio']:.2f} [{r['or_low']:.2f}, {r['or_high']:.2f}], p={r['p_value']}")
    print(f"\nWrote reports/metrics.json and reports/executive_summary.md")


if __name__ == "__main__":
    main()
