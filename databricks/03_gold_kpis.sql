-- Databricks notebook source
-- MAGIC %md
-- MAGIC # Gold layer: people analytics measures (Databricks SQL)
-- MAGIC
-- MAGIC Mirrors `sql/02_kpi_queries.sql` in Spark SQL. The main differences from the
-- MAGIC local SQLite version are `least`/`greatest` for scalar min and max and
-- MAGIC `datediff` for day arithmetic. The snapshot date and the scheduled hours per
-- MAGIC calendar day are written inline and match `config.py`.

-- COMMAND ----------

-- Free Edition ships the 'workspace' catalog. Change this if your catalog differs.
USE CATALOG workspace;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## gold.employee_analysis (one big table at employee grain)

-- COMMAND ----------

CREATE OR REPLACE TABLE gold.employee_analysis AS
WITH absence_agg AS (
    SELECT employee_key,
           sum(absence_hours)  AS absence_hours,
           sum(absence_days)   AS absence_days,
           count(*)            AS absence_spells
    FROM silver.fact_absence
    GROUP BY employee_key
),
base AS (
    SELECT
        f.employee_key, d.department_name, jr.job_role_name,
        e.age, e.age_band, e.gender, e.marital_status, e.education, e.education_field,
        e.job_level, e.business_travel, e.distance_from_home, e.distance_band,
        e.overtime, e.num_companies_worked, e.stock_option_level, e.training_times_last_year,
        e.job_satisfaction, e.environment_satisfaction, e.relationship_satisfaction,
        e.work_life_balance, e.job_involvement,
        f.performance_rating, e.percent_salary_hike,
        e.years_in_current_role, e.years_since_last_promotion, e.years_with_curr_manager,
        f.hire_date, f.termination_date, f.is_active, f.attrition_flag,
        f.tenure_days, f.tenure_years, f.tenure_band, f.monthly_income, f.income_band,
        r.source_channel, r.time_to_fill_days, r.ramp_up_days,
        r.hiring_manager_satisfaction, r.recruiting_cost,
        least(365.0, datediff(date('2025-12-31'), f.hire_date)) AS exposure_days
    FROM silver.fact_employment f
    JOIN silver.dim_employee    e  ON e.employee_key   = f.employee_key
    JOIN silver.dim_department  d  ON d.department_key = f.department_key
    JOIN silver.dim_job_role    jr ON jr.job_role_key  = f.job_role_key
    JOIN silver.fact_recruitment r ON r.employee_key   = f.employee_key
),
scored AS (
    SELECT
        b.*,
        coalesce(a.absence_hours, 0)  AS absence_hours,
        coalesce(a.absence_days, 0)   AS absence_days,
        coalesce(a.absence_spells, 0) AS absence_spells,
        round(b.exposure_days * 5.338, 1) AS scheduled_hours,   -- 162.5 scheduled hrs/month / 30.44 days
        round(100.0 * coalesce(a.absence_hours, 0) / nullif(b.exposure_days * 5.338, 0), 2) AS absenteeism_rate_pct,
        coalesce(a.absence_spells, 0) * coalesce(a.absence_spells, 0) * coalesce(a.absence_days, 0) AS bradford_factor,
        round(100.0 * (b.performance_rating - 1) / 3.0, 1) AS performance_score,
        CASE WHEN b.tenure_days >= 365 THEN 100.0
             WHEN b.is_active = 1 THEN NULL
             WHEN b.tenure_days >= 182 THEN 50.0 ELSE 0.0 END AS retention_score,
        round(100.0 * (1 - least(1.0, greatest(0.0, (b.ramp_up_days - 30.0) / 150.0))), 1) AS ramp_score,
        round(100.0 * (b.hiring_manager_satisfaction - 1) / 4.0, 1) AS hm_satisfaction_score
    FROM base b
    LEFT JOIN absence_agg a ON a.employee_key = b.employee_key
)
SELECT
    s.*,
    round(
        (s.performance_score + s.ramp_score + s.hm_satisfaction_score + coalesce(s.retention_score, 0))
        / (3 + CASE WHEN s.retention_score IS NULL THEN 0 ELSE 1 END), 1
    ) AS quality_of_hire
FROM scored s;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Turnover by segment

-- COMMAND ----------

CREATE OR REPLACE TABLE gold.kpi_turnover AS
SELECT segment_type, segment, headcount_current, separations,
       round(headcount_current + separations / 2.0, 1) AS avg_headcount,
       round(100.0 * separations / nullif(headcount_current + separations / 2.0, 0), 1) AS turnover_pct
FROM (
    SELECT 'Overall' AS segment_type, 'All employees' AS segment,
           sum(is_active) AS headcount_current, sum(attrition_flag) AS separations FROM gold.employee_analysis
    UNION ALL SELECT 'Department', department_name, sum(is_active), sum(attrition_flag) FROM gold.employee_analysis GROUP BY department_name
    UNION ALL SELECT 'Job role', job_role_name, sum(is_active), sum(attrition_flag) FROM gold.employee_analysis GROUP BY job_role_name
    UNION ALL SELECT 'Tenure band', tenure_band, sum(is_active), sum(attrition_flag) FROM gold.employee_analysis GROUP BY tenure_band
    UNION ALL SELECT 'Age band', age_band, sum(is_active), sum(attrition_flag) FROM gold.employee_analysis GROUP BY age_band
    UNION ALL SELECT 'Overtime', CASE WHEN overtime = 1 THEN 'Works overtime' ELSE 'No overtime' END,
           sum(is_active), sum(attrition_flag) FROM gold.employee_analysis GROUP BY overtime
);

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Absenteeism, by reason, and by month

-- COMMAND ----------

CREATE OR REPLACE TABLE gold.kpi_absenteeism AS
SELECT segment_type, segment, employees,
       round(absence_hours, 0) AS absence_hours,
       round(scheduled_hours, 0) AS scheduled_hours,
       round(100.0 * absence_hours / nullif(scheduled_hours, 0), 2) AS absenteeism_rate_pct,
       round(avg_absence_days, 2) AS avg_absence_days
FROM (
    SELECT 'Overall' AS segment_type, 'All employees' AS segment, count(*) AS employees,
           sum(absence_hours) AS absence_hours, sum(scheduled_hours) AS scheduled_hours, avg(absence_days) AS avg_absence_days
    FROM gold.employee_analysis
    UNION ALL SELECT 'Department', department_name, count(*), sum(absence_hours), sum(scheduled_hours), avg(absence_days)
    FROM gold.employee_analysis GROUP BY department_name
    UNION ALL SELECT 'Overtime', CASE WHEN overtime = 1 THEN 'Works overtime' ELSE 'No overtime' END,
           count(*), sum(absence_hours), sum(scheduled_hours), avg(absence_days)
    FROM gold.employee_analysis GROUP BY overtime
    UNION ALL SELECT 'Work-life balance', concat('WLB rating ', cast(work_life_balance AS STRING)),
           count(*), sum(absence_hours), sum(scheduled_hours), avg(absence_days)
    FROM gold.employee_analysis GROUP BY work_life_balance
);

-- COMMAND ----------

CREATE OR REPLACE TABLE gold.absence_by_reason AS
SELECT reason_code, count(*) AS spells, round(sum(absence_hours), 0) AS absence_hours,
       round(100.0 * sum(absence_hours) / (SELECT sum(absence_hours) FROM silver.fact_absence), 1) AS pct_of_hours
FROM silver.fact_absence GROUP BY reason_code ORDER BY absence_hours DESC;

-- COMMAND ----------

CREATE OR REPLACE TABLE gold.absence_monthly AS
SELECT dd.date_key, dd.month_start, dd.year, dd.month_name,
       count(*) AS spells, round(sum(fa.absence_hours), 0) AS absence_hours
FROM silver.fact_absence fa
JOIN silver.dim_date dd ON dd.date_key = fa.absence_month_key
GROUP BY dd.date_key, dd.month_start, dd.year, dd.month_name
ORDER BY dd.date_key;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Quality of Hire by source channel

-- COMMAND ----------

CREATE OR REPLACE TABLE gold.kpi_quality_of_hire AS
SELECT 'Overall' AS segment_type, 'All hires' AS segment, count(*) AS hires,
       round(avg(quality_of_hire), 1) AS quality_of_hire,
       round(avg(performance_score), 1) AS performance_score,
       round(avg(retention_score), 1) AS retention_score,
       round(avg(ramp_score), 1) AS ramp_score,
       round(avg(hm_satisfaction_score), 1) AS hm_satisfaction_score,
       round(avg(time_to_fill_days), 0) AS avg_time_to_fill,
       round(avg(recruiting_cost), 0) AS avg_recruiting_cost
FROM gold.employee_analysis
UNION ALL
SELECT 'Source channel', source_channel, count(*),
       round(avg(quality_of_hire), 1), round(avg(performance_score), 1), round(avg(retention_score), 1),
       round(avg(ramp_score), 1), round(avg(hm_satisfaction_score), 1),
       round(avg(time_to_fill_days), 0), round(avg(recruiting_cost), 0)
FROM gold.employee_analysis GROUP BY source_channel
ORDER BY segment_type, quality_of_hire DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Monthly headcount and movement (non equi join on the calendar)

-- COMMAND ----------

CREATE OR REPLACE TABLE gold.headcount_monthly AS
SELECT *, round(100.0 * separations / nullif(active_headcount, 0), 2) AS monthly_turnover_pct
FROM (
    SELECT dd.date_key, dd.month_start, dd.year, dd.month_name,
           sum(CASE WHEN f.hire_month_key <= dd.date_key
                     AND (f.term_month_key IS NULL OR f.term_month_key > dd.date_key) THEN 1 ELSE 0 END) AS active_headcount,
           sum(CASE WHEN f.hire_month_key = dd.date_key THEN 1 ELSE 0 END) AS hires,
           sum(CASE WHEN f.term_month_key = dd.date_key THEN 1 ELSE 0 END) AS separations
    FROM silver.dim_date dd
    CROSS JOIN silver.fact_employment f
    WHERE dd.date_key >= CAST(date_format(add_months(date('2025-12-31'), -23), 'yyyyMM') AS INT)
    GROUP BY dd.date_key, dd.month_start, dd.year, dd.month_name
);

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Attrition rate by I-O construct level

-- COMMAND ----------

CREATE OR REPLACE TABLE gold.attrition_drivers AS
SELECT driver, level, headcount, leavers, round(100.0 * leavers / nullif(headcount, 0), 1) AS attrition_pct
FROM (
    SELECT 'Job satisfaction' AS driver, concat('Level ', cast(job_satisfaction AS STRING)) AS level, count(*) AS headcount, sum(attrition_flag) AS leavers FROM gold.employee_analysis GROUP BY job_satisfaction
    UNION ALL SELECT 'Environment satisfaction', concat('Level ', cast(environment_satisfaction AS STRING)), count(*), sum(attrition_flag) FROM gold.employee_analysis GROUP BY environment_satisfaction
    UNION ALL SELECT 'Work-life balance', concat('Level ', cast(work_life_balance AS STRING)), count(*), sum(attrition_flag) FROM gold.employee_analysis GROUP BY work_life_balance
    UNION ALL SELECT 'Job involvement', concat('Level ', cast(job_involvement AS STRING)), count(*), sum(attrition_flag) FROM gold.employee_analysis GROUP BY job_involvement
    UNION ALL SELECT 'Overtime', CASE WHEN overtime = 1 THEN 'Works overtime' ELSE 'No overtime' END, count(*), sum(attrition_flag) FROM gold.employee_analysis GROUP BY overtime
    UNION ALL SELECT 'Business travel', business_travel, count(*), sum(attrition_flag) FROM gold.employee_analysis GROUP BY business_travel
    UNION ALL SELECT 'Marital status', marital_status, count(*), sum(attrition_flag) FROM gold.employee_analysis GROUP BY marital_status
    UNION ALL SELECT 'Stock option level', concat('Level ', cast(stock_option_level AS STRING)), count(*), sum(attrition_flag) FROM gold.employee_analysis GROUP BY stock_option_level
)
ORDER BY driver, level;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC The gold tables are ready. Connect Power BI to this catalog with Partner
-- MAGIC Connect and point the model at `gold.employee_analysis`.
