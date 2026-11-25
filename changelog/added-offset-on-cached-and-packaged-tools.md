- `faostat_list_areas`, `faostat_list_elements`, `faostat_list_items`,
  `faostat_list_domains` and `faostat_list_bulk_datasets` take
  `offset`, the rows of a cut answer already shown, and answer the rows after them by
  running the task again on a packaged table or a cached answer. The note of every page but
  the last names the `offset` to continue with. `faostat_get_series` takes none, since one
  answer of it can pass the response cache's bound of 8 MiB, past which a continuation
  would send its request again.
  (https://github.com/xippios/sdk-faostat/issues/32, https://github.com/xippios/sdk-faostat/issues/80)
