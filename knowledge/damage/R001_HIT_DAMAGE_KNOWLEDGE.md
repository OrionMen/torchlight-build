# R001 Hit Damage Knowledge

Status: confirmed working interpretation for first prototype

## Scope

This document covers only player-created hit damage before target defenses.

Excluded for now:

- damage over time
- indirect damage
- reflected damage
- true damage
- critical strikes
- double damage
- resistance and armor
- hit frequency and cooldown

## Source basis

Primary extracted help topics:

- Damage Calculation
- Damage Type Conversion
- Stacks and Multiplication Rules
- Attack
- Spell
- Skill Level

The original extracted help files remain external source material. This file records the current project interpretation.

## Confirmed concepts

### Damage components

A hit is represented as one or more typed damage components:

- physical
- lightning
- cold
- fire
- erosion

### Increased modifiers

All applicable non-extra percentage modifiers are additive inside one pool for a given component.

Example:

- base physical damage: 100
- increased physical damage: 50%
- increased attack damage: 30%

Result before extra multipliers:

```text
100 * (1 + 0.50 + 0.30) = 180
```

Damage tags only determine whether a modifier applies. Different matching tags do not create separate multipliers.

### Extra multipliers

Extra increases and extra reductions are multiplicative groups after the increased pool. Exact grouping rules will be frozen in a later specification. R001 only provides a generic ordered multiplier list.

### Damage conversion

Conversion splits damage rather than renaming the whole source component.

Example:

- 100 physical base damage
- 50% physical converted to fire

Produces:

- 50 physical
- 50 fire

Converted damage retains source-type history. A converted physical-to-fire component can match both physical and fire increased modifiers.

Example confirmed by user:

- 100 physical
- 100% physical converted to fire
- +100% physical damage
- +100% fire damage

Result:

```text
100 * (1 + 1.00 + 1.00) = 300 fire damage
```

It is not 400 and not 200.

## Ownership and scope

Every modifier has an owner and scope. R001 supports the data fields but does not yet resolve a full build graph.

Typical scopes:

- character_global
- skill_local
- generated_skill_local

A skill calculation may read both character-global and matching skill-local modifiers. Local modifiers belonging to another skill instance must not apply.

## Open questions deferred from R001

- exact extra-modifier grouping semantics
- chained conversion beyond the first confirmed examples
- conversion priority and overflow normalization
- base damage source construction for attack vs spell
- added flat damage and weapon effectiveness
- critical strike and double damage ordering
- defense pipeline
