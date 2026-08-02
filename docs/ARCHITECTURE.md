# Architecture

## Core flow

```text
Knowledge
  -> Specification
  -> Engine
  -> Application
```

## Responsibilities

### Knowledge

Stores source-backed understanding, terminology, assumptions, confidence, and unresolved questions.

### Specification

The executable contract for the engine. Engine code must follow frozen specifications and must not infer game behavior that is absent from them.

### Engine

Pure calculation and simulation code. It must be deterministic, testable, and independent from UI concerns.

### Application

Viewers, analyzers, build tools, and future optimizers. Applications consume engine output but do not redefine game rules.

## Source of truth

- Raw and parsed source data preserve what the source says.
- Knowledge records our current interpretation.
- Frozen specification files are the source of truth for engine behavior.
- Engine code must not modify or reinterpret specifications.

## Development workflow

1. Read and classify source material.
2. Draft knowledge notes.
3. Freeze a narrow specification.
4. Define executable examples.
5. Ask Codex to implement only that specification.
6. Run only the tests named by the task.
7. Review results before Git commit.
