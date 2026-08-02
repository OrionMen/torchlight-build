# TASK R001 Engine

Execute in Fast Mode and Low Token Mode.

## Goal

Implement the frozen specification:

```text
spec/R001_HIT_DAMAGE.md
```

## Read only

Read only:

- `tasks/task_r001.json`
- `spec/R001_HIT_DAMAGE.md`
- `tests/spec_cases/R001_hit_damage_cases.json`
- existing files under `engine/damage/` if present
- existing files under `tests/engine/damage/` if present
- `PROJECT_STATE.md` only when updating status

Do not read the full knowledge file unless the frozen specification is internally inconsistent. The spec is the implementation source of truth.

Do not scan the full repository.

## Implement

Use Python standard library only.

Create the smallest clear implementation under:

```text
engine/damage/
```

Recommended files, but adjust only if necessary:

```text
engine/__init__.py
engine/damage/__init__.py
engine/damage/models.py
engine/damage/hit_damage.py
```

Create unit tests under:

```text
tests/engine/damage/
```

The public API must be simple enough for later application code to call without importing test helpers.

## Required behavior

Implement only R001:

- damage types
- damage components
- modifier filtering by tags and source-type history
- additive increased pool
- grouped extra multipliers
- zero or one conversion rule
- deterministic trace
- validation required by the spec

Do not implement later mechanics.

## Test data

Use:

```text
tests/spec_cases/R001_hit_damage_cases.json
```

Tests must cover all cases in that file and core validation errors.

## Run

Run only:

```bash
python3 -m unittest discover -s tests/engine/damage -p 'test_*.py'
```

Do not run build, lint, pytest, or the full test suite.

## Project state

If and only if tests pass, minimally update `PROJECT_STATE.md` to record:

- R001 hit damage prototype implemented
- R001 focused unit tests passing
- next rule remains extra-damage grouping refinement / later hit mechanics

Do not rewrite unrelated sections.

## Forbidden

- Do not modify `spec/`.
- Do not modify `knowledge/`.
- Do not modify crawler, raw data, parsed data, reports, or app UI.
- Do not install dependencies.
- Do not commit or push Git.
- Do not expand beyond R001.

## Final response

Return only:

```text
Installed patch files:
- ...

Modified code files:
- ...

Implementation summary:
- ...

Test result:
- command:
- result:

Not executed:
- build
- lint
- full test suite
- git commit
- git push
```
