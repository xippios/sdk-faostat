- `Domain.date_update` of `list_domains` is a date, and `BulkDataset.date_update` of
  `list_bulk_datasets` a time without a zone, as FAOSTAT prints them, in place of their
  text. `meta.vintage` keeps the text as printed.
  (https://github.com/xippios/sdk-usda-esr/issues/60)
