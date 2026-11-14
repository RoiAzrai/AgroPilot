---
name: registry-api
description: How we build endpoints in the AgroPilot registry-service (FastAPI, SQLite). Use whenever you add, change, review, or test an endpoint, route, request or response model, status code, or error response in services/registry-service, even if the request does not mention errors, tests, or conventions.
---

# Registry API conventions

The spec is [docs/task-p1.md](../../../docs/task-p1.md). Decisions on cases the spec leaves open are in [docs/judgment-log.md](../../../docs/judgment-log.md). Read both before changing behavior, and follow the log instead of re-deciding.

## Rules

- **Every route is under `/v1`.** Clients build URLs from this prefix. A route outside it breaks versioning.
- **Lists are JSON arrays. No rows means `200` and `[]`, never `404`.** An empty result is a valid answer. A filter that matches nothing is an empty list too.
- **Return only the fields the spec lists. Never add fields on your own.** Other services read these responses, and every extra field becomes something we cannot remove later. Set `response_model` on every route so FastAPI drops anything else.
- **`PATCH` changes only the fields in the body.** Use `body.model_dump(exclude_unset=True)` and `merge()` from `models.py`. `{}` returns `200` with the unchanged record. `null` for a required field returns `422`.
- **Every error is `application/problem+json` (RFC 9457) with a stable `code`.** Clients branch on `code`, not on the text of `detail`. Never return FastAPI's default `{"detail": ...}` body.
- **Every endpoint gets tests: the success case and every failure case it can return.** A failure path without a test is a failure path nobody has seen work.
- **Run `uv run pytest` from `services/registry-service` before saying the work is done.** Report the result. If tests fail, say so.
- **If the spec does not say what to do in some case, ask. Don't invent behavior.** Examples: what to return for a farm with no plots, the name or unit of a new field. Behavior we ship becomes a contract.

## Errors

| Situation | Status | `code` |
| --- | --- | --- |
| Bad field, unknown crop/soil/emitter/farm in the body | 422 | `VALIDATION` |
| Unknown id in the path (also a path id that is not a UUID) | 404 | `NOT_FOUND` |
| Duplicate plot name in a farm, delete a farm that has plots | 409 | `CONFLICT` |
| Database unavailable | 503 + `Retry-After` header | `UNAVAILABLE` |

Body:

```json
{
  "type": "about:blank",
  "title": "Unprocessable Entity",
  "status": 422,
  "detail": "Unknown emitter",
  "code": "VALIDATION"
}
```

How to produce them:

- Raise `not_found()`, `conflict()` or `validation()` from `errors.py`. Don't raise `HTTPException` and don't build JSON by hand: the handlers in `errors.py` render every error in one place, so the format stays the same everywhere.
- 503, request validation, 404/405 from routing, and UNIQUE violations are already handled globally. Don't catch them in the endpoint.
- A FOREIGN KEY failure means different things per endpoint (422 on a plot write, 409 on a farm delete), so handle it in the endpoint. Check referenced ids first with `check_references()` in `routers/plots.py`: SQLite's error doesn't say which column failed, and the client needs a clear `detail`.
- Turn path ids into canonical form with `canonical_uuid()`. If it returns `None`, return 404.

## Request models

Request bodies inherit from `RequestBody` in `models.py` (`extra="forbid"`), so an unknown field returns 422 instead of being silently ignored.

## Tests

- Use the `client` fixture from `tests/conftest.py`. It seeds a temporary database, so tests never touch the real `registry.db`.
- Check every error with `assert_problem(response, status, code)` from `conftest.py`. It checks the status, the `Content-Type`, the exact set of body fields, and the `code`.
- On success, check the exact response body or its exact set of keys, so an extra field fails the test.
