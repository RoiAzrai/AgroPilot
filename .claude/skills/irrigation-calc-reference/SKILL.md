---
name: irrigation-calc-reference
description: The irrigation math of the AgroPilot planner-service (FAO-56: ET0, Kc, the soil bucket, drip minutes) and the decisions we made. Use whenever you write, change, test or explain any calculation in planner-service: kc, root depth, TAW/RAW, the daily bucket, rain, litres, run_minutes, bucket_start, or the bucket suggestion.
---

# Irrigation calculation reference

The spec is [docs/task-p2.md](../../../docs/task-p2.md). The FAO-56 sources (chapter, table and equation numbers, with URLs) are in [services/planner-service/docs/research/fao56.md](../../../services/planner-service/docs/research/fao56.md). Hand-calculated cases to test against are in [references/cases.md](references/cases.md). The decisions we made, and where we deviate from the task or FAO-56, are in [references/decisions.md](references/decisions.md). Follow these files. Don't re-decide.

FR-2.11: every number in the plan is calculated exactly as written here. If you change a formula, change this file and `cases.md` in the same commit.

## Units

- Depths (ET0, ETc, rain, TAW, RAW, Dr, I, bucket): **mm**. Lengths (Zr, row and emitter spacing): **m**. Area: **m²**. Flow: **L/h**.
- 1 mm of water over 1 m² is 1 litre.
- Soil water comes from the registry as `soil.available_water_mm_per_m`. **Never hard-code it.** It is plot data, and a hard-coded value silently gives the wrong bucket for every other soil.

## Season day and stage

```
i = (date - planting_date).days + 1        # the planting day is day 1
```

| Crop | L_ini / L_dev / L_mid / L_late (days) | Season | Kc ini / mid / end | Zmax (m) | p |
| --- | --- | --- | --- | --- | --- |
| tomato | 30 / 40 / 40 / 25 | 135 | 0.60 / 1.15 / 0.80 | 0.70 | 0.40 |
| pepper | 30 / 35 / 40 / 20 | 125 | 0.60 / 1.05 / 0.90 | 0.50 | 0.30 |

- Stage lengths come from FAO Table 11 (tomato: the "Arid Region", January row; pepper: the "Europe and Medit." row, taking 30 from "25/30"). Kc comes from Table 12, Zmax and p from Table 22. **Why:** these are FAO's own numbers, and tomato Kc_end 0.80 is the middle of the 0.70–0.90 range.
- p in the table is the per-crop **default**. The optional setting `DEPLETION_FRACTION_OVERRIDE` (planner-service config, range 0..1, unset by default) replaces p for every crop when it is set: 0.5 is the task's "half", and 0 gives daily irrigation of ETc. **Why:** the irrigation policy is configuration, not code (decision I21 in decisions.md).
- `i > season` → stage `"ended"`: no irrigation (`run_minutes: 0`). **Why:** FAO gives no Kc after the late stage, and the crop is harvested.

## Kc (FAO Eq. 66)

```
ini  (i <= L_ini):                 kc = Kc_ini
dev  (i <= L_ini+L_dev):           kc = Kc_ini + (i - L_ini) / L_dev * (Kc_mid - Kc_ini)
mid  (i <= L_ini+L_dev+L_mid):     kc = Kc_mid
late (i <= season):                kc = Kc_mid + (i - (L_ini+L_dev+L_mid)) / L_late * (Kc_end - Kc_mid)
```

**Why:** FAO-56 says Kc is constant in the ini and mid stages and changes linearly in dev and late. Eq. 66 applies to all four stages.

## Root depth (Annex 8, Eq. 8-3, time-based)

```
Zr = 0.20 + (Zmax - 0.20) * min(1, (i - 1) / (L_ini + L_dev))
```

**Why:** roots start shallow (Annex 8: Zr_min 0.15–0.20 m) and reach full depth at the end of development. A full-depth bucket on day 1 would hold water the young roots can't reach.

## The bucket

```
TAW = available_water_mm_per_m * Zr     # total available water, mm
RAW = p * TAW                           # readily available water, mm
ETc = kc * ET0                          # the crop's water use that day, mm
```

**Why:** FAO Ch. 8, Eq. 82–83 and Eq. 58. We use p from Table 22 without the `0.04 (5 − ETc)` correction (see decisions.md).

`Dr` is the depletion in mm: 0 means full, TAW means empty. Each day, in this order:

```
rain_eff = rain if rain >= 0.2 * ET0 else 0          # small rain is ignored, no runoff
Dr_start = max(Dr_prev - rain_eff, 0)                # rain beyond full drains away
if Dr_start + ETc > RAW:
    I = Dr_start + ETc;  Dr_end = 0                  # irrigate today, refill to full
else:
    I = 0;               Dr_end = min(Dr_start + ETc, TAW)
bucket_mm = TAW - Dr_end                             # the bucket level reported for the day
```

- **Rain filter.** FAO Ch. 8 says rain below about 0.2·ET0 per day can be ignored, and Annex 8 assumes RO = 0. **Why:** a light shower wets the surface and evaporates. It never reaches the roots.
- **Cap at 0.** **Why:** a bucket can't be fuller than full. The extra water is deep percolation (FAO Eq. 88).
- **Irrigate when the day would end below RAW, on that same day, refilling to full.** **Why:** refilling to full comes from Annex 8 (net irrigation = depletion). Irrigating on the same day is **our** choice, based on FAO Ch. 8 ("irrigations should be applied before or at the moment when the readily available soil water is depleted"). It avoids the stress day that Annex 8 gets by irrigating the next morning.
- **Cap at TAW.** **Why:** the bucket can't go below empty. This branch only matters in the suggestion simulation, which never irrigates.
- TAW changes each day while Zr grows. `Dr` carries over in mm.

## Drip conversion

```
litres      = round(I * area_m2)                                 # whole litres, half up (I19)
emitters    = area_m2 / (row_spacing_m * emitter_spacing_m)
run_minutes = round(I * area_m2 / (emitters * flow_lph) * 60)    # whole minutes, half up (I20)
            = round(I * row_spacing_m * emitter_spacing_m / flow_lph * 60)   # area cancels out
```

- Compute `run_minutes` from the unrounded `I`, not from the rounded `litres`. **Why:** a single rounding step keeps both outputs traceable to `I`. Both ways give the same minutes in every case in cases.md.
- Minutes are **net**: there is no efficiency factor. **Why:** drip losses are small, FAO-56 gives no factor, and an invented factor would be a hidden constant (see decisions.md).
- Check: 6.9 mm × 1000 m² → 6900 L. Row 1.5 m, spacing 0.4 m, flow 1.0 L/h → 248 min (the example in docs/task-p2.md).

## Initial bucket (`bucket_start`)

```
bucket_start in [0, 1], default 1.0 (full)
Dr_0 = (1 - bucket_start) * TAW(day 1 of the plan)
```

- `bucket_start` outside [0, 1] → `422`, `code`: `VALIDATION`.
- **Why:** the planner keeps no state, so it can't know today's bucket level. Full is the task's own assumption (its bucket example starts full). It can postpone irrigation, which is why the suggestion exists.

## Bucket suggestion ("suggest and confirm")

The grower gives the date D of their last irrigation. The planner suggests a `bucket_start`. The grower confirms it or changes it.

```
Dr = 0                                     # the bucket was full at the end of day D
for each day from D+1 to yesterday:        # past ET0 and rain, NO irrigation
    rain_eff = rain if rain >= 0.2 * ET0 else 0
    Dr = min(max(Dr - rain_eff, 0) + kc * ET0, TAW(that day))
suggestion = clamp(1 - Dr / TAW(today), 0, 1)
```

- `422` when D is in the future, before planting, more than 92 days ago, or not a valid date.
- Season ended → stage `"ended"`, no suggestion.
- weather-service can return fewer past days than requested (`past_days_returned`). What to do then is in decisions.md (I22).
- **Why:** without this the planner would assume a full bucket every day and keep postponing irrigation forever. The details are in decisions.md.

## Before saying the work is done

- Every case in [references/cases.md](references/cases.md) is a unit test, and they all pass.
- Run `uv run pytest` from `services/planner-service`, and report the result.
