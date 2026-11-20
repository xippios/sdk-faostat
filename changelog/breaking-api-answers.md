- The wrappers `api.get_data.get_data`, `api.get_code_list.get_code_list`,
  `api.get_groupsanddomains.get_groupsanddomains` and `api.datasets_e.datasets_e` return
  xippios-core's `Answer`, the parsed answer as `payload` beside `retrieved_at`, where each
  returned a pair of its own with the answer as `response`. `DataAnswer`, `CodeListAnswer`,
  `GroupsAndDomainsAnswer` and `DatasetsCatalogueAnswer` are gone, and the tasks answer as
  before. (https://github.com/xippios/sdk-core/issues/123)
