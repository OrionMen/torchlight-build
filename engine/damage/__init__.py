"""R001 hit-damage calculation API."""

from .hit_damage import calculate_hit_damage
from .models import (
    ComponentResult,
    Conversion,
    DamageComponent,
    HitDamageResult,
    Modifier,
)

__all__ = [
    "ComponentResult",
    "Conversion",
    "DamageComponent",
    "HitDamageResult",
    "Modifier",
    "calculate_hit_damage",
]
