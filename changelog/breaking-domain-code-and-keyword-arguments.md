- The tasks take the domain by FAOSTAT's name, `domain_code`, in `get_data`, `get_series`,
  `list_areas`, `list_elements` and `list_items`, and `download_dataset` takes the
  catalogue's `dataset_code`, over MCP and HTTP too. `get_series` takes `area`, `item` and
  `element` by keyword alone and `download_dataset` its `dest`, since the arguments that
  identify a record are positional and every other is keyword-only.
  (https://github.com/xippios/sdk-faostat/issues/58, https://github.com/xippios/sdk-usda-esr/issues/60)
