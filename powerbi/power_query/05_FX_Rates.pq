// Daily GBP -> EUR/USD rates from the Frankfurter API (ECB data), forward-filled over weekends.
let
    Raw = Json.Document(Web.Contents("https://api.frankfurter.dev/v1/2009-12-01..2011-12-31",
        [Query = [base = "GBP", symbols = "EUR,USD"]])),
    Rates = Record.ToTable(Raw[rates]),
    Expanded = Table.ExpandRecordColumn(Rates, "Value", {"EUR", "USD"}),
    Typed = Table.TransformColumnTypes(Expanded, {{"Name", type date}, {"EUR", type number}, {"USD", type number}}),
    Renamed = Table.RenameColumns(Typed, {{"Name", "date"}}),
    // Calendar to fill the gaps
    Days = List.Dates(#date(2009, 12, 1), Duration.Days(#date(2011, 12, 31) - #date(2009, 12, 1)) + 1, #duration(1, 0, 0, 0)),
    Calendar = Table.FromList(Days, Splitter.SplitByNothing(), type table [date = date]),
    Joined = Table.NestedJoin(Calendar, {"date"}, Renamed, {"date"}, "r", JoinKind.LeftOuter),
    Flat = Table.ExpandTableColumn(Joined, "r", {"EUR", "USD"}),
    Sorted = Table.Sort(Flat, {{"date", Order.Ascending}}),
    Filled = Table.FillUp(Table.FillDown(Sorted, {"EUR", "USD"}), {"EUR", "USD"}),
    WithGBP = Table.AddColumn(Filled, "GBP", each 1.0, type number),
    Long = Table.UnpivotOtherColumns(WithGBP, {"date"}, "currency_code", "rate_from_gbp"),
    Keyed = Table.AddColumn(Long, "date_key", each Date.Year([date]) * 10000 + Date.Month([date]) * 100 + Date.Day([date]), Int64.Type)
in
    Table.SelectColumns(Keyed, {"date_key", "currency_code", "rate_from_gbp"})
