// Continuous date table (mark it as the date table after loading).
let
    StartDate = #date(2009, 12, 1),
    EndDate = #date(2011, 12, 31),
    FiscalStartMonth = 4,
    Dates = List.Dates(StartDate, Duration.Days(EndDate - StartDate) + 1, #duration(1, 0, 0, 0)),
    T0 = Table.FromList(Dates, Splitter.SplitByNothing(), type table [date = date]),
    T1 = Table.AddColumn(T0, "date_key", each Date.Year([date]) * 10000 + Date.Month([date]) * 100 + Date.Day([date]), Int64.Type),
    T2 = Table.AddColumn(T1, "year", each Date.Year([date]), Int64.Type),
    T3 = Table.AddColumn(T2, "quarter", each "Q" & Text.From(Date.QuarterOfYear([date])), type text),
    T4 = Table.AddColumn(T3, "month_num", each Date.Month([date]), Int64.Type),
    T5 = Table.AddColumn(T4, "month_name", each Date.MonthName([date], "en-GB"), type text),
    T6 = Table.AddColumn(T5, "month_year", each Date.ToText([date], "MMM yyyy", "en-GB"), type text),
    T7 = Table.AddColumn(T6, "month_start", each Date.StartOfMonth([date]), type date),
    T8 = Table.AddColumn(T7, "weekday_num", each Date.DayOfWeek([date], Day.Monday) + 1, Int64.Type),
    T9 = Table.AddColumn(T8, "weekday_name", each Date.DayOfWeekName([date], "en-GB"), type text),
    T10 = Table.AddColumn(T9, "is_weekend", each Date.DayOfWeek([date], Day.Monday) >= 5, type logical),
    T11 = Table.AddColumn(T10, "fiscal_year", each
        let y = if Date.Month([date]) >= FiscalStartMonth then Date.Year([date]) else Date.Year([date]) - 1
        in "FY" & Text.From(y) & "/" & Text.End(Text.From(y + 1), 2), type text)
in
    T11
// Sort month_year by month_start and weekday_name by weekday_num (Column tools -> Sort by column).
