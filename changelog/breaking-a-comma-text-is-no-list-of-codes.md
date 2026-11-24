- `get_data` and `get_series` refuse a code given as a text with commas, such as
  `area="231,79"`, before sending, for every domain and filter, and name the whole value as
  the list that several codes take, `["231", "79"]`. In 0.2.0 such a text was sent as
  several codes, each checked first where the domain's table is packaged.
  (https://github.com/xippios/sdk-faostat/pull/67)
