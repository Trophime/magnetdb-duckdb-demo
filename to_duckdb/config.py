"""
Shared configuration for the to_duckdb CLI tools.

Only genuinely cross-cutting values live here.  Domain-specific constants
(bin edges, physical thresholds, channel lists, filesystem layout) stay in
the module that owns them.
"""

DEFAULT_DB = "magnetdb.duckdb"
