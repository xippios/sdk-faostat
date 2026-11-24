- `faostat_list_areas`, `faostat_list_elements`, `faostat_list_items`,
  `faostat_list_domains`, `faostat_list_bulk_datasets` and `faostat_get_series` take
  `offset`, the rows of a cut answer already shown, and answer the rows after them by
  running the task again on a packaged table or a cached answer; the note of every page but
  the last names the `offset` to continue with. (https://github.com/xippios/sdk-faostat/issues/32)
