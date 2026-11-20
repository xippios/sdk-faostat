- `xippios.faostat.mcp` exports `build()`, the tool set of xippios-core's package contract
  with the tools' caps, `server`, built from it, and `ENV_VARS`, the variables the package
  reads, `FAOSTAT_USERNAME` and `FAOSTAT_PASSWORD`, both secret and required, so a host
  serves the package as `xippios-faostat-mcp` does.
  (https://github.com/xippios/sdk-core/issues/245)
