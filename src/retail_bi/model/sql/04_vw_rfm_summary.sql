-- Customer value by RFM segment.
CREATE OR REPLACE VIEW vw_rfm_summary AS
SELECT
    rfm_segment,
    COUNT(*)                         AS customers,
    SUM(lifetime_revenue_gbp)        AS revenue_gbp,
    AVG(lifetime_revenue_gbp)        AS avg_revenue_gbp,
    AVG(orders)                      AS avg_orders,
    AVG(recency_days)                AS avg_recency_days
FROM dim_customer
WHERE customer_key <> -1
GROUP BY rfm_segment
ORDER BY revenue_gbp DESC;
