---
paths:
  - "services/registry-service/**/*.py"
---

# Registry service rules

- Every request body is a Pydantic model. Never use a `dict` or loose parameters.
- Every numeric field has a constraint (`gt=0` or `ge=0`). No unbounded numbers.
- Every endpoint needs a test in `tests/`, including at least one invalid-input case.