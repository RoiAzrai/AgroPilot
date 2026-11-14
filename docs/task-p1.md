# P1 - Registry service API

In this task you will implement the AgroPilot registry API in `services/registry-service`. The service already exposes `GET /health`. You add farms, plots, the catalogues, the database, and tests.

Work in your own AgroPilot repo. Setup is in the [Python environment tutorial](../tutorials/python_env.md).


## Spec

### Functional requirements

- **FR-1.1** Create, read, update, and delete farms and plots.
- **FR-1.2** Read-only catalogues for crops, soils, and emitters. They are already in the seed file. Any other method on those routes returns `405`.
- **FR-1.3** Reject a plot when `area_m2` is not greater than 0, either spacing is not greater than 0, `planting_date` is in the future, or the crop, soil, or emitter is not in the catalogue. `lat` must be from -90 to 90. `lon` must be from -180 to 180.
- **FR-1.4** Every error response is `application/problem+json` as defined by [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457), with a stable `code` of `VALIDATION`, `NOT_FOUND`, `CONFLICT`, or `UNAVAILABLE`.

### Non-functional requirements

- **NFR-1.1** `GET` list and `GET` by id: p95 `<= 100 ms` at 10 requests per second. Measure it. Write the number in the pull request.

### Data

Return only the fields listed here.

**Farm:** `id` (UUID), `name` (non-empty string).

**Plot:** `id` (UUID), `farm_id`, `name`, `area_m2`, `crop_id`, `planting_date` (`YYYY-MM-DD`), `soil_id`, `row_spacing_m`, `emitter_spacing_m`, `emitter_id`, `lat`, `lon`.

A plot name is unique inside one farm. The same name on another farm is allowed.

**Crops**

| id | name |
| --- | --- |
| `tomato` | Tomato |
| `bell-pepper` | Bell pepper |

**Soils**

| id | name | `available_water_mm_per_m` |
| --- | --- | --- |
| `sand` | Sand | 83 |
| `loam` | Loam | 175 |
| `clay-loam` | Clay loam | 200 |

`available_water_mm_per_m` is how much water that soil can hold for the plants, written as a depth of water in millimetres.


**Emitters**

| id | name | `flow_lph` (litres per hour) |
| --- | --- | --- |
| `dripnet-pc-0.6` | DripNet PC | 0.6 |
| `dripnet-pc-1.0` | DripNet PC | 1.0 |
| `dripnet-pc-1.6` | DripNet PC | 1.6 |
| `dripnet-pc-2.0` | DripNet PC | 2.0 |



### Database

The database is one SQLite file, `registry.db`, in `services/registry-service`.

To seed your database with initial values, copy [seed_registry.sh](seed_registry.sh) into that folder and run it:

```bash
bash seed_registry.sh
```

The script creates the file and loads **15 rows**:

- 2 crops, 3 soils, 4 emitters (the tables above)
- 2 farms, 4 plots

| Farm | Plot | Crop | Area | Soil | Emitter |
| --- | --- | --- | --- | --- | --- |
| Demo cooperative | North block | tomato | 1000 m² | loam | 1.0 L/h |
| Demo cooperative | East block | bell pepper | 800 m² | clay loam | 1.6 L/h |
| East farm | West block | tomato | 1500 m² | sand | 0.6 L/h |
| East farm | Greenhouse | bell pepper | 400 m² | loam | 2.0 L/h |

Run it again any time you want a clean file. It deletes `registry.db` and writes a new one.

### API

Lists are JSON arrays. No rows means `200` and `[]`.

| Method | Path | Success |
| --- | --- | --- |
| `POST` | `/v1/farms` | `201` |
| `GET` | `/v1/farms` | `200` |
| `GET` | `/v1/farms/{id}` | `200` |
| `PATCH` | `/v1/farms/{id}` | `200` |
| `DELETE` | `/v1/farms/{id}` | `204` |
| `POST` | `/v1/plots` | `201` |
| `GET` | `/v1/plots` | `200` |
| `GET` | `/v1/plots/{id}` | `200` |
| `PATCH` | `/v1/plots/{id}` | `200` |
| `DELETE` | `/v1/plots/{id}` | `204` |
| `GET` | `/v1/crops` | `200` |
| `GET` | `/v1/crops/{id}` | `200` |
| `GET` | `/v1/soils` | `200` |
| `GET` | `/v1/soils/{id}` | `200` |
| `GET` | `/v1/emitters` | `200` |
| `GET` | `/v1/emitters/{id}` | `200` |

`GET /v1/plots?farm_id={id}` returns that farm's plots. With no query, return every plot.

`PATCH` changes only the fields in the body.

`POST /v1/plots` body:

```json
{
  "farm_id": "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001",
  "name": "South block",
  "area_m2": 1000,
  "crop_id": "tomato",
  "planting_date": "2026-03-01",
  "soil_id": "loam",
  "row_spacing_m": 1.5,
  "emitter_spacing_m": 0.4,
  "emitter_id": "dripnet-pc-1.0",
  "lat": 31.25,
  "lon": 34.79
}
```

`201` returns that object plus `id`.

`GET /v1/emitters/dripnet-pc-1.0`:

```json
{ "id": "dripnet-pc-1.0", "name": "DripNet PC", "flow_lph": 1.0 }
```

`GET /v1/soils/sand`:

```json
{ "id": "sand", "name": "Sand", "available_water_mm_per_m": 83 }
```

`GET /v1/crops/tomato`:

```json
{ "id": "tomato", "name": "Tomato" }
```


Failures:

- Bad field, or unknown crop, soil, or emitter: `422`, `code`: `VALIDATION`.
- Duplicate plot name on the same farm: `409`, `code`: `CONFLICT`.
- Delete a farm that still has plots: `409`, `code`: `CONFLICT`.
- Unknown id: `404`, `code`: `NOT_FOUND`.
- Database unreachable: `503`, `code`: `UNAVAILABLE`, and a `Retry-After` header.

Every error is `application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Unprocessable Entity",
  "status": 422,
  "detail": "Unknown emitter",
  "code": "VALIDATION"
}
```

`code` is one of `VALIDATION`, `NOT_FOUND`, `CONFLICT`, `UNAVAILABLE`.


### Docs you also write

- A short service README.
- `docs/judgment-log.md` with at least two entries. Each entry: what your coding AI agent suggested, what you decided, and why.


## Learn the domain first

You may be meeting new terms for the first time. That is expected.

This is what the first month of a job feels like. 

Talk with ChatGPT, or another chat, to clarify the domain, ask for a small example with numbers.

## Use a coding agent

Build this with a coding agent: Claude Code, GitHub Copilot, Cursor, Codex, you choose.

Use a small model, such as Haiku, you don't need more than that.

**You own the code**. Read every file. Delete every functionality that the task does not list.

# Good Luck!
