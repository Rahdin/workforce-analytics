"""Central paths, constants, and business parameters for the people analytics pipeline."""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
DASHBOARD = ROOT / "dashboard"
SQL_DIR = ROOT / "sql"

# Core source file. This is the real IBM HR Analytics Employee Attrition dataset
# (download once from Kaggle, see README "Reproduce"). If it is absent, the
# pipeline falls back to a faithful synthetic sample written by make_sample_data.py.
IBM_CSV = DATA_RAW / "WA_Fn-UseC_-HR-Employee-Attrition.csv"
EMPLOYEE_SAMPLE = DATA_RAW / "employees_sample.csv"
ABSENCE_CSV = DATA_RAW / "absence_events.csv"
RECRUITMENT_CSV = DATA_RAW / "recruitment.csv"


def employee_source():
    """Prefer the real IBM file; fall back to the generated sample if absent."""
    return IBM_CSV if IBM_CSV.exists() else EMPLOYEE_SAMPLE

DB_PATH = DATA_PROCESSED / "warehouse.db"

# Reproducibility
RANDOM_SEED = 42

# Snapshot the cross sectional IBM file is treated as. Hire and termination dates
# are derived relative to this date so the warehouse has a usable time dimension.
AS_OF_DATE = date(2025, 12, 31)
ANALYSIS_WINDOW_MONTHS = 12

# Absenteeism rate denominator. A standard full time month is about 21.67 working
# days; we model 7.5 scheduled hours per working day in line with the posting's
# stated 37.5 hour week.
SCHEDULED_HOURS_PER_DAY = 7.5
WORKING_DAYS_PER_MONTH = 21.67
SCHEDULED_HOURS_PER_MONTH = SCHEDULED_HOURS_PER_DAY * WORKING_DAYS_PER_MONTH

# Quality of Hire is a transparent composite of four equally weighted, normalised
# components, each scaled to 0..100. This mirrors the common SHRM style index of
# performance, retention, ramp up speed, and hiring manager satisfaction.
QOH_COMPONENTS = ("performance_score", "retention_score", "ramp_score", "hm_satisfaction_score")

# First year retention horizon used by Quality of Hire and early attrition cuts.
EARLY_TENURE_DAYS = 365

# Likert style I-O Psychology constructs in the IBM schema (1 = low, 4 = high).
# These anchor the attrition research study.
SATISFACTION_FIELDS = (
    "JobSatisfaction",
    "EnvironmentSatisfaction",
    "RelationshipSatisfaction",
    "WorkLifeBalance",
    "JobInvolvement",
)

# Consistent figure styling.
BRAND_NAVY = "#1f2a44"
BRAND_TEAL = "#2a9d8f"
BRAND_AMBER = "#e9c46a"
BRAND_CORAL = "#e76f51"
BRAND_GREY = "#8d99ae"

for d in (DATA_RAW, DATA_PROCESSED, FIGURES, DASHBOARD):
    d.mkdir(parents=True, exist_ok=True)
