-- ============================================================================
-- Gold layer: business ready marts and the standard people analytics measures.
--
-- gold_employee_analysis     one big table (employee grain) joining all facts
--                            and dimensions, plus per employee absenteeism and
--                            Quality of Hire components. This is the model Power
--                            BI imports and the statistics study reads.
-- gold_kpi_turnover          Turnover by segment
-- gold_kpi_absenteeism       Absenteeism Rate by segment
-- gold_absence_by_reason     Absence hours and spells by reason code
-- gold_absence_monthly       Absence trend by month
-- gold_kpi_quality_of_hire   Quality of Hire and Time to Fill by source channel
-- gold_headcount_monthly     Headcount, hires, separations, turnover by month
-- gold_attrition_drivers     Attrition rate by I-O construct level (for charts)
--
-- Placeholders {AS_OF}, {WINDOW_DAYS}, {HOURS_PER_CAL_DAY} are injected by kpis.py.
-- ============================================================================

DROP TABLE IF EXISTS gold_employee_analysis;
CREATE TABLE gold_employee_analysis AS
WITH absence_agg AS (
    SELECT employee_key,
           SUM(absence_hours)  AS absence_hours,
           SUM(absence_days)   AS absence_days,
           COUNT(*)            AS absence_spells
    FROM silver_fact_absence
    GROUP BY employee_key
),
base AS (
    SELECT
        f.employee_key,
        d.department_name,
        jr.job_role_name,
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
        MIN(CAST({WINDOW_DAYS} AS REAL), julianday('{AS_OF}') - julianday(f.hire_date)) AS exposure_days
    FROM silver_fact_employment f
    JOIN silver_dim_employee    e  ON e.employee_key   = f.employee_key
    JOIN silver_dim_department  d  ON d.department_key = f.department_key
    JOIN silver_dim_job_role    jr ON jr.job_role_key  = f.job_role_key
    JOIN silver_fact_recruitment r ON r.employee_key   = f.employee_key
),
scored AS (
    SELECT
        b.*,
        COALESCE(a.absence_hours, 0)  AS absence_hours,
        COALESCE(a.absence_days, 0)   AS absence_days,
        COALESCE(a.absence_spells, 0) AS absence_spells,
        ROUND(b.exposure_days * {HOURS_PER_CAL_DAY}, 1) AS scheduled_hours,
        ROUND(100.0 * COALESCE(a.absence_hours, 0)
              / NULLIF(b.exposure_days * {HOURS_PER_CAL_DAY}, 0), 2) AS absenteeism_rate_pct,
        COALESCE(a.absence_spells, 0) * COALESCE(a.absence_spells, 0)
              * COALESCE(a.absence_days, 0) AS bradford_factor,
        ROUND(100.0 * (b.performance_rating - 1) / 3.0, 1) AS performance_score,
        CASE
            WHEN b.tenure_days >= {EARLY_TENURE_DAYS} THEN 100.0
            WHEN b.is_active = 1 THEN NULL                       -- under a year, not yet assessable
            WHEN b.tenure_days >= ({EARLY_TENURE_DAYS} / 2) THEN 50.0
            ELSE 0.0
        END AS retention_score,
        ROUND(100.0 * (1 - MIN(1.0, MAX(0.0, (b.ramp_up_days - 30.0) / 150.0))), 1) AS ramp_score,
        ROUND(100.0 * (b.hiring_manager_satisfaction - 1) / 4.0, 1) AS hm_satisfaction_score
    FROM base b
    LEFT JOIN absence_agg a ON a.employee_key = b.employee_key
)
SELECT
    s.*,
    ROUND(
        (s.performance_score + s.ramp_score + s.hm_satisfaction_score + COALESCE(s.retention_score, 0))
        / (3 + CASE WHEN s.retention_score IS NULL THEN 0 ELSE 1 END),
    1) AS quality_of_hire
FROM scored s;

-- ---------------------------------------------------------------------------
-- Turnover by segment. Average headcount approximates the trailing year as
-- current active heads plus half of the leavers who were present part of the year.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS gold_kpi_turnover;
CREATE TABLE gold_kpi_turnover AS
SELECT
    segment_type,
    segment,
    headcount_current,
    separations,
    ROUND(headcount_current + separations / 2.0, 1) AS avg_headcount,
    ROUND(100.0 * separations / NULLIF(headcount_current + separations / 2.0, 0), 1) AS turnover_pct
FROM (
    SELECT 'Overall' AS segment_type, 'All employees' AS segment,
           SUM(is_active) AS headcount_current, SUM(attrition_flag) AS separations
    FROM gold_employee_analysis
    UNION ALL
    SELECT 'Department', department_name, SUM(is_active), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY department_name
    UNION ALL
    SELECT 'Job role', job_role_name, SUM(is_active), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY job_role_name
    UNION ALL
    SELECT 'Tenure band', tenure_band, SUM(is_active), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY tenure_band
    UNION ALL
    SELECT 'Age band', age_band, SUM(is_active), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY age_band
    UNION ALL
    SELECT 'Overtime', CASE WHEN overtime = 1 THEN 'Works overtime' ELSE 'No overtime' END,
           SUM(is_active), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY overtime
);

-- ---------------------------------------------------------------------------
-- Absenteeism Rate by segment (absent hours over scheduled hours).
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS gold_kpi_absenteeism;
CREATE TABLE gold_kpi_absenteeism AS
SELECT
    segment_type,
    segment,
    employees,
    ROUND(absence_hours, 0)   AS absence_hours,
    ROUND(scheduled_hours, 0) AS scheduled_hours,
    ROUND(100.0 * absence_hours / NULLIF(scheduled_hours, 0), 2) AS absenteeism_rate_pct,
    ROUND(avg_absence_days, 2) AS avg_absence_days
FROM (
    SELECT 'Overall' AS segment_type, 'All employees' AS segment,
           COUNT(*) AS employees, SUM(absence_hours) AS absence_hours,
           SUM(scheduled_hours) AS scheduled_hours, AVG(absence_days) AS avg_absence_days
    FROM gold_employee_analysis
    UNION ALL
    SELECT 'Department', department_name, COUNT(*), SUM(absence_hours),
           SUM(scheduled_hours), AVG(absence_days)
    FROM gold_employee_analysis GROUP BY department_name
    UNION ALL
    SELECT 'Overtime', CASE WHEN overtime = 1 THEN 'Works overtime' ELSE 'No overtime' END,
           COUNT(*), SUM(absence_hours), SUM(scheduled_hours), AVG(absence_days)
    FROM gold_employee_analysis GROUP BY overtime
    UNION ALL
    SELECT 'Work-life balance', 'WLB rating ' || work_life_balance, COUNT(*), SUM(absence_hours),
           SUM(scheduled_hours), AVG(absence_days)
    FROM gold_employee_analysis GROUP BY work_life_balance
);

DROP TABLE IF EXISTS gold_absence_by_reason;
CREATE TABLE gold_absence_by_reason AS
SELECT
    reason_code,
    COUNT(*)                AS spells,
    ROUND(SUM(absence_hours), 0) AS absence_hours,
    ROUND(100.0 * SUM(absence_hours) / (SELECT SUM(absence_hours) FROM silver_fact_absence), 1) AS pct_of_hours
FROM silver_fact_absence
GROUP BY reason_code
ORDER BY absence_hours DESC;

DROP TABLE IF EXISTS gold_absence_monthly;
CREATE TABLE gold_absence_monthly AS
SELECT
    dd.date_key,
    dd.month_start,
    dd.year,
    dd.month_name,
    COUNT(*)                     AS spells,
    ROUND(SUM(fa.absence_hours), 0) AS absence_hours
FROM silver_fact_absence fa
JOIN silver_dim_date dd ON dd.date_key = fa.absence_month_key
GROUP BY dd.date_key, dd.month_start, dd.year, dd.month_name
ORDER BY dd.date_key;

-- ---------------------------------------------------------------------------
-- Quality of Hire and Time to Fill by recruiting source channel.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS gold_kpi_quality_of_hire;
CREATE TABLE gold_kpi_quality_of_hire AS
SELECT 'Overall' AS segment_type, 'All hires' AS segment,
       COUNT(*) AS hires,
       ROUND(AVG(quality_of_hire), 1)       AS quality_of_hire,
       ROUND(AVG(performance_score), 1)     AS performance_score,
       ROUND(AVG(retention_score), 1)       AS retention_score,
       ROUND(AVG(ramp_score), 1)            AS ramp_score,
       ROUND(AVG(hm_satisfaction_score), 1) AS hm_satisfaction_score,
       ROUND(AVG(time_to_fill_days), 0)     AS avg_time_to_fill,
       ROUND(AVG(recruiting_cost), 0)       AS avg_recruiting_cost
FROM gold_employee_analysis
UNION ALL
SELECT 'Source channel', source_channel,
       COUNT(*),
       ROUND(AVG(quality_of_hire), 1),
       ROUND(AVG(performance_score), 1),
       ROUND(AVG(retention_score), 1),
       ROUND(AVG(ramp_score), 1),
       ROUND(AVG(hm_satisfaction_score), 1),
       ROUND(AVG(time_to_fill_days), 0),
       ROUND(AVG(recruiting_cost), 0)
FROM gold_employee_analysis
GROUP BY source_channel
ORDER BY segment_type, quality_of_hire DESC;

-- ---------------------------------------------------------------------------
-- Monthly workforce movement over the trailing two years. The headcount uses a
-- non equi join: an employee is active in a month if hired on or before it and
-- not yet terminated.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS gold_headcount_monthly;
CREATE TABLE gold_headcount_monthly AS
SELECT *,
       ROUND(100.0 * separations / NULLIF(active_headcount, 0), 2) AS monthly_turnover_pct
FROM (
    SELECT
        dd.date_key,
        dd.month_start,
        dd.year,
        dd.month_name,
        SUM(CASE WHEN f.hire_month_key <= dd.date_key
                  AND (f.term_month_key IS NULL OR f.term_month_key > dd.date_key)
                 THEN 1 ELSE 0 END) AS active_headcount,
        SUM(CASE WHEN f.hire_month_key = dd.date_key THEN 1 ELSE 0 END) AS hires,
        SUM(CASE WHEN f.term_month_key = dd.date_key THEN 1 ELSE 0 END) AS separations
    FROM silver_dim_date dd
    CROSS JOIN silver_fact_employment f
    WHERE dd.date_key >= CAST(strftime('%Y%m', date('{AS_OF}', '-23 months')) AS INTEGER)
    GROUP BY dd.date_key, dd.month_start, dd.year, dd.month_name
);

-- ---------------------------------------------------------------------------
-- Attrition rate by I-O construct level, in long format for driver charts.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS gold_attrition_drivers;
CREATE TABLE gold_attrition_drivers AS
SELECT driver, level, headcount, leavers,
       ROUND(100.0 * leavers / NULLIF(headcount, 0), 1) AS attrition_pct
FROM (
    SELECT 'Job satisfaction' AS driver, 'Level ' || job_satisfaction AS level,
           COUNT(*) AS headcount, SUM(attrition_flag) AS leavers
    FROM gold_employee_analysis GROUP BY job_satisfaction
    UNION ALL
    SELECT 'Environment satisfaction', 'Level ' || environment_satisfaction, COUNT(*), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY environment_satisfaction
    UNION ALL
    SELECT 'Work-life balance', 'Level ' || work_life_balance, COUNT(*), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY work_life_balance
    UNION ALL
    SELECT 'Job involvement', 'Level ' || job_involvement, COUNT(*), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY job_involvement
    UNION ALL
    SELECT 'Overtime', CASE WHEN overtime = 1 THEN 'Works overtime' ELSE 'No overtime' END, COUNT(*), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY overtime
    UNION ALL
    SELECT 'Business travel', business_travel, COUNT(*), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY business_travel
    UNION ALL
    SELECT 'Marital status', marital_status, COUNT(*), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY marital_status
    UNION ALL
    SELECT 'Stock option level', 'Level ' || stock_option_level, COUNT(*), SUM(attrition_flag)
    FROM gold_employee_analysis GROUP BY stock_option_level
)
ORDER BY driver, level;
