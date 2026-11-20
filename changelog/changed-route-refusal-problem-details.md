- A route answers an argument that its schema refuses, `page_size` `"many"` posted to
  `/faostat/get_data` say, as problem details before the task runs: HTTP 422,
  `application/problem+json`, the title `InvalidRequestError` and the detail
  `page_size: <message>`, without the value given, where FastAPI's own 422 listed its error
  details with the input. (https://github.com/xippios/sdk-core/issues/66)
