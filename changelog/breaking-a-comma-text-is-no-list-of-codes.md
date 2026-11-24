- `get_data` and `get_series` refuse a code given as a text with commas, such as
  `area="231,79"`, before sending, for every domain and filter, and name the list form,
  `["231", "79"]`, that several codes take. Several codes were sent as that text where a
  domain had no packaged table, and refused as one unknown code where it had one.
  (https://github.com/xippios/sdk-faostat/pull/67)
