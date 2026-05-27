-- ============================================================================
-- Silver layer: a Kimball style dimensional model for workforce analytics.
--
-- Grain and design
--   dim_employee      one row per employee (current snapshot, SCD type 1)
--   dim_department    conformed dimension, surrogate keyed
--   dim_job_role      conformed dimension, surrogate keyed
--   dim_date          conformed monthly calendar spanning hire history to as of
--   fact_employment   one row per employee: tenure, pay, attrition (the turnover grain)
--   fact_absence      one row per absence spell (the absenteeism grain)
--   fact_recruitment  one row per hire: time to fill, ramp up, hiring satisfaction
--
-- The three fact tables share the conformed dimensions (a fact constellation),
-- which is what lets a single Power BI model slice turnover, absenteeism, and
-- quality of hire by the same department, role, and calendar.
--
-- {AS_OF} is replaced by the pipeline with the snapshot date from config.py.
-- ============================================================================

DROP TABLE IF EXISTS silver_fact_recruitment;
DROP TABLE IF EXISTS silver_fact_absence;
DROP TABLE IF EXISTS silver_fact_employment;
DROP TABLE IF EXISTS silver_dim_date;
DROP TABLE IF EXISTS silver_dim_job_role;
DROP TABLE IF EXISTS silver_dim_department;
DROP TABLE IF EXISTS silver_dim_employee;

-- ---------------------------------------------------------------------------
-- Conformed dimensions
-- ---------------------------------------------------------------------------
CREATE TABLE silver_dim_department (
    department_key   INTEGER PRIMARY KEY,
    department_name  TEXT UNIQUE
);
INSERT INTO silver_dim_department (department_name)
SELECT DISTINCT TRIM(Department) FROM bronze_employees
ORDER BY 1;

CREATE TABLE silver_dim_job_role (
    job_role_key   INTEGER PRIMARY KEY,
    job_role_name  TEXT UNIQUE
);
INSERT INTO silver_dim_job_role (job_role_name)
SELECT DISTINCT TRIM(JobRole) FROM bronze_employees
ORDER BY 1;

-- Monthly calendar built with a recursive CTE from the earliest hire to as of.
CREATE TABLE silver_dim_date (
    date_key     INTEGER PRIMARY KEY,   -- yyyymm, for example 202512
    month_start  TEXT,                  -- yyyy-mm-01
    year         INTEGER,
    month_num    INTEGER,
    month_name   TEXT,
    quarter      TEXT
);
WITH RECURSIVE months(d) AS (
    SELECT date((SELECT MIN(HireDate) FROM bronze_recruitment), 'start of month')
    UNION ALL
    SELECT date(d, '+1 month') FROM months
    WHERE d < date('{AS_OF}', 'start of month')
)
INSERT INTO silver_dim_date (date_key, month_start, year, month_num, month_name, quarter)
SELECT
    CAST(strftime('%Y%m', d) AS INTEGER),
    d,
    CAST(strftime('%Y', d) AS INTEGER),
    CAST(strftime('%m', d) AS INTEGER),
    CASE strftime('%m', d)
        WHEN '01' THEN 'Jan' WHEN '02' THEN 'Feb' WHEN '03' THEN 'Mar'
        WHEN '04' THEN 'Apr' WHEN '05' THEN 'May' WHEN '06' THEN 'Jun'
        WHEN '07' THEN 'Jul' WHEN '08' THEN 'Aug' WHEN '09' THEN 'Sep'
        WHEN '10' THEN 'Oct' WHEN '11' THEN 'Nov' WHEN '12' THEN 'Dec'
    END,
    'Q' || ((CAST(strftime('%m', d) AS INTEGER) - 1) / 3 + 1)
FROM months;

-- ---------------------------------------------------------------------------
-- dim_employee: demographics, job context, and the I-O Psychology constructs.
-- Surrogate FKs to department and role are resolved by joining on the names.
-- ---------------------------------------------------------------------------
CREATE TABLE silver_dim_employee (
    employee_key              INTEGER PRIMARY KEY,
    department_key            INTEGER,
    job_role_key              INTEGER,
    age                       INTEGER,
    age_band                  TEXT,
    gender                    TEXT,
    marital_status            TEXT,
    education                 INTEGER,
    education_field           TEXT,
    job_level                 INTEGER,
    business_travel           TEXT,
    distance_from_home        INTEGER,
    distance_band             TEXT,
    overtime                  INTEGER,
    num_companies_worked      INTEGER,
    stock_option_level        INTEGER,
    training_times_last_year  INTEGER,
    job_satisfaction          INTEGER,
    environment_satisfaction  INTEGER,
    relationship_satisfaction INTEGER,
    work_life_balance         INTEGER,
    job_involvement           INTEGER,
    performance_rating        INTEGER,
    percent_salary_hike       INTEGER,
    years_in_current_role     INTEGER,
    years_since_last_promotion INTEGER,
    years_with_curr_manager   INTEGER,
    FOREIGN KEY (department_key) REFERENCES silver_dim_department(department_key),
    FOREIGN KEY (job_role_key)   REFERENCES silver_dim_job_role(job_role_key)
);
INSERT INTO silver_dim_employee
SELECT
    e.EmployeeNumber,
    d.department_key,
    r.job_role_key,
    e.Age,
    CASE
        WHEN e.Age < 25 THEN '< 25'
        WHEN e.Age < 35 THEN '25-34'
        WHEN e.Age < 45 THEN '35-44'
        WHEN e.Age < 55 THEN '45-54'
        ELSE '55+'
    END,
    e.Gender,
    e.MaritalStatus,
    e.Education,
    e.EducationField,
    e.JobLevel,
    e.BusinessTravel,
    e.DistanceFromHome,
    CASE
        WHEN e.DistanceFromHome <= 5 THEN '0-5 km'
        WHEN e.DistanceFromHome <= 15 THEN '6-15 km'
        ELSE '16+ km'
    END,
    CASE WHEN e.OverTime = 'Yes' THEN 1 ELSE 0 END,
    e.NumCompaniesWorked,
    e.StockOptionLevel,
    e.TrainingTimesLastYear,
    e.JobSatisfaction,
    e.EnvironmentSatisfaction,
    e.RelationshipSatisfaction,
    e.WorkLifeBalance,
    e.JobInvolvement,
    e.PerformanceRating,
    e.PercentSalaryHike,
    e.YearsInCurrentRole,
    e.YearsSinceLastPromotion,
    e.YearsWithCurrManager
FROM bronze_employees e
JOIN silver_dim_department d ON d.department_name = TRIM(e.Department)
JOIN silver_dim_job_role  r ON r.job_role_name  = TRIM(e.JobRole);

-- ---------------------------------------------------------------------------
-- fact_employment: the turnover grain. Hire date comes from recruitment, the
-- termination date from the seeded stage table, tenure from date arithmetic.
-- ---------------------------------------------------------------------------
CREATE TABLE silver_fact_employment (
    employee_key       INTEGER PRIMARY KEY,
    department_key     INTEGER,
    job_role_key       INTEGER,
    hire_date          TEXT,
    hire_month_key     INTEGER,
    termination_date   TEXT,
    term_month_key     INTEGER,
    is_active          INTEGER,
    attrition_flag     INTEGER,
    tenure_days        INTEGER,
    tenure_years       REAL,
    tenure_band        TEXT,
    monthly_income     INTEGER,
    income_band        TEXT,
    performance_rating INTEGER,
    FOREIGN KEY (employee_key)   REFERENCES silver_dim_employee(employee_key),
    FOREIGN KEY (department_key) REFERENCES silver_dim_department(department_key),
    FOREIGN KEY (job_role_key)   REFERENCES silver_dim_job_role(job_role_key)
);
INSERT INTO silver_fact_employment
SELECT
    e.EmployeeNumber,
    d.department_key,
    jr.job_role_key,
    rec.HireDate,
    CAST(strftime('%Y%m', rec.HireDate) AS INTEGER),
    term.termination_date,
    CASE WHEN term.termination_date IS NOT NULL
         THEN CAST(strftime('%Y%m', term.termination_date) AS INTEGER) END,
    CASE WHEN e.Attrition = 'Yes' THEN 0 ELSE 1 END,
    CASE WHEN e.Attrition = 'Yes' THEN 1 ELSE 0 END,
    CAST(julianday(COALESCE(term.termination_date, '{AS_OF}')) - julianday(rec.HireDate) AS INTEGER),
    ROUND((julianday(COALESCE(term.termination_date, '{AS_OF}')) - julianday(rec.HireDate)) / 365.25, 2),
    CASE
        WHEN (julianday(COALESCE(term.termination_date, '{AS_OF}')) - julianday(rec.HireDate)) / 365.25 < 1 THEN '< 1 yr'
        WHEN (julianday(COALESCE(term.termination_date, '{AS_OF}')) - julianday(rec.HireDate)) / 365.25 < 3 THEN '1-2 yrs'
        WHEN (julianday(COALESCE(term.termination_date, '{AS_OF}')) - julianday(rec.HireDate)) / 365.25 < 6 THEN '3-5 yrs'
        WHEN (julianday(COALESCE(term.termination_date, '{AS_OF}')) - julianday(rec.HireDate)) / 365.25 < 11 THEN '6-10 yrs'
        ELSE '10+ yrs'
    END,
    e.MonthlyIncome,
    CASE
        WHEN e.MonthlyIncome < 3000 THEN '< 3k'
        WHEN e.MonthlyIncome < 6000 THEN '3-6k'
        WHEN e.MonthlyIncome < 10000 THEN '6-10k'
        WHEN e.MonthlyIncome < 15000 THEN '10-15k'
        ELSE '15k+'
    END,
    e.PerformanceRating
FROM bronze_employees e
JOIN silver_dim_department d  ON d.department_name = TRIM(e.Department)
JOIN silver_dim_job_role  jr ON jr.job_role_name  = TRIM(e.JobRole)
JOIN bronze_recruitment   rec ON rec.EmployeeNumber = e.EmployeeNumber
LEFT JOIN stage_termination term ON term.EmployeeNumber = e.EmployeeNumber;

-- ---------------------------------------------------------------------------
-- fact_absence: one row per absence spell. reason_code is a degenerate dimension.
-- ---------------------------------------------------------------------------
CREATE TABLE silver_fact_absence (
    absence_key       INTEGER PRIMARY KEY,
    employee_key      INTEGER,
    absence_date      TEXT,
    absence_month_key INTEGER,
    absence_hours     REAL,
    absence_days      INTEGER,
    reason_code       TEXT,
    FOREIGN KEY (employee_key) REFERENCES silver_dim_employee(employee_key)
);
INSERT INTO silver_fact_absence
SELECT
    a.AbsenceID,
    a.EmployeeNumber,
    a.AbsenceDate,
    CAST(strftime('%Y%m', a.AbsenceDate) AS INTEGER),
    a.AbsenceHours,
    a.AbsenceDays,
    a.ReasonCode
FROM bronze_absence a;

-- ---------------------------------------------------------------------------
-- fact_recruitment: one row per hire. source_channel is a degenerate dimension.
-- ---------------------------------------------------------------------------
CREATE TABLE silver_fact_recruitment (
    recruitment_key             INTEGER PRIMARY KEY,
    employee_key                INTEGER,
    source_channel              TEXT,
    req_open_date               TEXT,
    hire_date                   TEXT,
    hire_month_key              INTEGER,
    time_to_fill_days           INTEGER,
    ramp_up_days                INTEGER,
    hiring_manager_satisfaction INTEGER,
    recruiting_cost             INTEGER,
    FOREIGN KEY (employee_key) REFERENCES silver_dim_employee(employee_key)
);
INSERT INTO silver_fact_recruitment
SELECT
    ROW_NUMBER() OVER (ORDER BY rec.EmployeeNumber),
    rec.EmployeeNumber,
    rec.SourceChannel,
    rec.ReqOpenDate,
    rec.HireDate,
    CAST(strftime('%Y%m', rec.HireDate) AS INTEGER),
    rec.TimeToFillDays,
    rec.RampUpDays,
    rec.HiringManagerSatisfaction,
    rec.RecruitingCost
FROM bronze_recruitment rec;

CREATE INDEX idx_absence_emp ON silver_fact_absence(employee_key);
CREATE INDEX idx_absence_month ON silver_fact_absence(absence_month_key);
CREATE INDEX idx_employment_dept ON silver_fact_employment(department_key);
