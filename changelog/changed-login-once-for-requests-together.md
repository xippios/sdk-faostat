- Requests that start together while the process holds no token log in once and wait for
  that login, where each could log in, a keyed call each; a request refused with HTTP 401
  or 403 still logs in once more and is sent again once. A login answered with another
  status than 200 or a refusal of the account raises xippios-core's error quoting nothing
  of the answer, a 5xx an `UpstreamError` with an empty `body`, where it held the answer's
  text. (https://github.com/xippios/sdk-core/issues/156)
