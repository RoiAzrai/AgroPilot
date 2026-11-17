# Calculation decisions

The decisions behind [../SKILL.md](../SKILL.md). The FAO references point to [fao56.md](../../../../services/planner-service/docs/research/fao56.md). Follow these decisions. If one needs to change, change it here first, then in SKILL.md and cases.md.

| Decision | What we chose | Why | Deviation from task / FAO-56 |
| --- | --- | --- | --- |
| Crop coefficient | Single Kc (Table 12, Eq. 66) | Simple and traceable by hand, and the task asks for Kc per day | **Deviation from FAO.** FAO-56 prefers the dual Kcb + Ke approach for high-frequency microirrigation (Ch. 5, Table 10) |
| Partial wetting | No fw correction of Kc_ini (Eq. 60) | Conservative: it can only over-water slightly in the initial stage, never under-water | FAO-56 allows Kc_ini × fw for drip. We don't apply it |
| Depletion fraction (I21) | p from Table 22 (tomato 0.40, pepper 0.30) as the per-crop default, without the `0.04 (5 − ETc)` correction. The optional `DEPLETION_FRACTION_OVERRIDE` (planner-service config, 0..1, unset by default) replaces p for every crop when it is set | Water before stress starts. Total water is similar over a season (irrigation ≈ ETc minus effective rain). Mainly the timing changes | **Deviation from task by default.** The task says "below half". Setting the override to 0.5 gives the task's rule |
| When and how much | Irrigate on the same day the bucket would end below RAW, and refill to full (I = Dr_start + ETc) | Refilling to full comes from Annex 8 (net irrigation = depletion). Same-day irrigation is our choice, based on FAO Ch. 8 ("irrigations should be applied before or at the moment when the readily available soil water is depleted"). It avoids the stress day | Annex 8 irrigates the next morning. We irrigate the same day |
| Daily irrigation (I21) | `DEPLETION_FRACTION_OVERRIDE=0` gives irrigation of ETc every day | A grower who wants daily drip gets it through configuration | None. It is a setting, not code |
| Rain | Ignore rain < 0.2·ET0. No runoff. Rain beyond full drains away | FAO Ch. 8 rule. Annex 8 assumes RO = 0 | FAO-56 gives no "effective rainfall" method |
| Efficiency | Net minutes, with no efficiency factor | FAO-56 gives no factor. An invented one would be a hidden constant | None. A future factor would go in config.py |
| Season end | i > season length → stage `"ended"`, `run_minutes: 0` | No Kc after the late stage, and the crop is harvested | None |
| Output fields | No `need_mm` in the plan | Task FR-2.10 (updated upstream) lists no `need_mm` | None |
| Initial bucket | `bucket_start` in [0, 1], default 1.0. Suggest and confirm from the grower's last irrigation date, with `422` for a future date, a date before planting, more than 92 days ago, or an invalid date | A stateless planner that assumes a full bucket every day postpones irrigation forever | **Deviation from FR-2.3 / FR-2.11, on purpose.** The suggestion needs past ET0 and rain (FR-2.3 gives the forecast from today) and an input beyond plot, soil, emitter and forecast |
| Future improvement | Store the irrigations in a DB | The planner could then know the real bucket level, with no guess | Not built |
