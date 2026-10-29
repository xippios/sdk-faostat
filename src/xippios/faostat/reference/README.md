# Reference data for FAOSTAT

Lists and tables the upstream publishes for every caller alike, shipped with the package
(conventions §3): each `reference/<name>.json` holds `{"param", "endpoint", "fetched",
"records"}` and an optional `"note"`, upstream's records under upstream's field names,
written by `/refresh-reference-data`'s script with `PackagedList.write`, never by hand,
and read with `PackagedList.load`. One row per file: Origin is the endpoint or URL it was
fetched from, or the `docs/upstream/` file it was rebuilt from; Fetched is the UTC time
of that fetch, or the snapshot's `Fetched` time for a rebuilt file.

```python
from xippios.core import PackagedList

elements = PackagedList.load("xippios.faostat", "element_QCL")
elements.records[2]  # {"code": "2510", "label": "Production Quantity", "aggregate_type": "0"}
```

Fifteen tables, one per dimension and domain: the codes of the dimensions `area`,
`element` and `item` of the domains QCL (Crops and livestock products), TCL (their
trade), FBS (Food Balances, 2010-), PP (Producer Prices) and RL (Land Use), each
`getCodeList`'s answer for `GET /en/codes/<dimension>/<domain>` under
`https://faostatservices.fao.org/api/v1`, fetched with the FAO account's token, in
English, `show_lists` left to upstream's default (true). A file is named
`<dimension>_<domain>.json`, the domain's code as upstream writes it; its `param` is the
dimension, the data endpoint's filter that takes the codes, and its records carry `code`,
`label` and `aggregate_type`, and `parent` in QCL's, TCL's and RL's item tables (RL's on
51 of 57 records) and in TCL's and RL's element tables, in upstream's order and as
upstream sends them: QCL's item list names its five top groups (`QC>`, "Crops, primary >
(List)", and four more) twice, and so does the table. `list_areas`, `list_elements` and
`list_items` answer from them, and `get_data` checks a packaged domain's area, element
and item codes against them before it sends.

The element tables hold the codes a data query filters by (`2510` Production Quantity
in QCL), not the `Element Code` the data rows print (`5510` Production); nothing is
translated between the two (ADR-0003).

The tables come from the dimension ids, not the subdimension ids. `get_dimensions`
answers for QCL the dimensions `area`, `element`, `item` and `year`, the names
of the data endpoint's filters, each with its subdimensions
(`docs/upstream/samples/dimensions_QCL.json`: `countries`, `regions` and
`specialgroups` under `area`); the OpenAPI document's examples of `dimension_id` name
subdimension ids (`countries`, `items`, `elements`). Both answer `getCodeList`, recorded
for QCL on 2026-10-29 (`tests/fixtures/get_code_list/`): `codes/area/QCL` lists 278
codes, the 210 countries `codes/countries/QCL` lists with the same labels, and 68
aggregates beside them, the totals and lists of regions and special groups (`5000`
World + (Total), `5000>` World > (List)). The data endpoint filters by the dimension,
`area`, and `getCodeList` lists all 278 as that dimension's codes, so the dimension's
answer is packaged: a check against the countries alone would refuse a region's code.

| File | Origin | Fetched |
| --- | --- | --- |
| `area_QCL.json` | `getCodeList`, `GET /en/codes/area/QCL` | 2026-10-29T07:06:41Z |
| `element_QCL.json` | `getCodeList`, `GET /en/codes/element/QCL` | 2026-10-29T07:06:42Z |
| `item_QCL.json` | `getCodeList`, `GET /en/codes/item/QCL` | 2026-10-29T07:06:44Z |
| `area_TCL.json` | `getCodeList`, `GET /en/codes/area/TCL` | 2026-10-29T07:06:46Z |
| `element_TCL.json` | `getCodeList`, `GET /en/codes/element/TCL` | 2026-10-29T07:06:48Z |
| `item_TCL.json` | `getCodeList`, `GET /en/codes/item/TCL` | 2026-10-29T07:06:47Z |
| `area_FBS.json` | `getCodeList`, `GET /en/codes/area/FBS` | 2026-10-29T07:06:49Z |
| `element_FBS.json` | `getCodeList`, `GET /en/codes/element/FBS` | 2026-10-29T07:06:51Z |
| `item_FBS.json` | `getCodeList`, `GET /en/codes/item/FBS` | 2026-10-29T07:06:53Z |
| `area_PP.json` | `getCodeList`, `GET /en/codes/area/PP` | 2026-10-29T07:06:55Z |
| `element_PP.json` | `getCodeList`, `GET /en/codes/element/PP` | 2026-10-29T07:06:57Z |
| `item_PP.json` | `getCodeList`, `GET /en/codes/item/PP` | 2026-10-29T07:06:59Z |
| `area_RL.json` | `getCodeList`, `GET /en/codes/area/RL` | 2026-10-29T07:07:01Z |
| `element_RL.json` | `getCodeList`, `GET /en/codes/element/RL` | 2026-10-29T07:07:03Z |
| `item_RL.json` | `getCodeList`, `GET /en/codes/item/RL` | 2026-10-29T07:07:05Z |
