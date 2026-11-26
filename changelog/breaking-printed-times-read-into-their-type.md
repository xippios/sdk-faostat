- `Domain.date_update` of `list_domains` is a date, and `BulkDataset.date_update` of
  `list_bulk_datasets` a time without a zone, as FAOSTAT prints them, in place of their
  text, and the two tasks' docstrings, their tools' descriptions, say so. `meta.vintage`
  keeps the text as printed.
  (https://github.com/xippios/sdk-usda-esr/issues/60, https://github.com/xippios/sdk-faostat/issues/84)
