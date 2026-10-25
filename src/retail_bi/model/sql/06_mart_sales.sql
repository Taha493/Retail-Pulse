-- Materialised wide table used by the web dashboard for fast filtering.
-- (Power BI would use the star schema directly; this is a performance cache.)
CREATE OR REPLACE TABLE mart_sales AS
SELECT * FROM vw_sales
ORDER BY date;
