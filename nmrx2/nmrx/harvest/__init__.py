"""Harvest, normalize and stratify public spectral data into calibration corpora."""
from .sources import SOURCES, HARVESTABLE, COMMERCIALLY_CLEAR, SPECTRAL_AND_CLEAR, report
from .normalize import (NUCLEUS_RANGES, normalize_solvent, quality_filter, deduplicate,
                        pending_quantum_jobs, to_calibration_set, slice_key)
from .stratify import stratify, format_report, required_total

__all__ = ["SOURCES", "HARVESTABLE", "COMMERCIALLY_CLEAR", "SPECTRAL_AND_CLEAR", "report",
           "NUCLEUS_RANGES", "normalize_solvent", "quality_filter", "deduplicate",
           "pending_quantum_jobs", "to_calibration_set", "slice_key",
           "stratify", "format_report", "required_total"]
