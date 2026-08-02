from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Optional

from .models import (
    CalculationContext,
    CapabilityContribution,
    MechanicResolution,
    Modifier,
    ModifierAggregationResult,
    TraceEntry,
    finite_number,
    non_empty_string,
    normalized_filters,
)


def match_filters(
    filters: object,
    context: Optional[CalculationContext],
) -> tuple[bool, Optional[str]]:
    """按固定顺序独立检查技能标签与伤害类型过滤器。"""

    active = normalized_filters(filters)
    if context is None:
        if any(active.values()):
            return False, "calculation context is required"
        return True, None

    tags = context.effective_skill_tags
    required_all = frozenset(active.get("skill_tags_all", ()))
    missing = sorted(required_all - tags)
    if missing:
        return False, "missing skill_tags_all: " + ", ".join(missing)

    required_any = frozenset(active.get("skill_tags_any", ()))
    if required_any and required_any.isdisjoint(tags):
        return False, "no skill_tags_any matched"

    forbidden = sorted(frozenset(active.get("skill_tags_none", ())) & tags)
    if forbidden:
        return False, "matched skill_tags_none: " + ", ".join(forbidden)

    damage_types = frozenset(active.get("damage_types", ()))
    if damage_types and context.damage_type not in damage_types:
        return False, "damage_type did not match"
    return True, None


def _original_text(source: object) -> Optional[str]:
    return getattr(source, "original_text", None) if source is not None else None


def aggregate_modifiers(
    modifiers: Sequence[Modifier],
    context: CalculationContext,
) -> ModifierAggregationResult:
    """过滤后按 target_node 与 aggregation_key 合并加减贡献。"""

    if any(not isinstance(item, Modifier) for item in modifiers):
        raise TypeError("modifiers must contain only Modifier objects")
    if not isinstance(context, CalculationContext):
        raise TypeError("context must be CalculationContext")

    groups: dict[str, dict[str, float]] = {}
    trace: list[TraceEntry] = []
    for modifier in modifiers:
        matched, reason = match_filters(modifier.filters, context)
        contribution = 0.0
        if matched:
            contribution = modifier.value if modifier.operation == "add" else -modifier.value
            node_groups = groups.setdefault(modifier.target_node, {})
            node_groups[modifier.aggregation_key] = (
                node_groups.get(modifier.aggregation_key, 0.0) + contribution
            )
        trace.append(
            TraceEntry(
                entry_type="modifier",
                source_id=modifier.id,
                original_text=_original_text(modifier.source),
                matched=matched,
                rejection_reason=reason,
                target_node=modifier.target_node,
                aggregation_key=modifier.aggregation_key,
                contributed_value=contribution,
            )
        )

    ordered_groups = {
        node: {key: groups[node][key] for key in sorted(groups[node])}
        for node in sorted(groups)
    }
    node_values = {
        node: sum(group_values.values()) for node, group_values in ordered_groups.items()
    }
    return ModifierAggregationResult(ordered_groups, node_values, trace)


def calculate_extra_groups_multiplier(
    groups: Mapping[str, object],
) -> float:
    """组内先相加形成 1 + sum(group)，各组再按 key 顺序相乘。"""

    if not isinstance(groups, Mapping):
        raise TypeError("groups must be a mapping")
    result = 1.0
    for group_id in sorted(groups):
        non_empty_string(group_id, "aggregation_key")
        raw_values = groups[group_id]
        if isinstance(raw_values, bool):
            raise TypeError("group values must be numbers or iterables of numbers")
        if isinstance(raw_values, (int, float)):
            group_sum = finite_number(raw_values, f"group {group_id}")
        else:
            if isinstance(raw_values, (str, bytes)):
                raise TypeError("group values must be numbers or iterables of numbers")
            try:
                values = list(raw_values)  # type: ignore[arg-type]
            except TypeError as exc:
                raise TypeError("group values must be numbers or iterables of numbers") from exc
            group_sum = sum(
                finite_number(value, f"group {group_id} value") for value in values
            )
        multiplier = 1 + group_sum
        if multiplier < 0:
            raise ValueError(f"aggregation group {group_id} has a multiplier below zero")
        result *= multiplier
    return result


def resolve_mechanic(
    *,
    mechanic_id: str,
    base_maximum: float,
    capability_sources: Sequence[object],
    maximum_modifiers: Sequence[object],
    context: Optional[CalculationContext] = None,
    policy: str = "max_reachable",
) -> MechanicResolution:
    """按“具备获取能力则采用有效上限，否则为零”解析静态机制。"""

    mechanic_id = non_empty_string(mechanic_id, "mechanic_id")
    if policy != "max_reachable":
        raise ValueError("only max_reachable policy is supported")
    base = finite_number(base_maximum, "base_maximum")
    if base < 0:
        raise ValueError("base_maximum must be non-negative")

    trace: list[TraceEntry] = []
    capability_available = False
    for index, source in enumerate(capability_sources):
        if isinstance(source, str):
            source_id = non_empty_string(source, "capability source")
            matched, reason = True, None
            original_text = None
        elif isinstance(source, CapabilityContribution):
            source_id = source.id
            original_text = _original_text(source.source)
            if source.mechanic_id != mechanic_id:
                matched, reason = False, "mechanic_id did not match"
            elif source.capability_type != "acquire":
                matched, reason = False, "capability_type is not acquire"
            else:
                matched, reason = match_filters(source.filters, context)
        else:
            raise TypeError("capability_sources must contain strings or CapabilityContribution")
        capability_available = capability_available or matched
        trace.append(
            TraceEntry(
                entry_type="capability",
                source_id=source_id,
                original_text=original_text,
                matched=matched,
                rejection_reason=reason,
                target_node=mechanic_id,
                aggregation_key=f"{mechanic_id}.acquire",
                contributed_value=1.0 if matched else 0.0,
            )
        )

    maximum_delta = 0.0
    maximum_node = f"{mechanic_id}.maximum"
    for index, modifier in enumerate(maximum_modifiers):
        if isinstance(modifier, bool):
            raise TypeError("maximum modifiers must be numbers or Modifier objects")
        if isinstance(modifier, (int, float)):
            source_id = f"maximum_modifier[{index}]"
            original_text = None
            matched, reason = True, None
            contribution = finite_number(modifier, source_id)
            aggregation_key = maximum_node
        elif isinstance(modifier, Modifier):
            source_id = modifier.id
            original_text = _original_text(modifier.source)
            matched, reason = match_filters(modifier.filters, context)
            contribution = 0.0
            if matched:
                contribution = modifier.value if modifier.operation == "add" else -modifier.value
            aggregation_key = modifier.aggregation_key
        else:
            raise TypeError("maximum modifiers must be numbers or Modifier objects")
        if matched:
            maximum_delta += contribution
        trace.append(
            TraceEntry(
                entry_type="modifier",
                source_id=source_id,
                original_text=original_text,
                matched=matched,
                rejection_reason=reason,
                target_node=maximum_node,
                aggregation_key=aggregation_key,
                contributed_value=contribution,
            )
        )

    effective_maximum = base + maximum_delta
    if effective_maximum < 0:
        raise ValueError("effective maximum must be non-negative")
    assumed_value = effective_maximum if capability_available else 0.0
    return MechanicResolution(
        mechanic_id=mechanic_id,
        capability_available=capability_available,
        base_maximum=base,
        maximum_delta=maximum_delta,
        effective_maximum=effective_maximum,
        assumed_value=assumed_value,
        policy=policy,
        trace=trace,
    )
