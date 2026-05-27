"""Generate a runnable sample dataset for the people analytics pipeline.

The analysis is designed for the real IBM HR Analytics Employee Attrition dataset
(see README "Reproduce"). To keep the project runnable out of the box, this script
produces:

  1. employees_sample.csv  -> only when the real IBM file is absent. A faithful
     stand in that reproduces the IBM schema and realistic conditional structure
     (overtime, work life balance, satisfaction, pay, tenure all move attrition in
     the directions the people analytics literature expects).
  2. absence_events.csv    -> simulated absence spells keyed to each employee.
  3. recruitment.csv        -> one hiring record per employee (source channel,
     time to fill, ramp up, hiring manager satisfaction, hire date).

Absence and recruitment are always generated, keyed to whichever employee base is
present (real IBM file or the sample), so every KPI computes on one population and
the joins are real. Everything is seeded for full reproducibility.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

RNG = np.random.default_rng(config.RANDOM_SEED)
N_DEFAULT = 1470  # matches the real IBM row count

DEPARTMENTS = ["Research & Development", "Sales", "Human Resources"]
DEPT_P = [0.654, 0.303, 0.043]

ROLES_BY_DEPT = {
    "Research & Development": [
        ("Research Scientist", 0.34),
        ("Laboratory Technician", 0.31),
        ("Healthcare Representative", 0.14),
        ("Manufacturing Director", 0.13),
        ("Research Director", 0.05),
        ("Manager", 0.03),
    ],
    "Sales": [
        ("Sales Executive", 0.62),
        ("Sales Representative", 0.27),
        ("Manager", 0.11),
    ],
    "Human Resources": [
        ("Human Resources", 0.74),
        ("Manager", 0.26),
    ],
}

SOURCE_CHANNELS = [
    "Employee Referral",
    "Job Board",
    "Recruiting Agency",
    "Internal Transfer",
    "Campus",
    "Company Website",
]
SOURCE_P = [0.22, 0.24, 0.16, 0.12, 0.10, 0.16]

ABSENCE_REASONS = [
    "Sickness",
    "Medical Appointment",
    "Family Responsibility",
    "Personal",
    "Mental Health",
    "Bereavement",
]
ABSENCE_REASON_P = [0.50, 0.15, 0.12, 0.10, 0.08, 0.05]


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _weighted(values, probs, n):
    return RNG.choice(values, size=n, p=np.array(probs) / np.sum(probs))


def synthesize_employees(n: int = N_DEFAULT) -> pd.DataFrame:
    """Build an IBM schema employee table with realistic conditional structure."""
    emp_no = np.sort(RNG.choice(np.arange(1, 2200), size=n, replace=False))

    age = np.clip(RNG.normal(37, 9, n).round(), 18, 60).astype(int)
    department = RNG.choice(DEPARTMENTS, size=n, p=DEPT_P)

    job_role = np.empty(n, dtype=object)
    for dept, roles in ROLES_BY_DEPT.items():
        mask = department == dept
        names = [r[0] for r in roles]
        probs = np.array([r[1] for r in roles])
        probs = probs / probs.sum()
        job_role[mask] = RNG.choice(names, size=int(mask.sum()), p=probs)

    business_travel = _weighted(
        ["Travel_Rarely", "Travel_Frequently", "Non-Travel"], [0.71, 0.19, 0.10], n
    )
    distance = np.clip(RNG.exponential(8, n).round() + 1, 1, 29).astype(int)
    education = _weighted([1, 2, 3, 4, 5], [0.12, 0.19, 0.39, 0.27, 0.03], n)
    education_field = _weighted(
        ["Life Sciences", "Medical", "Marketing", "Technical Degree", "Other", "Human Resources"],
        [0.41, 0.32, 0.11, 0.09, 0.06, 0.01],
        n,
    )

    env_sat = _weighted([1, 2, 3, 4], [0.19, 0.19, 0.31, 0.31], n)
    job_sat = _weighted([1, 2, 3, 4], [0.20, 0.19, 0.30, 0.31], n)
    rel_sat = _weighted([1, 2, 3, 4], [0.18, 0.21, 0.31, 0.30], n)
    job_inv = _weighted([1, 2, 3, 4], [0.06, 0.26, 0.59, 0.09], n)
    wlb = _weighted([1, 2, 3, 4], [0.05, 0.23, 0.61, 0.11], n)

    job_level = _weighted([1, 2, 3, 4, 5], [0.37, 0.36, 0.15, 0.07, 0.05], n)
    gender = RNG.choice(["Male", "Female"], size=n, p=[0.60, 0.40])
    marital = RNG.choice(["Single", "Married", "Divorced"], size=n, p=[0.32, 0.46, 0.22])

    level_base = {1: 2700, 2: 5300, 3: 9800, 4: 15200, 5: 19000}
    base_income = np.array([level_base[l] for l in job_level], dtype=float)
    monthly_income = np.clip(
        (base_income * RNG.lognormal(0.0, 0.18, n)).round(), 1009, 19999
    ).astype(int)

    daily_rate = RNG.integers(102, 1500, n)
    hourly_rate = RNG.integers(30, 101, n)
    monthly_rate = RNG.integers(2094, 27000, n)
    num_companies = np.clip(RNG.poisson(2.0, n), 0, 9).astype(int)

    perf_rating = RNG.choice([3, 4], size=n, p=[0.846, 0.154])
    pct_hike = np.where(
        perf_rating == 4,
        RNG.integers(20, 26, n),
        RNG.integers(11, 22, n),
    ).astype(int)

    stock = _weighted([0, 1, 2, 3], [0.43, 0.40, 0.11, 0.06], n)

    total_working = np.clip(
        ((age - 21) * RNG.uniform(0.45, 0.95, n)).round(), 0, 40
    ).astype(int)
    years_at_company = np.minimum(total_working, np.clip(RNG.gamma(2.0, 3.0, n).round(), 0, 40).astype(int))
    years_in_role = (years_at_company * RNG.uniform(0.0, 0.85, n)).round().astype(int)
    years_since_promo = np.minimum(
        years_at_company, np.clip(RNG.gamma(1.3, 1.8, n).round(), 0, 15).astype(int)
    )
    years_with_mgr = (years_at_company * RNG.uniform(0.0, 0.85, n)).round().astype(int)
    training_times = _weighted([0, 1, 2, 3, 4, 5, 6], [0.05, 0.12, 0.36, 0.27, 0.12, 0.05, 0.03], n)

    overtime_p = sigmoid(
        -1.0
        + 0.6 * (business_travel == "Travel_Frequently")
        + 0.3 * (job_level >= 4)
        - 0.15 * (wlb - 2.5)
    )
    overtime = np.where(RNG.random(n) < overtime_p, "Yes", "No")

    # Attrition as a function of recognised drivers, centred so the coefficients
    # read as plausible log odds. The intercept is then calibrated by bisection so
    # the realised rate matches the real IBM base rate of about 16 percent.
    z0 = (
        1.05 * (overtime == "Yes")
        + 0.55 * (business_travel == "Travel_Frequently")
        - 0.38 * (wlb - 2.5)
        - 0.32 * (job_sat - 2.5)
        - 0.26 * (env_sat - 2.5)
        - 0.20 * (job_inv - 2.5)
        + 0.035 * (distance - 9)
        - 0.045 * (age - 37)
        + 0.14 * years_since_promo
        - 0.00006 * (monthly_income - 6500)
        + 0.45 * (marital == "Single")
        - 0.22 * stock
        + 0.10 * (num_companies - 2)
        - 0.06 * (years_at_company - 7)
    )
    target_rate = 0.161
    lo, hi = -10.0, 6.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if sigmoid(z0 + mid).mean() > target_rate:
            hi = mid
        else:
            lo = mid
    attrition = np.where(RNG.random(n) < sigmoid(z0 + (lo + hi) / 2), "Yes", "No")

    df = pd.DataFrame(
        {
            "Age": age,
            "Attrition": attrition,
            "BusinessTravel": business_travel,
            "DailyRate": daily_rate,
            "Department": department,
            "DistanceFromHome": distance,
            "Education": education,
            "EducationField": education_field,
            "EmployeeCount": 1,
            "EmployeeNumber": emp_no,
            "EnvironmentSatisfaction": env_sat,
            "Gender": gender,
            "HourlyRate": hourly_rate,
            "JobInvolvement": job_inv,
            "JobLevel": job_level,
            "JobRole": job_role,
            "JobSatisfaction": job_sat,
            "MaritalStatus": marital,
            "MonthlyIncome": monthly_income,
            "MonthlyRate": monthly_rate,
            "NumCompaniesWorked": num_companies,
            "Over18": "Y",
            "OverTime": overtime,
            "PercentSalaryHike": pct_hike,
            "PerformanceRating": perf_rating,
            "RelationshipSatisfaction": rel_sat,
            "StandardHours": 80,
            "StockOptionLevel": stock,
            "TotalWorkingYears": total_working,
            "TrainingTimesLastYear": training_times,
            "WorkLifeBalance": wlb,
            "YearsAtCompany": years_at_company,
            "YearsInCurrentRole": years_in_role,
            "YearsSinceLastPromotion": years_since_promo,
            "YearsWithCurrManager": years_with_mgr,
        }
    )
    return df


def make_absence(emp: pd.DataFrame, recruitment: pd.DataFrame) -> pd.DataFrame:
    """Simulate absence spells over the trailing 12 months, keyed to EmployeeNumber.

    Each employee is only exposed for the part of the trailing window they were
    actually employed, so recent hires are not credited with pre hire absences and
    their absence count scales with time on the job.
    """
    wlb = emp["WorkLifeBalance"].to_numpy()
    overtime = (emp["OverTime"].to_numpy() == "Yes").astype(float)
    distance = emp["DistanceFromHome"].to_numpy()

    as_of = np.datetime64(config.AS_OF_DATE)
    window_start = as_of - np.timedelta64(config.ANALYSIS_WINDOW_MONTHS * 30 + 5, "D")
    hire = (
        emp[["EmployeeNumber"]]
        .merge(recruitment[["EmployeeNumber", "HireDate"]], on="EmployeeNumber", how="left")["HireDate"]
        .to_numpy()
        .astype("datetime64[D]")
    )
    emp_window_start = np.maximum(window_start, hire)
    window_days = 365.0
    exposure_days = np.clip((as_of - emp_window_start).astype("timedelta64[D]").astype(int), 0, int(window_days))

    # Expected spells rise with poor work life balance, overtime, and commute, and
    # scale with the fraction of the window the employee was present.
    lam = np.clip(1.4 + 0.45 * (3 - wlb) + 0.40 * overtime + 0.02 * distance, 0.2, 6.0)
    lam_eff = lam * (exposure_days / window_days)
    counts = RNG.poisson(lam_eff)

    emp_no = np.repeat(emp["EmployeeNumber"].to_numpy(), counts)
    exp_per_event = np.repeat(exposure_days, counts)
    total = int(counts.sum())

    spell_days = RNG.choice([1, 2, 3, 4, 5], size=total, p=[0.55, 0.22, 0.12, 0.07, 0.04])
    hours = (spell_days * config.SCHEDULED_HOURS_PER_DAY).astype(float)
    reason = RNG.choice(ABSENCE_REASONS, size=total, p=ABSENCE_REASON_P)

    offset = np.floor(RNG.random(total) * np.maximum(exp_per_event, 1)).astype(int)
    absence_date = as_of - offset.astype("timedelta64[D]")

    out = pd.DataFrame(
        {
            "AbsenceID": np.arange(1, total + 1),
            "EmployeeNumber": emp_no,
            "AbsenceDate": np.datetime_as_string(absence_date, unit="D"),
            "AbsenceHours": hours,
            "AbsenceDays": spell_days,
            "ReasonCode": reason,
        }
    )
    return out.sort_values(["EmployeeNumber", "AbsenceDate"]).reset_index(drop=True)


def make_recruitment(emp: pd.DataFrame) -> pd.DataFrame:
    """One hiring record per employee: source, dates, ramp up, manager satisfaction."""
    n = len(emp)
    job_level = emp["JobLevel"].to_numpy()
    perf = emp["PerformanceRating"].to_numpy()
    years_at_company = emp["YearsAtCompany"].to_numpy()

    source = RNG.choice(SOURCE_CHANNELS, size=n, p=SOURCE_P)
    fast_source = np.isin(source, ["Employee Referral", "Internal Transfer"])
    slow_source = np.isin(source, ["Recruiting Agency"])

    # Time to fill grows with seniority and is shorter for referrals/internal moves.
    ttf = np.clip(
        RNG.gamma(shape=3.0, scale=10.0, size=n)
        + 8 * job_level
        - 12 * fast_source
        + 14 * slow_source,
        7,
        180,
    ).round().astype(int)

    # Ramp up to productivity, in days.
    ramp = np.clip(
        RNG.normal(70, 20, n) + 18 * (job_level - 1) - 16 * fast_source,
        20,
        220,
    ).round().astype(int)

    # Hiring manager satisfaction on a 1..5 scale, higher for referrals/internal and
    # for hires who turned out to perform well.
    hm_latent = (
        3.4
        + 0.5 * fast_source
        - 0.3 * slow_source
        + 0.6 * (perf == 4)
        + RNG.normal(0, 0.7, n)
    )
    hm_sat = np.clip(np.rint(hm_latent), 1, 5).astype(int)

    source_cost = {
        "Employee Referral": 1500,
        "Job Board": 2500,
        "Recruiting Agency": 7000,
        "Internal Transfer": 800,
        "Campus": 3000,
        "Company Website": 1200,
    }
    base_cost = np.array([source_cost[s] for s in source], dtype=float)
    cost = (base_cost * (1 + 0.18 * (job_level - 1)) * RNG.lognormal(0, 0.12, n)).round().astype(int)

    as_of = np.datetime64(config.AS_OF_DATE)
    jitter = RNG.integers(0, 365, size=n).astype("timedelta64[D]")
    hire_date = as_of - (years_at_company * 365).astype("timedelta64[D]") - jitter
    req_open_date = hire_date - ttf.astype("timedelta64[D]")

    out = pd.DataFrame(
        {
            "EmployeeNumber": emp["EmployeeNumber"].to_numpy(),
            "SourceChannel": source,
            "ReqOpenDate": np.datetime_as_string(req_open_date, unit="D"),
            "HireDate": np.datetime_as_string(hire_date, unit="D"),
            "TimeToFillDays": ttf,
            "RampUpDays": ramp,
            "HiringManagerSatisfaction": hm_sat,
            "RecruitingCost": cost,
        }
    )
    return out


def main() -> None:
    if config.IBM_CSV.exists():
        emp = pd.read_csv(config.IBM_CSV)
        base = "real IBM file"
    else:
        emp = synthesize_employees()
        emp.to_csv(config.EMPLOYEE_SAMPLE, index=False)
        base = f"synthetic sample -> {config.EMPLOYEE_SAMPLE.name}"

    recruitment = make_recruitment(emp)
    absence = make_absence(emp, recruitment)
    absence.to_csv(config.ABSENCE_CSV, index=False)
    recruitment.to_csv(config.RECRUITMENT_CSV, index=False)

    print(f"Employee base: {base} ({len(emp):,} employees)")
    print(f"Attrition rate: {(emp['Attrition'] == 'Yes').mean():.1%}")
    print(f"Absence events: {len(absence):,} -> {config.ABSENCE_CSV.name}")
    print(f"Recruitment records: {len(recruitment):,} -> {config.RECRUITMENT_CSV.name}")


if __name__ == "__main__":
    main()
