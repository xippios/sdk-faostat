- `xippios.faostat.errors` and `xippios.faostat.enums` are removed: each held the
  template's empty `__all__` and no class or enum, since the package refuses with core's
  errors and generates no enum from its fifteen tables.
  (https://github.com/xippios/sdk-template/issues/300)
