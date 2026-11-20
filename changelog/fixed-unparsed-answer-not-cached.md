- An answer of HTTP 200 that is not JSON, a maintenance page say, or JSON that is not the
  documented answer is asked again on the next call, where it was cached for five minutes
  and every call in that time failed with `ValidationError` without a request.
  (https://github.com/xippios/sdk-core/issues/122)
