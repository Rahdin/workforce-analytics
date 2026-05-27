# Databricks notebook source
# MAGIC %md
# MAGIC # Silver dimensional model
# MAGIC
# MAGIC Builds the conformed dimensions and the three fact tables as Delta tables,
# MAGIC mirroring `sql/01_star_schema.sql` from the local project in Spark SQL.
# MAGIC Surrogate keys come from window functions, the calendar from `sequence`, and
# MAGIC termination dates from a deterministic hash so the result is reproducible
# MAGIC without an external random seed.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("as_of", "2025-12-31")
c = dbutils.widgets.get("catalog")
as_of = dbutils.widgets.get("as_of")
print(f"catalog={c}  as_of={as_of}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Conformed dimensions

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {c}.silver.dim_department AS
SELECT ROW_NUMBER() OVER (ORDER BY department_name) AS department_key, department_name
FROM (SELECT DISTINCT trim(Department) AS department_name FROM {c}.bronze.employees)
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {c}.silver.dim_job_role AS
SELECT ROW_NUMBER() OVER (ORDER BY job_role_name) AS job_role_key, job_role_name
FROM (SELECT DISTINCT trim(JobRole) AS job_role_name FROM {c}.bronze.employees)
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {c}.silver.dim_date AS
WITH bounds AS (
    SELECT date_trunc('MM', min(to_date(HireDate))) AS lo,
           date_trunc('MM', date('{as_of}'))        AS hi
    FROM {c}.bronze.recruitment
),
months AS (
    SELECT explode(sequence(lo, hi, interval 1 month)) AS m FROM bounds
)
SELECT
    CAST(date_format(m, 'yyyyMM') AS INT) AS date_key,
    CAST(m AS DATE)                        AS month_start,
    year(m)                                AS year,
    month(m)                               AS month_num,
    date_format(m, 'MMM')                  AS month_name,
    concat('Q', CAST(quarter(m) AS STRING)) AS quarter
FROM months
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## dim_employee with the I-O constructs and surrogate foreign keys

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {c}.silver.dim_employee AS
SELECT
    e.EmployeeNumber AS employee_key,
    d.department_key,
    jr.job_role_key,
    e.Age AS age,
    CASE WHEN e.Age < 25 THEN '< 25' WHEN e.Age < 35 THEN '25-34'
         WHEN e.Age < 45 THEN '35-44' WHEN e.Age < 55 THEN '45-54' ELSE '55+' END AS age_band,
    e.Gender AS gender,
    e.MaritalStatus AS marital_status,
    e.Education AS education,
    e.EducationField AS education_field,
    e.JobLevel AS job_level,
    e.BusinessTravel AS business_travel,
    e.DistanceFromHome AS distance_from_home,
    CASE WHEN e.DistanceFromHome <= 5 THEN '0-5 km'
         WHEN e.DistanceFromHome <= 15 THEN '6-15 km' ELSE '16+ km' END AS distance_band,
    CASE WHEN e.OverTime = 'Yes' THEN 1 ELSE 0 END AS overtime,
    e.NumCompaniesWorked AS num_companies_worked,
    e.StockOptionLevel AS stock_option_level,
    e.TrainingTimesLastYear AS training_times_last_year,
    e.JobSatisfaction AS job_satisfaction,
    e.EnvironmentSatisfaction AS environment_satisfaction,
    e.RelationshipSatisfaction AS relationship_satisfaction,
    e.WorkLifeBalance AS work_life_balance,
    e.JobInvolvement AS job_involvement,
    e.PerformanceRating AS performance_rating,
    e.PercentSalaryHike AS percent_salary_hike,
    e.YearsInCurrentRole AS years_in_current_role,
    e.YearsSinceLastPromotion AS years_since_last_promotion,
    e.YearsWithCurrManager AS years_with_curr_manager
FROM {c}.bronze.employees e
JOIN {c}.silver.dim_department d ON d.department_name = trim(e.Department)
JOIN {c}.silver.dim_job_role  jr ON jr.job_role_name  = trim(e.JobRole)
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## fact_employment (the turnover grain)
# MAGIC Termination dates are placed inside the trailing year with a deterministic
# MAGIC offset hashed from the employee number, never before the hire date.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {c}.silver.fact_employment AS
WITH base AS (
    SELECT
        e.EmployeeNumber AS employee_key,
        d.department_key,
        jr.job_role_key,
        to_date(rec.HireDate) AS hire_date,
        CASE WHEN e.Attrition = 'Yes' THEN
            greatest(
                date_add(to_date(rec.HireDate), 14),
                date_sub(date('{as_of}'), CAST(abs(hash(e.EmployeeNumber)) % 365 AS INT))
            )
        END AS termination_date,
        CASE WHEN e.Attrition = 'Yes' THEN 1 ELSE 0 END AS attrition_flag,
        e.MonthlyIncome AS monthly_income,
        e.PerformanceRating AS performance_rating
    FROM {c}.bronze.employees e
    JOIN {c}.silver.dim_department d  ON d.department_name = trim(e.Department)
    JOIN {c}.silver.dim_job_role  jr ON jr.job_role_name  = trim(e.JobRole)
    JOIN {c}.bronze.recruitment   rec ON rec.EmployeeNumber = e.EmployeeNumber
)
SELECT
    *,
    CAST(date_format(hire_date, 'yyyyMM') AS INT) AS hire_month_key,
    CASE WHEN termination_date IS NOT NULL
         THEN CAST(date_format(termination_date, 'yyyyMM') AS INT) END AS term_month_key,
    CASE WHEN attrition_flag = 1 THEN 0 ELSE 1 END AS is_active,
    datediff(coalesce(termination_date, date('{as_of}')), hire_date) AS tenure_days,
    round(datediff(coalesce(termination_date, date('{as_of}')), hire_date) / 365.25, 2) AS tenure_years,
    CASE
        WHEN datediff(coalesce(termination_date, date('{as_of}')), hire_date) / 365.25 < 1 THEN '< 1 yr'
        WHEN datediff(coalesce(termination_date, date('{as_of}')), hire_date) / 365.25 < 3 THEN '1-2 yrs'
        WHEN datediff(coalesce(termination_date, date('{as_of}')), hire_date) / 365.25 < 6 THEN '3-5 yrs'
        WHEN datediff(coalesce(termination_date, date('{as_of}')), hire_date) / 365.25 < 11 THEN '6-10 yrs'
        ELSE '10+ yrs'
    END AS tenure_band,
    CASE
        WHEN monthly_income < 3000 THEN '< 3k' WHEN monthly_income < 6000 THEN '3-6k'
        WHEN monthly_income < 10000 THEN '6-10k' WHEN monthly_income < 15000 THEN '10-15k'
        ELSE '15k+' END AS income_band
FROM base
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## fact_absence and fact_recruitment

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {c}.silver.fact_absence AS
SELECT
    AbsenceID AS absence_key,
    EmployeeNumber AS employee_key,
    to_date(AbsenceDate) AS absence_date,
    CAST(date_format(to_date(AbsenceDate), 'yyyyMM') AS INT) AS absence_month_key,
    AbsenceHours AS absence_hours,
    AbsenceDays AS absence_days,
    ReasonCode AS reason_code
FROM {c}.bronze.absence
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {c}.silver.fact_recruitment AS
SELECT
    ROW_NUMBER() OVER (ORDER BY EmployeeNumber) AS recruitment_key,
    EmployeeNumber AS employee_key,
    SourceChannel AS source_channel,
    to_date(ReqOpenDate) AS req_open_date,
    to_date(HireDate) AS hire_date,
    CAST(date_format(to_date(HireDate), 'yyyyMM') AS INT) AS hire_month_key,
    TimeToFillDays AS time_to_fill_days,
    RampUpDays AS ramp_up_days,
    HiringManagerSatisfaction AS hiring_manager_satisfaction,
    RecruitingCost AS recruiting_cost
FROM {c}.bronze.recruitment
""")

# COMMAND ----------

display(spark.sql(f"""
SELECT d.department_name,
       count(*) AS headcount,
       sum(f.attrition_flag) AS leavers,
       round(100.0 * avg(f.attrition_flag), 1) AS attrition_pct
FROM {c}.silver.fact_employment f
JOIN {c}.silver.dim_department d ON d.department_key = f.department_key
GROUP BY d.department_name
ORDER BY attrition_pct DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC Silver is built. Continue with `03_gold_kpis` (Databricks SQL).
