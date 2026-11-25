- `faostat_list_areas`, `faostat_list_elements`, `faostat_list_items`,
  `faostat_list_domains` and `faostat_list_bulk_datasets` take
  `offset`, the rows of a cut answer already shown, and answer the rows after them by
  running the task again on a packaged table or a cached answer. The note of every page but
  the last names the `offset` to continue with. (https://github.com/xippios/sdk-faostat/issues/32)
