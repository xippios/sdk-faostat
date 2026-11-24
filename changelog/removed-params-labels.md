- `xippios.faostat.params.labels`, the index of a packaged table's codes and labels, is
  removed: `params.table(name)` declares each table once for core's `check`, whose
  `name_of` gives a code's label, and `params.codes(name)` lists the codes with their labels.
  (https://github.com/xippios/sdk-faostat/issues/31)
