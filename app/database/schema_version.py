"""Versões conhecidas, sem permitir ignorar a compatibilidade do banco."""

SCHEMA_VERSION = 2
CURRENT_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, SCHEMA_VERSION})
