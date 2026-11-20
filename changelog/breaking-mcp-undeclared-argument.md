- A tool refuses an argument that it does not declare before it runs, whatever its value,
  where the argument was dropped and the tool ran without it: `faostat_list_domains` called
  with `serch` answers `error: InvalidRequestError: serch: Not an argument of this tool; it
  takes search`, where it listed every domain. (https://github.com/xippios/sdk-core/issues/84)
