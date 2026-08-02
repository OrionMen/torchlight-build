from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional


DAMAGE_TYPES = frozenset({"physical", "lightning", "cold", "fire", "erosion"})
MODIFIER_KINDS = frozenset({"increased", "extra"})
OWNER_SCOPES = frozenset({"character_global", "skill_local", "generated_skill_local"})


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _damage_type(value: object, field_name: str) -> str:
    if value not in DAMAGE_TYPES:
        raise ValueError(f"{field_name} must be a supported damage type")
    return str(value)


def _string_set(value: object, field_name: str) -> FrozenSet[str]:
    if isinstance(value, str):
        raise TypeError(f"{field_name} must be a set of strings")
    try:
        result = frozenset(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(f"{field_name} must be a set of strings") from exc
    if any(not isinstance(item, str) for item in result):
        raise TypeError(f"{field_name} must contain only strings")
    return result


@dataclass
class DamageComponent:
    base_value: float
    current_type: str
    source_type_history: List[str]

    def __post_init__(self) -> None:
        self.base_value = _number(self.base_value, "base_value")
        if self.base_value < 0:
            raise ValueError("base_value must be non-negative")
        self.current_type = _damage_type(self.current_type, "current_type")
        if isinstance(self.source_type_history, str):
            raise TypeError("source_type_history must be an ordered list")
        self.source_type_history = list(self.source_type_history)
        if not self.source_type_history:
            raise ValueError("source_type_history must not be empty")
        for damage_type in self.source_type_history:
            _damage_type(damage_type, "source_type_history item")
        if len(set(self.source_type_history)) != len(self.source_type_history):
            raise ValueError("source_type_history must be unique")
        if self.current_type not in self.source_type_history:
            raise ValueError("source_type_history must include current_type")


@dataclass
class Modifier:
    kind: str
    value: float
    required_tags: FrozenSet[str] = field(default_factory=frozenset)
    required_damage_types: FrozenSet[str] = field(default_factory=frozenset)
    owner_scope: str = "character_global"
    owner_id: Optional[str] = None
    extra_group: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in MODIFIER_KINDS:
            raise ValueError("kind must be increased or extra")
        self.value = _number(self.value, "value")
        self.required_tags = _string_set(self.required_tags, "required_tags")
        damage_types = _string_set(self.required_damage_types, "required_damage_types")
        for damage_type in damage_types:
            _damage_type(damage_type, "required_damage_types item")
        self.required_damage_types = damage_types
        if self.owner_scope not in OWNER_SCOPES:
            raise ValueError("owner_scope is not supported")
        if self.owner_id is not None and not isinstance(self.owner_id, str):
            raise TypeError("owner_id must be a string or None")
        if self.extra_group is not None and not isinstance(self.extra_group, str):
            raise TypeError("extra_group must be a string or None")


@dataclass
class Conversion:
    from_type: str
    to_type: str
    ratio: float

    def __post_init__(self) -> None:
        self.from_type = _damage_type(self.from_type, "from_type")
        self.to_type = _damage_type(self.to_type, "to_type")
        self.ratio = _number(self.ratio, "ratio")
        if not 0 <= self.ratio <= 1:
            raise ValueError("ratio must be between 0 and 1")


@dataclass
class ComponentResult:
    current_type: str
    source_type_history: List[str]
    base_value: float
    increased_sum: float
    extra_groups: dict[Optional[str], float]
    final_value: float


@dataclass
class HitDamageResult:
    components: List[ComponentResult]
    total_value: float
    trace: List[str]
