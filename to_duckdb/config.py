"""
Shared configuration for the to_duckdb CLI tools.

Only genuinely cross-cutting values live here.  Domain-specific constants
(bin edges, physical thresholds, channel lists, filesystem layout) stay in
the module that owns them.
"""

DEFAULT_DB = "magnetdb.duckdb"

MW_TO_W = 1e6      # MW → W
J_TO_KWH = 3.6e6   # J → kWh
J_TO_MWH = 3.6e9   # J → MWh

# Expected physical unit of each computed scalar channel stored in
# op_run_scalars / exp_run_scalars.  Used to assert dimensional
# consistency of compute_scalars() at ingest time and to populate the
# `unit` column on insert.
SCALAR_CHANNEL_UNITS: dict[str, str] = {
    "energy_j": "joule",
    "heat_extracted_j": "joule",
    "duration_s": "second",
    "duration_field_on_s": "second",
}
