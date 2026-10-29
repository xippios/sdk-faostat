# Sample files

A sample of each file kind the parsers read, `<file_kind>/<case>.<ext>`: a small real
file, or the first rows of one as conventions §10 allows, never typed in by hand
(ADR-0020). A binary file carries no comment, so each sample's provenance is one row
here: the release id, the URL, the bytes and sha256 of the full file as upstream serves
it, and the UTC time it was fetched, with `Z`.

`bulk-csv/` holds the ZIPs `parse_bulk_csv` reads, recorded on 2026-10-29 without the
account by a one-off recording script, which fetched the catalogue and both files: MDDW's
whole ZIP, the smallest dataset's, the response body of the recorded exchange
`tests/fixtures/download_dataset/MDDW.json` byte for byte; and, for a header of the
production shape (area, item, element, year), a new ZIP the script wrote from RL's fetched
file, holding one member of it, the normalized table, cut to its header and first rows as
printed (ADR-0019 decision 5: one member of the archive cut to a few rows, a real sample,
never a byte-truncated archive). The release is the catalogue's `DateUpdate` for the
dataset. `tests/test_parse.py` reads both and checks the first against its recording; it
asserts shape, never values or sizes.

| File | Release | URL | Bytes | sha256 | Fetched | What |
| --- | --- | --- | --- | --- | --- | --- |
| `bulk-csv/MDDW.zip` | `2025-10-28T00:00:00` (DateUpdate) | https://bulks-faostat.fao.org/production/Minimum_Dietary_Diversity_for_Women_(MDD-W)_Food_and_Diet_E_All_Data_(Normalized).zip | 12146 | `f8a1b5058c802c909339ed81c4603b34d5223217e6d5c05779af2311384bbf2b` | 2026-10-29T07:42:28Z | the whole ZIP, the response body of `download_dataset/MDDW.json` byte for byte: the normalized table `Minimum_Dietary_Diversity_for_Women_(MDD-W)_Food_and_Diet_E_All_Data_(Normalized).csv` (206,295 bytes, 1,223 rows, where the catalogue's `FileRows` counts 2,035), with MDDW's own columns, no area, item or year, and four code lists, `_Elements.csv`, `_Flags.csv`, `_Indicators.csv` and `_Surveys.csv` |
| `bulk-csv/RL_first_rows.zip` | `2026-10-02T00:00:00` (DateUpdate) | https://bulks-faostat.fao.org/production/Inputs_LandUse_E_All_Data_(Normalized).zip | 2970716 | `39b739fbfb694971207a2efa572c41e8de2386fc5cb33caaf2a188e9c9a6ca3f` | 2026-10-29T07:42:31Z | a new ZIP holding the full file's member `Inputs_LandUse_E_All_Data_(Normalized).csv` (49,969,452 bytes, 421,850 rows) cut to its header and first 20 rows, as printed, CRLF kept, under the member's name and time, deflated with `zipfile`; the full file's four code lists, `_AreaCodes.csv`, `_Elements.csv`, `_Flags.csv` and `_ItemCodes.csv`, left out |
