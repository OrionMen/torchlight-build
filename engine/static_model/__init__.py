"""A001/A002 静态计算基础公开 API。"""

from .calculation import (
    aggregate_modifiers,
    calculate_extra_groups_multiplier,
    match_filters,
    resolve_mechanic,
)
from .models import (
    CalculationContext,
    CapabilityContribution,
    MechanicResolution,
    Modifier,
    ModifierAggregationResult,
    SourceTrace,
    TraceEntry,
)

__all__ = [
    "CalculationContext",
    "CapabilityContribution",
    "MechanicResolution",
    "Modifier",
    "ModifierAggregationResult",
    "SourceTrace",
    "TraceEntry",
    "aggregate_modifiers",
    "calculate_extra_groups_multiplier",
    "match_filters",
    "resolve_mechanic",
]
