- `api.get_groupsanddomains` answers `GroupsAndDomains`, the parsed `response` and each
  `date_update` as FAOSTAT sent it, and `api.datasets_e` answers `Catalogue`, the parsed
  `catalogue` and each `DateUpdate` as sent, in place of the bare models, so that
  `meta.vintage` holds the release as FAOSTAT states it.
  (https://github.com/xippios/sdk-usda-esr/issues/60)
