# DAX measures

Paste these into Power BI Desktop (Modeling > New measure). They assume a small model:
the employee grain table `gold_employee_analysis`, a `dim_date` calendar, and
`fact_absence` for the monthly absence trend.

Group the measures under a dedicated `_Measures` table to keep the field list tidy.

## Workforce and turnover

```DAX
Headcount = COUNTROWS ( gold_employee_analysis )

Active Headcount = SUM ( gold_employee_analysis[is_active] )

Separations = SUM ( gold_employee_analysis[attrition_flag] )

-- Trailing year average: current active heads plus half the leavers who were
-- present for part of the year.
Average Headcount = [Active Headcount] + DIVIDE ( [Separations], 2 )

Turnover % = DIVIDE ( [Separations], [Average Headcount] )

Attrition Rate % = DIVIDE ( [Separations], [Headcount] )

Retention Rate % = 1 - [Attrition Rate %]
```

## Absenteeism

```DAX
Absence Hours = SUM ( gold_employee_analysis[absence_hours] )

Scheduled Hours = SUM ( gold_employee_analysis[scheduled_hours] )

Absenteeism Rate % = DIVIDE ( [Absence Hours], [Scheduled Hours] )

Avg Absence Days = AVERAGE ( gold_employee_analysis[absence_days] )

-- Bradford Factor rewards frequent short absences over rare long ones.
Avg Bradford Factor = AVERAGE ( gold_employee_analysis[bradford_factor] )

-- Uses the fact_absence to dim_date relationship for a monthly trend line.
Absence Hours (trend) = SUM ( fact_absence[absence_hours] )
```

## Quality of Hire and talent acquisition

```DAX
Quality of Hire = AVERAGE ( gold_employee_analysis[quality_of_hire] )

QoH Performance = AVERAGE ( gold_employee_analysis[performance_score] )
QoH Retention = AVERAGE ( gold_employee_analysis[retention_score] )
QoH Ramp = AVERAGE ( gold_employee_analysis[ramp_score] )
QoH Hiring Manager = AVERAGE ( gold_employee_analysis[hm_satisfaction_score] )

Avg Time to Fill = AVERAGE ( gold_employee_analysis[time_to_fill_days] )

Avg Ramp Up Days = AVERAGE ( gold_employee_analysis[ramp_up_days] )

Recruiting Cost = SUM ( gold_employee_analysis[recruiting_cost] )

Cost per Hire = DIVIDE ( [Recruiting Cost], [Headcount] )
```

## Formatting and conditional flags

```DAX
-- A traffic light on turnover for a card or table.
Turnover Status =
VAR t = [Turnover %]
RETURN
    SWITCH (
        TRUE (),
        t > 0.20, "High",
        t > 0.12, "Watch",
        "Healthy"
    )
```

## Advanced: point in time headcount

If you also import `fact_employment` (hire and termination month keys) and relate
it to `dim_date` with an inactive relationship on the hire month, you can show a
true month by month active headcount rather than the pre aggregated table.

```DAX
Active Headcount (point in time) =
VAR currentMonth = MAX ( dim_date[date_key] )
RETURN
    CALCULATE (
        COUNTROWS ( fact_employment ),
        FILTER (
            ALL ( fact_employment ),
            fact_employment[hire_month_key] <= currentMonth
                && ( ISBLANK ( fact_employment[term_month_key] )
                     || fact_employment[term_month_key] > currentMonth )
        )
    )
```

Tip: if you prefer to skip the DAX above, the pipeline already ships
`gold_headcount_monthly.csv` with active headcount, hires, separations, and a
monthly turnover column, ready to drop straight onto a line chart.
