from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Mapping, Optional, Tuple


FILTER_KEYS = frozenset(
    {"skill_tags_all", "skill_tags_any", "skill_tags_none", "damage_types"}
)
OPERATIONS = frozenset({"add", "subtract"})


def finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def normalized_filters(filters: object) -> Dict[str, Tuple[str, ...]]:
    if filters is None:
        return {}
    if not isinstance(filters, Mapping):
        raise TypeError("filters must be a mapping")
    normalized: Dict[str, Tuple[str, ...]] = {}
    for key, raw_values in filters.items():
        if key not in FILTER_KEYS:
            continue
        if isinstance(raw_values, str):
            raise TypeError(f"filter {key} must be a sequence of strings")
        try:
            values = tuple(raw_values)
        except TypeError as exc:
            raise TypeError(f"filter {key} must be a sequence of strings") from exc
        if any(not isinstance(item, str) for item in values):
            raise TypeError(f"filter {key} must contain only strings")
        normalized[key] = values
    return normalized


@dataclass
class CalculationContext:
    """静态过滤上下文；技能标签与伤害类型保持相互独立。"""

    effective_skill_tags: FrozenSet[str]
    damage_type: str

    def __post_init__(self) -> None:
        if isinstance(self.effective_skill_tags, str):
            raise TypeError("effective_skill_tags must be a set of strings")
        self.effective_skill_tags = frozenset(self.effective_skill_tags)
        if any(not isinstance(tag, str) for tag in self.effective_skill_tags):
            raise TypeError("effective_skill_tags must contain only strings")
        self.damage_type = non_empty_string(self.damage_type, "damage_type")


@dataclass
class SourceTrace:
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    location: Optional[str] = None
    original_text: Optional[str] = None

    def __post_init__(self) -> None:
        for field_name in ("entity_type", "entity_id", "location", "original_text"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"source.{field_name} must be a string or None")


@dataclass
class Modifier:
    """对计算节点的一次可过滤写入声明。"""

    id: str
    target_node: str
    aggregation_key: str
    operation: str
    value: float
    filters: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    source: Optional[SourceTrace] = None

    def __post_init__(self) -> None:
        self.id = non_empty_string(self.id, "id")
        self.target_node = non_empty_string(self.target_node, "target_node")
        self.aggregation_key = non_empty_string(self.aggregation_key, "aggregation_key")
        if self.operation not in OPERATIONS:
            raise ValueError("operation must be add or subtract")
        self.value = finite_number(self.value, "value")
        self.filters = normalized_filters(self.filters)
        if isinstance(self.source, Mapping):
            self.source = SourceTrace(**self.source)
        elif self.source is not None and not isinstance(self.source, SourceTrace):
            raise TypeError("source must be SourceTrace, a mapping, or None")


@dataclass
class CapabilityContribution:
    """某机制的获取能力来源。"""

    id: str
    mechanic_id: str
    capability_type: str = "acquire"
    filters: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    source: Optional[SourceTrace] = None

    def __post_init__(self) -> None:
        self.id = non_empty_string(self.id, "id")
        self.mechanic_id = non_empty_string(self.mechanic_id, "mechanic_id")
        self.capability_type = non_empty_string(self.capability_type, "capability_type")
        self.filters = normalized_filters(self.filters)
        if isinstance(self.source, Mapping):
            self.source = SourceTrace(**self.source)
        elif self.source is not None and not isinstance(self.source, SourceTrace):
            raise TypeError("source must be SourceTrace, a mapping, or None")


@dataclass(frozen=True)
class TraceEntry:
    entry_type: str
    source_id: str
    original_text: Optional[str]
    matched: bool
    rejection_reason: Optional[str]
    target_node: str
    aggregation_key: str
    contributed_value: float


@dataclass
class ModifierAggregationResult:
    groups: Dict[str, Dict[str, float]]
    node_values: Dict[str, float]
    trace: List[TraceEntry]


@dataclass
class MechanicResolution:
    mechanic_id: str
    capability_available: bool
    base_maximum: float
    maximum_delta: float
    effective_maximum: float
    assumed_value: float
    policy: str
    trace: List[TraceEntry]
