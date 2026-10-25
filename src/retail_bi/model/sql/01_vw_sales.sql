-- Denormalised sales view: the star schema flattened for ad-hoc SQL analysis.
CREATE OR REPLACE VIEW vw_sales AS
SELECT
    f.sales_key,
    f.invoice_no,
    f.invoice_datetime,
    f.invoice_hour,
    d.date,
    d.year,
    d.quarter,
    d.month_num,
    d.month_start,
    d.month_year,
    d.weekday_num,
    d.weekday_short,
    d.is_uk_holiday,
    c.customer_key,
    c.customer_label,
    c.rfm_segment,
    c.cohort_month,
    p.product_key,
    p.stock_code,
    p.product_name,
    p.category,
    p.sub_category,
    p.abc_class,
    p.price_band,
    g.country_key,
    g.country_name,
    g.iso3,
    g.region,
    g.market,
    f.quantity,
    f.unit_price_gbp,
    f.revenue_gbp,
    f.revenue_eur,
    f.revenue_usd,
    f.is_return,
    c.customer_key = -1 AS is_guest
FROM fact_sales f
JOIN dim_date d USING (date_key)
JOIN dim_customer c USING (customer_key)
JOIN dim_product p USING (product_key)
JOIN dim_country g USING (country_key);
