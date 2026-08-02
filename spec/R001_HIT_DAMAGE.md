# R001 Hit Damage

Status: Frozen v1

## 1. Purpose

Implement the smallest deterministic hit-damage calculation core needed to validate:

- typed base damage components
- tag-filtered increased modifiers
- ordered extra multiplier groups
- one-step damage-type conversion
- source-type history for converted damage

## 2. Non-goals

Do not implement:

- damage over time
- indirect, reflected, or true damage
- critical strike
- double damage
- armor, resistance, penetration, or mitigation
- attack speed, cast speed, cooldown, or DPS
- equipment, skill, hero, or talent loading
- UI
- database persistence
- chained conversion
- conversion priority ordering
- overflow normalization above 100%

## 3. Damage types

The engine must support exactly these identifiers:

```text
physical
lightning
cold
fire
erosion
```

## 4. Data model

### 4.1 DamageComponent

Required fields:

```text
base_value: non-negative number
current_type: damage type
source_type_history: ordered unique list of damage types
```

For an unconverted component, `source_type_history` must include its own type.

Example:

```json
{
  "base_value": 100,
  "current_type": "physical",
  "source_type_history": ["physical"]
}
```

Converted physical-to-fire component:

```json
{
  "base_value": 50,
  "current_type": "fire",
  "source_type_history": ["physical", "fire"]
}
```

### 4.2 Modifier

Required fields:

```text
kind: increased | extra
value: decimal ratio
required_tags: set of strings
required_damage_types: set of damage types
owner_scope: character_global | skill_local | generated_skill_local
owner_id: nullable string
extra_group: nullable string
```

Rules:

- `value=0.50` means +50%.
- An empty filter set means no restriction for that filter.
- R001 receives only modifiers already visible to the current skill context.
- The calculator still evaluates tag and damage-type matching.

### 4.3 Conversion

Required fields:

```text
from_type: damage type
to_type: damage type
ratio: decimal from 0 to 1 inclusive
```

R001 accepts at most one conversion rule per calculation.

## 5. Modifier matching

A modifier applies to a component only if all conditions below are true:

1. `required_tags` is a subset of the hit's tag set.
2. If `required_damage_types` is non-empty, it intersects the component's `source_type_history`.

A converted component therefore may match modifiers for any type in its source history.

## 6. Conversion

Given a component whose `current_type` matches `from_type`:

```text
converted_base = base_value * ratio
remaining_base = base_value - converted_base
```

Output:

- retain the remaining component when `remaining_base > 0`
- create a converted component when `converted_base > 0`
- converted history is original history followed by `to_type`, without duplicates

Components of other current types are unchanged.

R001 must reject:

- ratio below 0
- ratio above 1
- multiple conversion rules

## 7. Increased calculation

For each resulting component:

```text
increased_sum = sum(value of every matching modifier where kind=increased)
value_after_increased = base_value * (1 + increased_sum)
```

All matching increased modifiers share one additive pool.

## 8. Extra multiplier groups

For each resulting component:

1. Select matching modifiers where `kind=extra`.
2. Group them by `extra_group`.
3. Within each group, sum their values.
4. Apply each group as one ordered multiplier:

```text
component_result = value_after_increased * product(1 + group_sum)
```

For v1, group ordering must be deterministic by lexicographic group id. Multiplication is mathematically commutative, but deterministic ordering makes tracing stable.

An extra group may be negative. The calculator must reject any group whose final multiplier is below zero.

## 9. Output

Return a calculation result containing:

```text
components:
  - current_type
  - source_type_history
  - base_value
  - increased_sum
  - extra_groups
  - final_value

total_value
trace
```

`total_value` is the sum of all component final values.

The trace must be concise and deterministic. It must not depend on UI formatting.

## 10. Precision

Use normal floating-point arithmetic for this prototype.

Tests should compare with a small tolerance rather than exact binary equality.

## 11. Required examples

### Case A: increased modifiers are additive

Input:

- 100 physical
- hit tags: attack, melee, hit
- +50% physical increased
- +30% attack increased

Expected:

```text
180 physical
total 180
```

### Case B: different matching tags do not create separate multipliers

Input:

- 100 physical
- hit tags: attack, melee, area, hit
- +50% attack increased
- +40% melee increased
- +30% area increased

Expected:

```text
220 physical
total 220
```

### Case C: full conversion retains source history

Input:

- 100 physical
- 100% physical to fire
- +100% physical increased
- +100% fire increased

Expected:

```text
300 fire
total 300
history [physical, fire]
```

### Case D: partial conversion

Input:

- 100 physical
- 50% physical to fire
- +100% physical increased
- +50% fire increased

Expected:

```text
100 physical
125 fire
total 225
```

### Case E: extra groups multiply after increased

Input:

- 100 physical
- +50% physical increased
- extra group hero: +20%
- extra group skill: +30%

Expected:

```text
100 * 1.5 * 1.2 * 1.3 = 234
total 234
```

## 12. Change policy

Changes to behavior require a new specification version. Engine code must not silently extend this document.
