"""
Query helper for the "max consume prob vs halt time" datapoint.

This module provides a single-datapoint query function with on-disk caching,
so scripts can call it repeatedly without needing separate "acquire vs load"
phases.
"""

from helpers.compute import MaxProbHaltTimeParams, query_maxprob_halt_time
