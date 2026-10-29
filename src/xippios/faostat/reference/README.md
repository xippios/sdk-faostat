# Reference data for FAOSTAT

Lists and tables the upstream publishes for every caller alike, shipped with the package
(conventions §3): each `reference/<name>.json` holds `{"param", "endpoint", "fetched",
"records"}` and an optional `"note"`, upstream's records under upstream's field names,
written by `/refresh-reference-data`'s script with `PackagedList.write`, never by hand,
and read with `PackagedList.load`. One row per file: Origin is the endpoint or URL it was
fetched from, or the `docs/upstream/` file it was rebuilt from; Fetched is the UTC time
of that fetch, or the snapshot's `Fetched` time for a rebuilt file.

| File | Origin | Fetched |
| --- | --- | --- |
| (none yet) | | |
