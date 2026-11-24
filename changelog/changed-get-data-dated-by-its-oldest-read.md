- `meta.retrieved_at` of `get_data` and `get_series` is the client's time of the answer, the
  oldest of the two reads they assemble, so a release date kept in the cache dates the
  answer where it is older than the data request.
  (https://github.com/xippios/sdk-core/issues/479, https://github.com/xippios/sdk-faostat/issues/68)
