# Hand-calculated cases

Each case follows the formulas in [../SKILL.md](../SKILL.md). The bucket starts full (`bucket_start = 1.0`) unless noted, and ET0 is the same every day. `bucket_mm` is the level at the end of the day. Turn every case into a unit test.

## Case 1: tomato, mid-season, no rain

- Input: tomato, sand (`available_water_mm_per_m` 83), plan day 1 = season day 80 (mid), ET0 5.0, no rain.
- Plot: area 1000 m², row 1.5 m, emitter spacing 0.4 m, flow 1.6 L/h.
- Every day: Kc 1.15, Zr 0.70, TAW 58.10, RAW 23.24, ETc 5.75.

| Day | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bucket_mm | 52.35 | 46.60 | 40.85 | 35.10 | 58.10 | 52.35 | 46.60 |
| run_minutes | 0 | 0 | 0 | 0 | 647 | 0 | 0 |

- Day 5: Dr_start 23.00, and 23.00 + 5.75 = 28.75 > RAW 23.24, so irrigate.
- Day 5: I 28.75 mm, litres 28750, run_minutes 647 (646.875).

## Case 2: pepper, development stage, no rain

- Input: pepper, sand (83), plan day 1 = season day 40 (dev), ET0 4.0, no rain.
- Plot: area 400 m², row 1.2 m, emitter spacing 0.3 m, flow 2.0 L/h.
- Kc and Zr grow every day, so TAW and RAW grow too.

| Day | kc | Zr | TAW | RAW | ETc | bucket_mm |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.7286 | 0.3800 | 31.540 | 9.462 | 2.9143 | 28.626 |
| 2 | 0.7414 | 0.3846 | 31.923 | 9.577 | 2.9657 | 26.043 |
| 3 | 0.7543 | 0.3892 | 32.306 | 9.692 | 3.0171 | 23.409 |
| 4 | 0.7671 | 0.3938 | 32.689 | 9.807 | 3.0686 | 32.689 (irrigate) |
| 5 | 0.7800 | 0.3985 | 33.072 | 9.922 | 3.1200 | 29.952 |
| 6 | 0.7929 | 0.4031 | 33.455 | 10.037 | 3.1714 | 27.164 |
| 7 | 0.8057 | 0.4077 | 33.838 | 10.152 | 3.2229 | 24.324 |

- Day 4: I 11.9657 mm, litres 4786, run_minutes 129 (129.23).

## Case 3: as case 1, with rain

- Input: the same as case 1, plus rain of 0.5 mm on day 2 and 12 mm on day 4.
- Day 2: the 0.5 mm is ignored, because it is less than 0.2 × 5.0 = 1.0.
- Day 4: Dr_start = 17.25 − 12 = 5.25, and Dr_end = 11.00.

| Day | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bucket_mm | 52.35 | 46.60 | 40.85 | 47.10 | 41.35 | 35.60 | 58.10 |
| run_minutes | 0 | 0 | 0 | 0 | 0 | 0 | 636 |

- Day 7: I 28.25 mm, litres 28250, run_minutes 636 (635.625).

## Case 4: bucket suggestion

- Input: tomato, sand (83), today = season day 80, ET0 5.0 on every past day, no rain.
- Each day: ETc 5.75, TAW 58.10.

| | Last irrigation (season day) | Past days simulated | Dr | Suggestion |
| --- | --- | --- | --- | --- |
| 4a | 76 | 77, 78, 79 | 17.25 | 0.7031 |
| 4b | 65 | 66 … 79 (14 days) | capped at 58.10 | 0.0 |

- In 4a, Dr passes RAW (23.24) without triggering an irrigation. This is intended: the simulation never irrigates.

## Conversion check: the example in docs/task-p2.md

- Input: tomato mid-season, 1000 m², ET0 6.0, Kc 1.15.
- Plot: row 1.5 m, emitter spacing 0.4 m, flow 1.0 L/h.
- ETc = I = 6.9 mm → litres 6900, run_minutes 248 (248.4).
