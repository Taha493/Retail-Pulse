-- Monthly KPIs (one row per month).
CREATE OR REPLACE VIEW vw_monthly_sales AS
SELECT
    month_start,
    SUM(revenue_gbp) FILTER (WHERE NOT is_return)                    AS gross_revenue_gbp,
    -SUM(revenue_gbp) FILTER (WHERE is_return)                       AS return_value_gbp,
    SUM(revenue_gbp)                                                 AS net_revenue_gbp,
    COUNT(DISTINCT invoice_no) FILTER (WHERE NOT is_return)          AS orders,
    COUNT(DISTINCT customer_key) FILTER (WHERE NOT is_guest AND NOT is_return) AS active_customers,
    SUM(quantity) FILTER (WHERE NOT is_return)                       AS units_sold
FROM vw_sales
GROUP BY month_start
ORDER BY month_start;
