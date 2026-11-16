"""Consumer-facing web report builder for the WGS/FMT platform.

This package is intentionally separate from ``reporting`` so that the
professional PDF, Markdown and structured report remain byte-for-byte
unaffected.  The consumer view model has its own schema, its own number
formatting and its own glossary review gate.
"""

from .builder import BUILDER_VERSION, SCHEMA_VERSION, build_report

__all__ = ["BUILDER_VERSION", "SCHEMA_VERSION", "build_report"]
