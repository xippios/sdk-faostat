- `meta.retrieved_at` of `get_data`, `get_series` and `download_dataset` is the client's
  time of the answer, the oldest of the two reads each assembles, so a release date or a
  catalogue kept in the cache dates the answer where it is older than the data read or
  the download. (https://github.com/xippios/sdk-core/issues/479, https://github.com/xippios/sdk-faostat/issues/68)
