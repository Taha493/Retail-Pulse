// Silver equivalent: the key cleaning rules from src/retail_bi/transform/silver.py
let
    Source = Retail_Raw,

    // 1) Remove duplicates (incl. the 1-9 Dec 2010 overlap between the two sheets)
    BusinessCols = {"invoice","stock_code","description","quantity","invoice_date","price","customer_id","country"},
    Deduped = Table.Distinct(Source, BusinessCols),

    // 2) Text standardisation
    Trimmed = Table.TransformColumns(Deduped, {
        {"description", each if _ = null then null else Text.Combine(List.Select(Text.Split(Text.Trim(_), " "), (w) => w <> ""), " "), type text},
        {"stock_code", each Text.Upper(Text.Trim(_)), type text},
        {"country", Text.Trim, type text}
    }),

    // 3) Invoice type: C = cancellation (return), A = bad-debt adjustment
    InvoiceType = Table.AddColumn(Trimmed, "invoice_type", each
        if Text.StartsWith([invoice], "C") then "cancellation"
        else if Text.StartsWith([invoice], "A") then "bad_debt"
        else "sale", type text),

    // 4) Line type: non-product stock codes
    NonProduct = [
        postage = {"POST","DOT","C2","C3"},
        fee = {"AMAZONFEE","BANK CHARGES","CRUK"},
        adjustment = {"M","D","S","B","PADS","ADJUST","ADJUST2","GIFT"},
        test = {"TEST001","TEST002"}
    ],
    LineType = Table.AddColumn(InvoiceType, "line_type", each
        if [invoice_type] = "bad_debt" then "adjustment"
        else if List.Contains(NonProduct[postage], [stock_code]) then "postage"
        else if List.Contains(NonProduct[fee], [stock_code]) then "fee"
        else if List.Contains(NonProduct[adjustment], [stock_code]) or Text.StartsWith([stock_code], "GIFT_")
             or Text.StartsWith([stock_code], "ADJUST") then "adjustment"
        else if Text.StartsWith([stock_code], "TEST") then "test"
        else if [invoice_type] = "sale" and [quantity] < 0 and [price] = 0 then "stock_writeoff"
        else "product", type text),

    // 5) Guests: missing customer -> -1
    Guests = Table.ReplaceValue(LineType, null, -1, Replacer.ReplaceValue, {"customer_id"}),

    // 6) Country labels -> ISO-3166 alpha-3 via the mapping query
    WithIso = Table.NestedJoin(Guests, {"country"}, Country_Map, {"country"}, "map", JoinKind.LeftOuter),
    Expanded = Table.ExpandTableColumn(WithIso, "map", {"iso3"}, {"country_iso3"}),

    // 7) Derived columns
    Revenue = Table.AddColumn(Expanded, "revenue_gbp", each Number.Round([quantity] * [price], 2), Currency.Type),
    DateKey = Table.AddColumn(Revenue, "date_key", each
        Date.Year([invoice_date]) * 10000 + Date.Month([invoice_date]) * 100 + Date.Day([invoice_date]), Int64.Type),

    // 8) Analysis-ready = priced product sales and returns
    Analysis = Table.SelectRows(DateKey, each [line_type] = "product" and [price] > 0
        and ([invoice_type] = "sale" or [invoice_type] = "cancellation"))
in
    Analysis
