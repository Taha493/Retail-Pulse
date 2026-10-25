-- Cohort retention: share of each first-purchase cohort active N months later.
CREATE OR REPLACE VIEW vw_cohort_retention AS
WITH activity AS (
    SELECT DISTINCT customer_key, cohort_month, month_start
    FROM vw_sales
    WHERE NOT is_guest AND NOT is_return AND cohort_month IS NOT NULL
),
sized AS (
    SELECT
        cohort_month,
        date_diff('month', cohort_month, month_start) AS months_since_first,
        COUNT(*) AS active_customers
    FROM activity
    GROUP BY ALL
)
SELECT
    s.*,
    FIRST_VALUE(active_customers) OVER (PARTITION BY cohort_month ORDER BY months_since_first) AS cohort_size,
    active_customers / FIRST_VALUE(active_customers)
        OVER (PARTITION BY cohort_month ORDER BY months_since_first) AS retention_rate
FROM sized s
ORDER BY cohort_month, months_since_first;
