// Bronze equivalent: both Excel sheets -> typed, appended table.
// Mirrors src/retail_bi/transform/bronze.py
let
    Source      = Excel.Workbook(File.Contents(SourceFolder & "raw\online_retail_II.xlsx"), null, true),
    Sheets      = Table.SelectRows(Source, each [Kind] = "Sheet"),
    // Promote headers inside each sheet, tag the sheet name for lineage
    Promoted    = Table.AddColumn(Sheets, "Data2", each Table.PromoteHeaders([Data], [PromoteAllScalars = true])),
    Tagged      = Table.AddColumn(Promoted, "Tagged", each Table.AddColumn([Data2], "_source_sheet", (r) => [Name], type text)),
    Appended    = Table.Combine(Tagged[Tagged]),
    // Invoice MUST be text: "C" (cancellation) and "A" (bad debt) prefixes
    Typed = Table.TransformColumnTypes(Appended, {
        {"Invoice", type text}, {"StockCode", type text}, {"Description", type text},
        {"Quantity", Int64.Type}, {"InvoiceDate", type datetime}, {"Price", type number},
        {"Customer ID", Int64.Type}, {"Country", type text}
    }),
    Renamed = Table.RenameColumns(Typed, {
        {"Invoice", "invoice"}, {"StockCode", "stock_code"}, {"Description", "description"},
        {"Quantity", "quantity"}, {"InvoiceDate", "invoice_date"}, {"Price", "price"},
        {"Customer ID", "customer_id"}, {"Country", "country"}
    })
in
    Renamed
