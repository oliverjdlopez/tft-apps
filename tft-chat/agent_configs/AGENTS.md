# Agent documentation router


## Load documentation

Before completing a task, first gather the related repository documentation.

1. Identify the affected paths and task type.
2. Read this file and every nested `AGENTS.md` governing those paths.
3. Use the routing tables below to select the closest subsystem documentation and workflow.
4. Initially load no more than three documentation pages unless the change clearly spans more subsystems.
5. Follow links to adjacent documentation only when the implementation crosses that boundary.
6. Inspect the current source and tests before relying on documentation; code, tests, build configuration, and CI are authoritative.
7. Avoid unrelated documentation. Report documentation mismatches rather than silently preserving stale claims.



## Code standards

- Use Google-style docstrings for every function and model; explain its purpose and where it is applied.
- Add targeted inline comments wherever a reviewer may struggle to follow non-obvious code. Examples include unusual initialization, loop priming, complex expressions, and multi-function pipelines; this list is not exhaustive.
- Good comments explain why the code exists or takes a particular approach, rather than merely restating it. Explaining what the code does is still useful when that context implicitly communicates the why.
- Optimize modules for intent-first reading. Readability outweighs keeping helper implementations nearby when their names already explain their behavior.
- Put data models in `models.py` unless they implement surprising, inseparable behavior.
- Keep lightweight type aliases composed only from typing constructs such as
  `Annotated`, `Literal`, and collection types in the module that uses them
  when they are used by only that one module. Reserve `models.py` for data
  models and aliases shared across module boundaries.
- Move self-explanatory implementation helpers to the single `utils.py` in their
  package, even when they are used by only one module. Never create parallel
  module-named utility files such as `query_utils.py`, `model_utils.py`, or
  `foo_utils.py` alongside it. When one `utils.py` supports several purpose
  modules, separate each module's helpers with a prominent five- or six-line
  comment banner that names the purpose module; use local imports when needed
  to keep the consolidated module free of circular imports.
- Functions left in a purpose module should be first-class operations of that module, not underscore-prefixed implementation details.



