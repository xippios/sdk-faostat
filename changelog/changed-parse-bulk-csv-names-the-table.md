- `parse_bulk_csv`'s refusal of a table names the table alone,
  `faostat: Inputs_LandUse_E_All_Data_(Normalized).csv is not UTF-8 text: invalid start
  byte`, where it named the table in its ZIP, `... (Normalized).csv in RL.zip ...`. A
  refusal of the archive itself still names the ZIP, and the table is read through
  xippios-core's `decode_csv`. (https://github.com/xippios/sdk-core/issues/89)
