// Option A: import the gold star schema produced by the Python pipeline.
// Create one query per table by changing TableName, or duplicate this query.
let
    TableName = "fact_sales",
    Source = Parquet.Document(File.Contents(SourceFolder & "gold\" & TableName & ".parquet"))
in
    Source
// Tables: fact_sales, fact_fx_rates, dim_date, dim_customer, dim_product, dim_country, dim_currency
// (CSV copies sit next to the parquet files if your Power BI version lacks Parquet.Document.)
