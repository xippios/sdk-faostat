- A row's `value`, of `get_data`, `get_series` and `parse_bulk_csv`, is the text as FAOSTAT
  prints it, `""` for an empty cell of a bulk file, with `value_number` beside it, its
  reading as a number or `None`, a JSON integer over MCP and HTTP where it has no fraction.
  (https://github.com/xippios/sdk-core/issues/474)
