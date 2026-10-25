-- Country league table incl. revenue per million inhabitants.
CREATE OR REPLACE VIEW vw_country_summary AS
SELECT
    g.country_name,
    g.iso3,
    g.region,
    g.market,
    g.population,
    g.gdp_per_capita,
    SUM(f.revenue_gbp)                                         AS net_revenue_gbp,
    COUNT(DISTINCT f.invoice_no) FILTER (WHERE NOT f.is_return) AS orders,
    COUNT(DISTINCT f.customer_key) FILTER (WHERE f.customer_key <> -1) AS customers,
    SUM(f.revenue_gbp) / NULLIF(g.population, 0) * 1e6        AS revenue_per_million_pop
FROM fact_sales f
JOIN dim_country g USING (country_key)
GROUP BY g.country_name, g.iso3, g.region, g.market, g.population, g.gdp_per_capita
ORDER BY net_revenue_gbp DESC;
