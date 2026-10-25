// Parameters (Home -> Manage Parameters). Point SourceFolder at the repo's data folder.
// SourceFolder = "C:\retail-bi\data\" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]
// GoldFolder   = SourceFolder & "gold\"
//
// Option A (recommended): import the finished star schema from data\gold\*.parquet
//   -> see 07_Gold_Import.pq
// Option B (show the transforms in Power Query): rebuild from the raw Excel file
//   -> 02_Retail_Raw.pq, 03_Retail_Clean.pq, 04_Country_Map.pq, 05_FX_Rates.pq, 06_Dim_Date.pq
let
    SourceFolder = "C:\retail-bi\data\"
in
    SourceFolder
