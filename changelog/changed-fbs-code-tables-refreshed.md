- The packaged code tables of Food Balances (FBS) follow FAOSTAT's lists of this release:
  seven areas are added and Seychelles (`196`) is gone, so `get_data` refuses that area on
  FBS before it sends. Six indicator elements (`501` to `506`) stand under the new list
  `72003>`, and one item is added (`2920`) and four take new labels, the fish groups among
  them.
  (https://github.com/xippios/sdk-faostat/issues/74)
