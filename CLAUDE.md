# Code Conventions

## Documentation stack

- Sphinx with **MyST-Parser** (documentation pages are `.md` files, not `.rst`)
- `sphinx.ext.napoleon` renders docstrings
- `sphinx.ext.autodoc` + `autosummary` build the API reference
- `sphinx.ext.intersphinx` links to Python, NumPy, pandas, SciPy, Matplotlib

## Docstrings

All docstrings must use **NumPy style**.

- Public functions/classes: full NumPy-style docstring with at minimum a
  summary line, `Parameters`, and `Returns` sections.
- Private helpers (`_name`): a one-liner is sufficient.
- Include physical units in brackets: `[A]`, `[T]`, `[m]`, `[K]`.
- Use intersphinx cross-references for well-known types:
  `:class:`~pandas.DataFrame``, `:class:`~numpy.ndarray``,
  `:class:`~pathlib.Path``.
- When writing new code or modifying an existing function, update or add
  its docstring in NumPy style.
- Do **not** use Google style or Sphinx reST field lists (`:param:`, `:type:`).

Example:

```python
def resolve_defs_file(filename: str, user_dir: Path | None = None) -> Path:
    """Resolve a defs filename to a concrete path.

    Parameters
    ----------
    filename : str
        Bare name like ``"pupitre-defs.json"`` or any concrete path.
    user_dir : Path, optional
        Override for the user config directory lookup.

    Returns
    -------
    Path
        Resolved path; always points to an existing file.

    Raises
    ------
    FileNotFoundError
        If the file cannot be found in any search location.
    """
```

## Naming conventions

### New code — PEP 8 strictly

| Construct | Style | Example |
|---|---|---|
| Modules / files | `snake_case` | `housing_config.py` |
| Classes | `PascalCase` | `MagnetRun`, `PandasMagnetData` |
| Functions / methods | `snake_case` | `get_keys`, `clean_data` |
| Properties | `snake_case` | `data`, `unit` |
| Constants | `UPPER_SNAKE` | `USER_CONFIG_DIR` |
| Private helpers | `_snake_case` | `_validate_formula_keys` |

All new code must follow PEP 8. Do not add `# noqa: N802` to new methods.

### Existing camelCase public methods — deprecation shim pattern

The codebase contains legacy camelCase public methods (`getData`, `getKeys`,
`cleanupData`, …) that cannot be renamed without breaking downstream callers.

**Do not rename them silently.** Instead, use the deprecation shim pattern:

1. Implement the real logic under the new `snake_case` name.
2. Keep the old camelCase name as a thin wrapper that emits `DeprecationWarning`.
3. Update internal callers (`self.getX()` within the package) to the new name
   whenever you touch the file.
4. Remove shims only on a major version bump.

```python
import warnings

def get_keys(self) -> list[str]:
    """Return the list of data column keys."""
    ...  # real implementation here

def getKeys(self) -> list[str]:  # noqa: N802
    warnings.warn(
        "getKeys() is deprecated, use get_keys() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return self.get_keys()
```

### Module names

New modules must use `snake_case`. Legacy `PascalCase` module names
(`MagnetRun.py`) are kept as-is to avoid import breakage.

---

## Behavioral guidelines

### Think before coding

- State assumptions explicitly before implementing. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so and push back when warranted.
- If something is unclear, stop and name what's confusing.

### Simplicity first

- Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- No error handling for impossible scenarios.

### Surgical changes

When editing existing code:
- Don't improve adjacent code, comments, or formatting unless asked.
- Match existing style, even if you'd do it differently.
- If unrelated dead code is noticed, mention it — don't delete it.
- Remove only imports/variables/functions that YOUR changes made unused.

Every changed line should trace directly to the user's request.

### Plan-first, act-on-approval (mandatory)

No action that changes state may be taken without an **explicitly approved
plan**. This gate is not optional and applies to every task, however small.

**Allowed without approval (read-only investigation):**
reading files, listing directories, searching/grepping, inspecting git
history, running read-only queries. Use these freely to build the plan.

**Gated behind approval (state-changing actions):**
creating/editing/deleting files, running commands with side effects,
installing dependencies, `git add/commit/push`, database writes, any
network call that mutates remote state.

**Workflow:**

1. Investigate as needed (read-only) to understand the request.
2. Present a plan and then **stop**. Do not proceed in the same turn.
   The plan must include:
   - **Goal** — one sentence restating what success looks like.
   - **Files affected** — explicit paths, and per file: create / edit / delete.
   - **Approach** — the concrete steps, in order.
   - **Verification** — how each step is checked (test, command, expected
     output). When fixing a bug or adding validation, write the test first;
     when refactoring, ensure tests pass before and after.
   - **Assumptions & open questions** — anything uncertain (per the
     "Think before coding" rule).
3. Wait for explicit approval. Approval = the user replying with
   `approve`, `approved`, `go`, `proceed`, or `LGTM`. Anything else
   (questions, edits, silence, "looks good but…") is **not** approval —
   revise and re-present.
4. Execute the approved plan, and only that plan.

Plans for multi-step work use the verifiable step → check format:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

**Re-plan triggers.** Stop and present a revised plan for re-approval if,
mid-execution, any of these occur:
- a file not in the approved list needs to change;
- the approach diverges from what was approved;
- a new assumption or blocker surfaces;
- the user changes the request.

**Do not** bundle the plan and the implementation in one response.
**Do not** treat a question from the user as approval.
**Do not** start coding "to save time" while awaiting approval.
