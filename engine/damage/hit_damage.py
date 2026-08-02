from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Optional

from .models import ComponentResult, Conversion, DamageComponent, HitDamageResult, Modifier


def _format_number(value: float) -> str:
    return format(value, ".12g")


def _conversion_list(conversion: object) -> list[Conversion]:
    if conversion is None:
        return []
    if isinstance(conversion, Conversion):
        return [conversion]
    if isinstance(conversion, Sequence) and not isinstance(conversion, (str, bytes)):
        conversions = list(conversion)
        if any(not isinstance(item, Conversion) for item in conversions):
            raise TypeError("conversion sequence must contain only Conversion objects")
        if len(conversions) > 1:
            raise ValueError("R001 accepts at most one conversion rule")
        return conversions
    raise TypeError("conversion must be a Conversion, a sequence, or None")


def _convert_components(
    components: Sequence[DamageComponent],
    conversion: Optional[Conversion],
    trace: list[str],
) -> list[DamageComponent]:
    if conversion is None:
        trace.append("conversion: none")
        return [
            DamageComponent(item.base_value, item.current_type, item.source_type_history)
            for item in components
        ]

    output: list[DamageComponent] = []
    for index, component in enumerate(components):
        if component.current_type != conversion.from_type:
            output.append(
                DamageComponent(
                    component.base_value,
                    component.current_type,
                    component.source_type_history,
                )
            )
            trace.append(f"conversion[{index}]: unchanged")
            continue

        converted_base = component.base_value * conversion.ratio
        remaining_base = component.base_value - converted_base
        if remaining_base > 0:
            output.append(
                DamageComponent(
                    remaining_base,
                    component.current_type,
                    component.source_type_history,
                )
            )
        if converted_base > 0:
            history = list(component.source_type_history)
            if conversion.to_type not in history:
                history.append(conversion.to_type)
            output.append(DamageComponent(converted_base, conversion.to_type, history))
        trace.append(
            "conversion[{}]: {} {} -> remaining {} + {} {}".format(
                index,
                component.current_type,
                _format_number(component.base_value),
                _format_number(remaining_base),
                conversion.to_type,
                _format_number(converted_base),
            )
        )
    return output


def _matches(modifier: Modifier, component: DamageComponent, tags: frozenset[str]) -> bool:
    if not modifier.required_tags.issubset(tags):
        return False
    if modifier.required_damage_types and not modifier.required_damage_types.intersection(
        component.source_type_history
    ):
        return False
    return True


def calculate_hit_damage(
    *,
    components: Sequence[DamageComponent],
    modifiers: Sequence[Modifier] = (),
    tags: Iterable[str] = (),
    conversion: object = None,
) -> HitDamageResult:
    """Calculate one R001 hit and return component results plus a stable trace."""

    if isinstance(tags, str):
        raise TypeError("tags must be an iterable of strings")
    hit_tags = frozenset(tags)
    if any(not isinstance(tag, str) for tag in hit_tags):
        raise TypeError("tags must contain only strings")
    if any(not isinstance(item, DamageComponent) for item in components):
        raise TypeError("components must contain only DamageComponent objects")
    if any(not isinstance(item, Modifier) for item in modifiers):
        raise TypeError("modifiers must contain only Modifier objects")

    conversions = _conversion_list(conversion)
    trace: list[str] = []
    resulting_components = _convert_components(
        components,
        conversions[0] if conversions else None,
        trace,
    )

    results: list[ComponentResult] = []
    for index, component in enumerate(resulting_components):
        matching = [item for item in modifiers if _matches(item, component, hit_tags)]
        increased_sum = sum(item.value for item in matching if item.kind == "increased")
        value = component.base_value * (1 + increased_sum)

        grouped: dict[Optional[str], float] = {}
        for modifier in matching:
            if modifier.kind == "extra":
                grouped[modifier.extra_group] = grouped.get(modifier.extra_group, 0.0) + modifier.value
        ordered_groups: dict[Optional[str], float] = {}
        for group in sorted(grouped, key=lambda item: (item is not None, item or "")):
            group_sum = grouped[group]
            multiplier = 1 + group_sum
            if multiplier < 0:
                raise ValueError(f"extra group {group!r} has a multiplier below zero")
            ordered_groups[group] = group_sum
            value *= multiplier

        results.append(
            ComponentResult(
                current_type=component.current_type,
                source_type_history=list(component.source_type_history),
                base_value=component.base_value,
                increased_sum=increased_sum,
                extra_groups=ordered_groups,
                final_value=value,
            )
        )
        history = ",".join(component.source_type_history)
        trace.append(
            f"component[{index}]: type={component.current_type} "
            f"history={history} base={_format_number(component.base_value)} "
            f"increased={_format_number(increased_sum)}"
        )
        for group, group_sum in ordered_groups.items():
            trace.append(
                f"component[{index}].extra[{group!r}]={_format_number(group_sum)}"
            )
        trace.append(f"component[{index}].final={_format_number(value)}")

    total_value = sum(item.final_value for item in results)
    trace.append(f"total={_format_number(total_value)}")
    return HitDamageResult(results, total_value, trace)
