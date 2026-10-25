// Country label -> ISO-3166 alpha-3. Labels not listed here match the ISO list by name.
let
    Overrides = #table(type table [country = text, iso3 = text], {
        {"United Kingdom", "GBR"}, {"Netherlands", "NLD"}, {"EIRE", "IRL"}, {"RSA", "ZAF"},
        {"USA", "USA"}, {"Korea", "KOR"}, {"Czech Republic", "CZE"},
        {"Channel Islands", "CHI"}, {"European Community", "EUR"},
        {"West Indies", "WIN"}, {"Unspecified", "UNK"}
    }),
    IsoList = Csv.Document(
        Web.Contents("https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/master/all/all.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    IsoPromoted = Table.PromoteHeaders(IsoList),
    IsoNames = Table.SelectColumns(Table.RenameColumns(IsoPromoted, {{"name", "country"}, {"alpha-3", "iso3"}}), {"country", "iso3"}),
    Combined = Table.Combine({Overrides, Table.SelectRows(IsoNames, each not List.Contains(Overrides[country], [country]))})
in
    Combined
