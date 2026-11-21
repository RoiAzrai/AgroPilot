# FAO-56: crop water need and daily soil water balance

Source: Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998). *Crop evapotranspiration: Guidelines for computing crop water requirements*. FAO Irrigation and Drainage Paper 56. Online edition: https://www.fao.org/3/x0490E/x0490e00.htm

Read on 2026-11-15. Every claim below comes from the FAO HTML chapter pages listed in [Sources](#sources). The page text came from `https://www.fao.org/3/x0490E/...`. Most equations on those pages are GIF images, and the `/3/x0490E/` image links redirect to openknowledge.fao.org. The images were therefore read from the mirror `https://www.fao.org/4/x0490e/...`. Equations below were copied from those images. Citations use the form (Ch. N, Eq. / Table / section) and link to the page used.

Each citation links to its page:

- Ch. 5 → https://www.fao.org/3/x0490E/x0490e0a.htm
- Ch. 6 → https://www.fao.org/3/x0490E/x0490e0b.htm
- Ch. 7 → https://www.fao.org/3/x0490E/x0490e0c.htm
- Ch. 8 → https://www.fao.org/3/x0490E/x0490e0e.htm
- Ch. 9 → https://www.fao.org/3/x0490E/x0490e0f.htm
- Ch. 10 → https://www.fao.org/3/x0490E/x0490e0g.htm
- Annex 8 → https://www.fao.org/3/x0490E/x0490e0p.htm

---

## 1. From ET0 and Kc to crop water need (Ch. 5 and 6)

### 1.1 The crop coefficient approach

```
ETc = Kc × ET0                                   (Eq. 56, Ch. 5; repeated as Eq. 58, Ch. 6)
  ETc  crop evapotranspiration   [mm/d]
  Kc   crop coefficient          [-]
  ET0  reference evapotranspiration (FAO Penman-Monteith, grass) [mm/d]
```
([Ch. 5, Eq. 56][ch5]; [Ch. 6, Eq. 58][ch6])

- **What Kc represents.** Kc is the ratio ETc/ET0. It combines four things that make a crop differ from reference grass: crop height, the albedo of the crop and soil surface, canopy resistance, and evaporation from exposed soil ([Ch. 5, "Crop coefficient approach"][ch5]). Weather effects sit in ET0, so Kc mostly depends on the crop and only a little on climate. That is why standard Kc values can be used in other places ([Ch. 5][ch5]).
- **Standard conditions.** Eq. 56 gives ETc under *standard conditions*: large fields, no water, salinity, density, pest or disease limits. This is the upper envelope of ET. Non-standard conditions use ETc adj (Part C, Ch. 8 onward) ([Ch. 5][ch5]).
- **Reference climate for the tables.** Table 12 values assume a sub-humid climate with RHmin ≈ 45% and u2 ≈ 2 m/s ([Ch. 5, "Climate"][ch5]; [Ch. 6, Table 12 title][ch6]).
- **Single vs dual.** In the single approach, transpiration and soil evaporation are merged into one time-averaged Kc. It suits planning, design and "real time irrigation scheduling for non-frequent water applications (surface and sprinkler irrigation)". The dual approach (Kcb + Ke) is listed for "irrigation scheduling for high frequency water application (microirrigation and automated sprinkler irrigation)" and needs a daily time step ([Ch. 5, Table 10][ch5]). The single Kc "expresses only the time-averaged (multi-day) effects", but the calculation may still run on a daily step ([Ch. 5, "Single crop coefficient approach"][ch5]).
- **Ch. 6 procedure.** (1) find the growth stages, their lengths and their Kc values; (2) adjust Kc for wetting frequency and climate; (3) build the Kc curve; (4) compute ETc = Kc × ET0 ([Ch. 6, intro][ch6]).

### 1.2 Growth stages (Ch. 5)

- **Initial:** from planting to about 10% ground cover. ET is mostly soil evaporation, so Kc_ini depends on how often the surface is wetted ([Ch. 5, "Crop growth stages"][ch5]).
- **Crop development:** from 10% ground cover to effective full cover, which for many crops is at the start of flowering. For crops taller than 0.5 m, fc at effective full cover is about 0.7–0.8. LAI = 3 is another marker ([Ch. 5][ch5]).
- **Mid-season:** from effective full cover to the start of maturity. Kc is at its maximum (Kc_mid) and fairly constant ([Ch. 5][ch5]).
- **Late season:** from the start of maturity to harvest or full senescence. Kc_end is high if the crop is irrigated often until a fresh harvest and low if it dries in the field ([Ch. 5][ch5]).

### 1.3 Building the Kc curve

Only three values are needed: Kc_ini, Kc_mid and Kc_end ([Ch. 6, "Crop coefficients"][ch6]). Construction ([Ch. 6, "Construction of the Kc curve – Annual crops"][ch6]):

1. Split the season into the four stages, set their lengths (Table 11) and take Kc_ini, Kc_mid and Kc_end from Table 12.
2. Adjust the values for wetting frequency and climate.
3. Draw horizontal lines at Kc_ini (initial stage) and Kc_mid (mid-season). Draw straight lines from Kc_ini to Kc_mid across the development stage and from Kc_mid to Kc_end across the late season.

**Kc on day i (numerical form):**

```
Kc_i = Kc_prev + [ (i − Σ(L_prev)) / L_stage ] × (Kc_next − Kc_prev)        (Eq. 66)
  i         day number within the growing season [1 .. season length]
  L_stage   length of the current stage [days]
  Σ(L_prev) sum of the lengths of all previous stages [days]
  Kc_prev   Kc at the end of the previous stage; Kc_next = Kc at the start of the next stage (Kc_end for the late stage)
```
Kc is constant in the initial and mid-season stages. It changes linearly in the development and late stages. "Equation 66 applies to all four stages." ([Ch. 6, "Numerical determination of Kc", Eq. 66][ch6]). Worked check (Example 28, dry beans 25/25/30/20 d, Kc 0.15/1.19/0.35): day 40 → 0.15 + [(40−25)/25](1.19−0.15) = 0.77 ([Ch. 6, Example 28][ch6]). Annex 8 implements the same rule with nested IFs, and uses Kc_ini outside the season ([Annex 8, Box 8.1, cell O14, footnote 2][an8]).

### 1.4 Climate adjustment of Kc_mid and Kc_end

```
Kc_mid = Kc_mid(Tab) + [0.04 (u2 − 2) − 0.004 (RHmin − 45)] (h/3)^0.3       (Eq. 62)
Kc_end = Kc_end(Tab) + [0.04 (u2 − 2) − 0.004 (RHmin − 45)] (h/3)^0.3       (Eq. 65)
  u2     mean daily wind speed at 2 m over grass during the stage [m/s], valid 1 ≤ u2 ≤ 6
  RHmin  mean daily minimum relative humidity during the stage [%], valid 20 ≤ RHmin ≤ 80
  h      mean plant height during the stage [m], valid 0.1 < h < 10
```
([Ch. 6, Eq. 62 and Eq. 65][ch6])

- Apply Eq. 62 when RHmin ≠ 45% or u2 ≠ 2 m/s. Use stage-average u2 and RHmin ([Ch. 6][ch6]).
- **Eq. 65 is applied only when Kc_end(Tab) > 0.45.** If Kc_end(Tab) < 0.45, no adjustment is made ([Ch. 6, Kc_end section][ch6]).
- Eq. 62 is not very sensitive to its inputs: it changes by 0.04 per 1 m/s of u2 and per 10% of RHmin for a 3 m crop. If no data are available, Tables 15 and 16 give typical u2 and RHmin values ([Ch. 6][ch6]).
- RHmin from temperatures: `RHmin = 100 × e°(Tdew) / e°(Tmax)` (Eq. 63). Where Tdew is missing, Tmin can replace it (Eq. 64). In arid and semi-arid climates, subtract 2 °C from Tmin first ([Ch. 6, Eq. 63–64 and footnote][ch6]).
- Below h = 0.1 m the crop behaves like grass and Eq. 62 should not be applied ([Ch. 6][ch6]).
- **Wetting frequency at mid-season:** with irrigation more often than every 3 days and a tabulated Kc_mid below 1.0, Kc_mid can be replaced by about 1.1–1.3, "especially where the irrigation system moistens an important fraction of the soil surface (fw > 0.3)" ([Ch. 6, "Adjustment for frequency of wetting"][ch6]).
- Note: the Ch. 6 text says Box 14 shows Kc_mid variation "for tomatoes", but Box 14 on the page is about wheat (Kc_mid 1.15, h = 1.0 m). This was verified on the page. It is a mismatch in the source ([Ch. 6, Box 14][ch6]).

### 1.5 Kc_ini notes

- The Table 12 Kc_ini values are approximations for preliminary or planning studies only ([Ch. 6, "Crop coefficient for the initial stage"][ch6]). Footnote 1 of Table 12: with frequent wettings (high-frequency sprinkler or daily rain), Kc_ini "may increase substantially and may approach 1.0 to 1.2" ([Ch. 6, Table 12 fn 1][ch6]).
- Kc_ini depends on the time between wetting events, ET0 and the size of each wetting. It "can vary between 0.1 and 1.15" ([Ch. 6][ch6]). Table 9 gives rough values. For example, weekly wetting with ET0 3–5 mm/d → 0.6 ([Ch. 5, Table 9][ch5]).
- Graphical method: Fig. 29 covers light wettings (3–10 mm per event). Fig. 30a/30b cover heavy wettings (≥ 40 mm) on coarse and on fine/medium soils. For infiltration depths between 10 and 40 mm, interpolate ([Ch. 6, Figs. 29–30, Eq. 59][ch6]):
  ```
  Kc_ini = Kc_ini(Fig29) + [(I − 10)/(40 − 10)] × [Kc_ini(Fig30) − Kc_ini(Fig29)]   (Eq. 59)
  ```
- **Partial wetting (drip):** "for a trickle irrigation system, the fraction of the surface wetted, fw, may be only 0.4" ([Ch. 6, "Adjustment for partial wetting by irrigation"][ch6]).
  ```
  Kc_ini = fw × Kc_ini(Tab, Fig)      (Eq. 60)
  Iw     = I / fw                     (Eq. 61)  infiltrated depth on the wetted part, used to pick Fig. 29 vs 30
  ```
  Example 26 is trickle irrigation every 2 days, 12 mm per event (field-average depth), fw = 0.4, ET0 = 4. It gives Iw = 30 mm, then Kc_ini = 1.05 by interpolation, then 0.4 × 1.05 = **0.42**, so ETc = 1.7 mm/d ([Ch. 6, Example 26][ch6]). When irrigation (partial) and rain (full surface) both happen, fw should be weighted by the infiltration depth of each ([Ch. 6][ch6]).

### 1.6 Dual coefficient (only what the planner needs to know)

- `Kc = Kcb + Ke` (Eq. 57). Kcb is the basal coefficient (transpiration, dry soil surface). Ke is soil evaporation ([Ch. 5, Eq. 57][ch5]); `ETc = (Kcb + Ke) ET0` (Eq. 69) ([Ch. 7][ch7]).
- Ke requires a daily water balance of the top soil layer (Ze ≈ 0.10–0.15 m, TEW, REW; Eqs. 71–79) ([Ch. 7][ch7]).
- Exposed and wetted fraction: `few = min(1 − fc, fw)` (Eq. 75). "In the case of drip irrigation, where the majority of soil wetted by irrigation may be beneath the canopy ... the value for fw may need to be reduced to about one-half to one-third of that given in Table 20 ... A general approach could be to multiply fw by [1-(2/3)fc] for drip irrigation." ([Ch. 7, "few: calculation procedure"][ch7]). Example 34 (cotton, drip, fw = 0.3, fc = 0.53): few = 0.19, Ke capped at 0.25, Kc = 1.15. This is lower than sprinkler (1.30) or furrow (1.29) ([Ch. 7, Examples 32–34][ch7]).
- Simple daily rule for fw: irrigation, or irrigation plus rain → fw of the system; significant rain (> 3–4 mm) with no irrigation → fw = 1; neither → keep the previous day's fw ([Ch. 7, after Table 20][ch7]).

**Table 20 – fw, fraction of the soil surface wetted** ([Ch. 7, Table 20][ch7])

| Wetting event | fw |
| --- | --- |
| Precipitation | 1.0 |
| Sprinkler irrigation | 1.0 |
| Basin irrigation | 1.0 |
| Border irrigation | 1.0 |
| Furrow irrigation (every furrow), narrow bed | 0.6...1.0 |
| Furrow irrigation (every furrow), wide bed | 0.4... 0.6 |
| Furrow irrigation (alternated furrows) | 0.3...0.5 |
| Trickle irrigation | 0.3... 0.4 |

**Table 21 – fc, ground cover by stage** ([Ch. 7, Table 21][ch7])

| Crop growth stage | fc | 1 − fc |
| --- | --- | --- |
| Initial stage | 0.0 - 0.1 | 1.0 - 0.9 |
| Crop development stage | 0.1 - 0.8 | 0.9 - 0.2 |
| Mid-season stage | 0.8 - 1.0 | 0.2 - 0.0 |
| Late season stage | 0.8 - 0.2 | 0.2 - 0.8 |

- **Ground cover below full.** For thin stands, Ch. 9 lowers Kcb_mid using effective ground cover: `Kcb_mid = Kc_min + (Kcb_full − Kc_min) × min(1, 2fc, (fc_eff)^(1/(1+h)))` (Eq. 98), with Kc_min ≈ 0.15–0.20 ([Ch. 9, Eq. 98][ch9]). In Ch. 5, dry soil with Kc = 0.5 corresponds to about 25–40% cover and Kc = 0.7 to about 40–60% ([Ch. 5, "Crop development stage"][ch5]).
- **Plastic mulch + trickle** (common for tomato and pepper): reduce Kc_mid and Kc_end in Table 12 by 10–30% (use the higher value for frequent trickle irrigation). Kc_ini under mulch "is often as low as 0.10". For Kcb, the reduction is about 5–15%. Table 25 lists Tomato: Kc reduction 35% (Haddadin and Ghawi, 1983) ([Ch. 10, "Plastic mulches", Table 25][ch10]).

---

## 2. Tomato and sweet (bell) pepper values

All numbers are copied from the tables as printed. Tables 12, 17 and 22 also give a group-level row "b. Vegetables – Solanum Family (Solanaceae)". Its Kc_ini / Kcb_ini value applies to every crop in the group, because the individual crop rows leave that cell blank.

### 2.1 Table 12 – single Kc and max height ([Ch. 6, Table 12][ch6])

| Row | Kc_ini ¹ | Kc_mid | Kc_end | Max crop height h (m) |
| --- | --- | --- | --- | --- |
| b. Vegetables – Solanum Family (Solanaceae) (group row) | 0.6 | 1.15 | 0.80 | – |
| Sweet Peppers (bell) | (0.6 from group) | 1.05 ² | 0.90 | 0.7 |
| Tomato | (0.6 from group) | 1.15 ² | 0.70-0.90 | 0.6 |

- ¹ Kc_ini is a general value for typical irrigation. With frequent wetting it may approach 1.0–1.2. Refine it with Figs. 29/30, Annex 7 Eq. 7-3 or the dual approach ([Ch. 6, Table 12 fn 1][ch6]).
- ² "Beans, Peas, Legumes, Tomatoes, Peppers and Cucumbers are sometimes grown on stalks reaching 1.5 to 2 meters in height. In such cases, increased Kc values need to be taken. For green beans, peppers and cucumbers, 1.15 can be taken, and for tomatoes, dry beans and peas, 1.20. Under these conditions h should be increased also." ([Ch. 6, Table 12 fn 2][ch6])
- The tomato Kc_end is given only as the range 0.70-0.90. FAO-56 does not say which end of the range applies when (not specified in the table row or footnotes read).

### 2.2 Table 11 – stage lengths (days) ([Ch. 6, Table 11][ch6])

| Crop | L_ini | L_dev | L_mid | L_late | Total | Plant date | Region |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Sweet peppers (bell) | 25/30 | 35 | 40 | 20 | 125 | April/June | Europe and Medit. |
| Sweet peppers (bell) | 30 | 40 | 110 | 30 | 210 | October | Arid Region |
| Tomato | 30 | 40 | 40 | 25 | 135 | January | Arid Region |
| Tomato | 35 | 40 | 50 | 30 | 155 | Apr/May | Calif., USA |
| Tomato | 25 | 40 | 60 | 30 | 155 | Jan | Calif. Desert, USA |
| Tomato | 35 | 45 | 70 | 30 | 180 | Oct/Nov | Arid Region |
| Tomato | 30 | 40 | 45 | 30 | 145 | April/May | Mediterranean |

- Table footnote: stage lengths "are indicative of general conditions, but may vary substantially from region to region, with climate and cropping conditions, and with crop variety. The user is strongly encouraged to obtain appropriate local information." The primary source is FAO-24, Table 22 ([Ch. 6, Table 11 footnote *][ch6]).
- "The values in Table 11 are useful only as a general guide ... Local observations of the specific plant stage development should be used, wherever possible" ([Ch. 6][ch6]). Box 15 shows a Table 11 mid-season length that was 10 days too long against lysimeter data ([Ch. 6, Box 15][ch6]).
- For pepper, row 1 lists L_ini as "25/30" but the total as 125. 25+35+40+20 = 120 and 30+35+40+20 = 125, so the total matches the 30-day variant. This is my arithmetic on the printed values.

### 2.3 Table 17 – basal Kcb (dual approach) ([Ch. 7, Table 17][ch7])

| Row | Kcb_ini | Kcb_mid | Kcb_end |
| --- | --- | --- | --- |
| b. Vegetables – Solanum Family (Solanaceae) (group row) | 0.15 | 1.10 | 0.70 |
| Sweet Peppers (bell) | (0.15 from group) | 1.00 ² | 0.80 |
| Tomato | (0.15 from group) | 1.10 ² | 0.60-0.80 |

- Footnote 1: Kcb values are for a dry soil surface and are meant only for the dual Kcb + Ke approach. Use h from Table 12 for the climate adjustment ([Ch. 7, Table 17 fn 1][ch7]). The adjustment is Eq. 70, which has the same form as Eq. 62 ([Ch. 7, Example 29, Eq. 70][ch7]).
- Footnote 2 (staked crops 1.5–2 m): for peppers 1.10 can be used, for tomatoes 1.15; increase h as well ([Ch. 7, Table 17 fn 2][ch7]).

### 2.4 Table 22 – root depth Zr and depletion fraction p ([Ch. 8, Table 22][ch8])

| Row | Maximum root depth ¹ (m) | Depletion fraction p ² (for ET ≈ 5 mm/day) |
| --- | --- | --- |
| Sweet Peppers (bell) | 0.5-1.0 | 0.30 |
| Tomato | 0.7-1.5 | 0.40 |

- ¹ "The larger values for Zr are for soils having no significant layering ... The smaller values for Zr may be used for irrigation scheduling and the larger values for modeling soil water stress or for rainfed conditions." ([Ch. 8, Table 22 fn 1][ch8])
- ² "The values for p apply for ETc ≈ 5 mm/day", adjusted with `p = p_table22 + 0.04 (5 − ETc)` ([Ch. 8, Table 22 fn 2][ch8]). See §3.2.
- The group heading on the FAO page is misspelled "Solarium Family (Solanaceae)" (as printed).
- Example 36 uses tomato with Zr ≈ 0.8 m and p = 0.40. It gives TAW/RAW = 72/29 mm (loamy sand), 136/54 mm (silt) and 96/38 mm (silty clay) ([Ch. 8, Example 36][ch8]).

---

## 3. The soil water "bucket" (Ch. 8)

### 3.1 Total and readily available water

```
TAW = 1000 (θFC − θWP) Zr          (Eq. 82)   [mm]; θ in m³/m³, Zr in m
RAW = p × TAW                      (Eq. 83)   [mm]
```
([Ch. 8, Eq. 82–83][ch8])

- p is "average fraction of Total Available Soil Water (TAW) that can be depleted from the root zone before moisture stress (reduction in ET) occurs [0-1]". It ranges from 0.30 for shallow-rooted plants at ETc > 8 mm/d to 0.70 for deep-rooted plants at ETc < 3 mm/d. A value of 0.50 is common ([Ch. 8, "Readily available water"][ch8]).

### 3.2 Adjusting p for ETc

```
p = p_Table22 + 0.04 (5 − ETc)       limited to 0.1 ≤ p ≤ 0.8, ETc in mm/day
```
([Ch. 8, RAW section and Table 22 fn 2; Fig. 41][ch8]). In hot, dry weather p is 10–25% below the table value. At low ETc it can be up to 20% above it. "Often, a constant value is used for p for a specific growing period, rather than varying the value each day." ([Ch. 8][ch8])

### 3.3 Water stress coefficient Ks

```
Ks = (TAW − Dr) / (TAW − RAW) = (TAW − Dr) / ((1 − p) TAW)    for Dr > RAW     (Eq. 84)
Ks = 1                                                         for Dr ≤ RAW
ETc adj = Ks × Kc × ET0                       (Eq. 81, single Kc)
ETc adj = (Ks × Kcb + Ke) × ET0               (Eq. 80, dual)
```
([Ch. 8, Eq. 80, 81, 84][ch8]). Eq. 80 is "generally more valid" because Ks acts only on transpiration. Eq. 81 is reasonable where soil evaporation is small ([Ch. 8, intro][ch8]).

Example 37 (tomato, Zr 0.8 m, p 0.40, silt θFC 0.32 / θWP 0.12, TAW 160, RAW 64, start Dr 55 mm, ET0 5, Kc 1.2, no water). Ks falls from 1.00 (days 1–2) to 0.97 on day 3 and to 0.62 on day 10, when Dr = 104.5 mm. The table columns are: Day, ET0, Kc, ETc, Dr start, Ks, ETc adj, Dr end ([Ch. 8, Example 37][ch8]).

### 3.4 Daily root zone water balance

```
Dr,i = Dr,i-1 − (P − RO)_i − I_i − CR_i + ETc,i + DP_i       (Eq. 85)
0 ≤ Dr,i ≤ TAW                                               (Eq. 86)
```
([Ch. 8, Eq. 85–86][ch8])

| Term | Meaning (FAO-56 wording) and guidance |
| --- | --- |
| Dr,i | root zone depletion at the end of day i [mm] |
| Dr,i-1 | depletion at the end of the previous day [mm] |
| P_i | precipitation on day i. "Daily precipitation in amounts less than about 0.2 ET0 is normally entirely evaporated and can usually be ignored in the water balance calculations especially when the single crop coefficient approach is being used." |
| RO_i | runoff from the soil surface; "can be predicted using standard procedures from hydrological texts" (no method given in FAO-56) |
| I_i | "net irrigation depth on day i that infiltrates the soil", "the mean infiltrated irrigation depth expressed for the entire field surface" |
| CR_i | capillary rise from groundwater; "can normally be assumed to be zero when the water table is more than about 1 m below the bottom of the root zone" |
| ETc,i | Kc·ET0 while Dr ≤ RAW; Eq. 80/81 once Dr > RAW |
| DP_i | deep percolation out of the root zone (Eq. 88) |

([Ch. 8, "Soil water balance" and term sub-sections][ch8])

- **Bounds.** Water above field capacity is "assumed to be lost the same day by deep percolation, following any ET for that day", so the minimum Dr is 0. At wilting point Dr = TAW and Ks = 0 ([Ch. 8, "Limits on Dr,i"][ch8]).
- **Initial depletion:** `Dr,i-1 = 1000 (θFC − θ_i-1) Zr` (Eq. 87), where θ_i-1 is the measured average root-zone water content. "Following heavy rain or irrigation, the user can assume that the root zone is near field capacity, i.e., Dr,i-1 ≈ 0." ([Ch. 8, Eq. 87][ch8])
- **Deep percolation:** `DP_i = (P_i − RO_i) + I_i − ETc,i − Dr,i-1 ≥ 0` (Eq. 88). It applies after heavy rain or irrigation. While Dr,i > 0 the soil does not drain and DP = 0 ([Ch. 8, Eq. 88][ch8]).
- **Scheduling rule from Ch. 8:** "To avoid crop water stress, irrigations should be applied before or at the moment when the readily available soil water is depleted (Dr,i ≤ RAW). To avoid deep percolation losses that may leach relevant nutrients out of the root zone, the net irrigation depth should be smaller than or equal to the root zone depletion (I_i ≤ Dr,i)." ([Ch. 8, "Forecasting or allocating irrigations"][ch8])
- Example 38 (dual Kc, p = 0.6, root depth growing from 0.3 to 0.35 m, irrigation when RAW is depleted, all water applied early in the day). Columns: Day, ET0, Zr, RAW, Dr start, P−RO, I, Ks, Kcb, Ke, Kc, ETc, DP, Dr end. Dr start = max(Dr,i-1 end − I − (P−RO), 0) when water is applied early in the day. On day 10, Dr = 27 mm ≥ RAW, so a 27 mm net irrigation "refills the root zone and avoids water loss by deep percolation" ([Ch. 8, Example 38, footnotes 5 and 7][ch8]). When Zr grows, subsoil water is added: `Dr,i = Dr,i-1 + 1000(θFC − θsub,i-1) ΔZr`. The example assumes θsub is at FC ([Ch. 8, Example 38 fn 5][ch8]).

### 3.5 Table 19 – typical soil water characteristics ([Ch. 7, Table 19][ch7])

| Soil type (USA texture) | θFC (m³/m³) | θWP (m³/m³) | θFC − θWP (m³/m³) | REW (mm) | TEW (mm, Ze = 0.10 m) |
| --- | --- | --- | --- | --- | --- |
| Sand | 0.07 - 0.17 | 0.02 - 0.07 | 0.05 - 0.11 | 2 - 7 | 6 - 12 |
| Loamy sand | 0.11 - 0.19 | 0.03 - 0.10 | 0.06 - 0.12 | 4 - 8 | 9 - 14 |
| Sandy loam | 0.18 - 0.28 | 0.06 - 0.16 | 0.11 - 0.15 | 6 - 10 | 15 - 20 |
| Loam | 0.20 - 0.30 | 0.07 - 0.17 | 0.13 - 0.18 | 8 - 10 | 16 - 22 |
| Silt loam | 0.22 - 0.36 | 0.09 - 0.21 | 0.13 - 0.19 | 8 - 11 | 18 - 25 |
| Silt | 0.28 - 0.36 | 0.12 - 0.22 | 0.16 - 0.20 | 8 - 11 | 22 - 26 |
| Silt clay loam | 0.30 - 0.37 | 0.17 - 0.24 | 0.13 - 0.18 | 8 - 11 | 22 - 27 |
| Silty clay | 0-30 - 0.42 (sic; read 0.30 - 0.42) | 0.17 - 0.29 | 0.13 - 0.19 | 8 - 12 | 22 - 28 |
| Clay | 0.32 - 0.40 | 0.20 - 0.24 | 0.12 - 0.20 | 8 - 12 | 22 - 29 |

Table 19 is in Chapter 7, not Chapter 8. Ch. 8 refers to it for θFC and θWP ([Ch. 8, TAW section][ch8]). TEW = 1000(θFC − 0.5 θWP) Ze (Eq. 73) ([Ch. 7, Eq. 73][ch7]). The "0-30" for silty clay is printed that way on the page.

---

## 4. Annex 8: the worked daily irrigation schedule

Annex 8 is a spreadsheet example (Figure 8.1 and the Excel formulas in Box 8.1). It uses the **dual** Kc approach for the dry bean crop from Boxes 15 and 16. It schedules irrigation with the daily root zone balance of Ch. 8 ([Annex 8, intro][an8]). Timing is "based on the management allowed depletion (MAD)" ([Annex 8][an8]).

### 4.1 Inputs (boxed cells in Fig. 8.1)

Crop, planting month and day, L_ini/L_dev/L_mid/L_late = 25/25/30/20 (Table 11), Kcb_ini/mid/end = 0.15/1.10/0.25 (Table 17; adjusted to 0.15/1.13/0.23), Kc_min 0.15, max height 0.4 m, fw (irrig.) 0.5, REW 8 mm, TEW 22 mm, initial De 18 mm, initial fw 1, Root_min 0.20 m, Root_max 0.80 m, Avail. Water 160 mm/m (= θFC − θWP), MAD 70% during the initial stage and 45% after it. Daily user columns: Month, Day, Year, Tmax, u2, Tdew, ET0, P−RO ([Annex 8, Fig. 8.1, Box 8.1, Table 8.1][an8]).

### 4.2 Columns (left to right in Fig. 8.1)

- A–N: date, J (day of year), Tmax, u2, Tdew, ET0, e°(Tdew), e°(Tmax), RHmin (Eq. 63), P−RO.
- O–AC, "Evaporation Calculation": Kcb (Eq. 66), height, Kc_max (Eq. 72), Net Irrig./fw (beginning of day), fc (Eq. 76), fw, few (Eq. 75), De start, Kr (Eq. 74), Ke (Eq. 71), E, DPe, De end (Eq. 77), Kc, ETc.
- AE–AL, "Irrigation Scheduling": Root depth, RAW, Ending Deplet. (first estimate), Net Irrigation Needed, Drainage DP (from precip.), Ks, Adjusted Kc (Ks·Kcb + Ke), Corrected Ending Depletion.
- AO–AP: running sums of u2 and RHmin, used to average them over mid-season for Eq. 70.

([Annex 8, Fig. 8.1 images x0490e7e/7f/7g.gif][an8]). Note: some cell labels in the HTML Box 8.1 transcription are garbled (e.g. "AK14" used for the adjusted Kc formula, "AU 4" for the corrected depletion, "015" for "O15"). The column meanings above come from the Figure 8.1 headers.

### 4.3 Procedure, step by step (as the annex does it)

1. **Stage dates.** J_plant, J_dev, J_mid, J_late and J_harv are computed from the planting date plus the cumulative stage lengths ([Box 8.1, cells Q3–Q7][an8]).
2. **Daily Kcb** by Eq. 66 (nested IFs). Before planting and after harvest it uses Kcb_ini ([Box 8.1 O14, fn 2][an8]). Kcb_mid and Kcb_end are adjusted with Eq. 70 using mid-season average u2 and RHmin ([Box 8.1 J5–J6, K8–K9][an8]).
3. **Crop height** = (Kcb / Kcb_mid) × max height. It is never allowed to decrease ([Box 8.1 fn 3][an8]).
4. **Root depth** grows with Kcb ([Annex 8, Eq. 8-1 and 8-2][an8]):
   ```
   Zr_i = Zr_min + (Zr_max − Zr_min) × (Kcb_i − Kcb_ini)/(Kcb_mid − Kcb_ini)   for J < J_mid   (8-1)
   Zr_i = Zr_max                                                               for J ≥ J_mid   (8-2)
   ```
   Alternative, time-based: `Zr_i = Zr_min + (Zr_max − Zr_min)(J − J_start)/(J_max − J_start)` (8-3). "For many annual crops, Zr_min can be estimated as 0.15 to 0.20 m." ([Annex 8][an8]). Root depth is never allowed to decrease ([Box 8.1 fn 8][an8]).
5. **RAW of the day** = MAD × Zr × Avail. Water. MAD is 70% before J_dev and 45% after. The annex assumes p = MAD ([Box 8.1 AF14; Annex 8 text; fn 11][an8]). Check: 0.70 × 0.20 × 160 = 22.4 mm, as shown in Fig. 8.1.
6. **Evaporation layer** (Ch. 7). Rain and irrigation are added early in the day. Irrigation is divided by fw so the depth applies to the wetted part only (`R = AH_prev / fw`). The water balance of De gives Kr, Ke, E, Kc and ETc ([Box 8.1 R15–AC15, fn 4–7][an8]).
7. **First estimate of ending depletion** (Eq. 85, no drainage, unstressed ETc): `Dr_end = Dr_prev_end − (P−RO) − I_prev_decided + ETc` ([Box 8.1 AG15, fn 9][an8]).
8. **Drainage** (Eq. 88): `DP = max((P−RO) + I − ETc − Dr_prev, 0)` ([Box 8.1 AI15][an8]).
9. **Ks** (Eq. 84): if the first-estimate depletion > RAW, Ks = (TAW − Dr)/(TAW − RAW), with TAW = Zr × 160. Otherwise Ks = 1 ([Box 8.1 AJ, fn 11][an8]).
10. **Adjusted Kc** = Ks·Kcb + Ke (Eq. 80). The **corrected ending depletion** is recomputed with Eq. 85 using ETc adj and DP. This is the value carried forward as Dr,i-1 for the next day ([Box 8.1 AK/AL, fn 9][an8]).
11. **Trigger.** At the end of day i, if the depletion > RAW, the net irrigation needed = that depletion. It is "presumed to be applied at the beginning of the next day" ([Box 8.1 AH, fn 10; Fig. 8.1 cell AH8][an8]). The formula uses a strict `AG > AF`, while the annex text says "greater than or equal to RAW". The rule is active only from J_plant until the middle of the late season: "no irrigation will be desired during the last one-half of the late-season period" ([Box 8.1 AH, fn 10; Annex 8 text][an8]).
12. **Net depth.** "It is assumed that the net depth of irrigation that is retained in the crop root zone is exactly equal to the depletion depth of the previous day", i.e. refill to field capacity. "This assumption presumes perfect knowledge of soil water depletion ... and can be changed by the user as needed." ([Annex 8, text][an8])

Concrete trace from Fig. 8.1 (planting J = 142, May 22). On row 21 (J 142) the ending depletion is 25.3 mm, above RAW 22.4, so the net irrigation needed is 25.3 mm. On row 22 that water is applied at the start of the day. The evaporation side records 50.6 mm (= 25.3 / fw 0.5), Ke jumps to 0.61, and the ending depletion falls to 3.7 mm. Ks was 0.83 and 0.70 on the two days before, because irrigation is decided only after RAW is exceeded ([Annex 8, Fig. 8.1 rows 20–22][an8]). The annex says this delay "occasionally causes a small amount of stress on the day prior to irrigation" ([Annex 8][an8]).

### 4.4 Rain, effective rain, efficiency

- Rain enters as a user column **P − RO**. "It is assumed that runoff from precipitation is zero." Runoff methods can be added from hydrology textbooks ([Annex 8, text][an8]).
- "All drainage from the root zone due to excess precipitation occurs on the day of the precipitation event." Drainage is computed with Eq. 88 ([Annex 8; Box 8.1 AI][an8]).
- All rain and irrigation are assumed to happen early in the morning. Scheduling uses the depletion at the end of the previous day ([Annex 8][an8]).
- The term "effective rainfall" does not appear in Ch. 5–8, Ch. 10 or Annex 8 (searched). The only related rule is in Ch. 8: rain below about 0.2 ET0 per day can be ignored ([Ch. 8][ch8]).
- **Irrigation efficiency / gross depth: not handled.** Annex 8 schedules **net** depths only. The words "efficiency" and "gross" do not appear on the Ch. 5, 6, 7, 8 or Annex 8 pages (searched with whole-word matching). In Ch. 8, I is defined as the net infiltrated depth over the whole field ([Ch. 8, Eq. 85][ch8]).
- The annex warns: "The procedure used to determine the irrigation schedule and the assumptions used may not always be appropriate. The reader should modify the irrigation scheduling procedure to fit the conditions of the local area." ([Annex 8][an8])

---

## 5. Implications for a daily planner

### 5.1 Minimal inputs that FAO-56 requires (single-Kc path)

| Input | Used in | Source |
| --- | --- | --- |
| Daily ET0 [mm] | ETc = Kc·ET0 | Eq. 56/58 |
| Daily rain P [mm] (and RO, or assume 0 as Annex 8 does) | Eq. 85 | Ch. 8; Annex 8 |
| Crop → Kc_ini, Kc_mid, Kc_end, h | Kc curve, Eq. 62/65 | Table 12 |
| Planting date and L_ini/L_dev/L_mid/L_late → days since planting | Eq. 66 | Table 11 |
| u2 and RHmin (stage averages) if adjusting Kc_mid/Kc_end | Eq. 62/65 | Ch. 6 |
| θFC, θWP (or their difference) | TAW, Eq. 82 | Table 19 |
| Zr (max; optionally Zr_min and growth) | TAW, Eq. 82; Eq. 8-1 | Table 22; Annex 8 |
| p (optionally adjusted for ETc) | RAW, Eq. 83 | Table 22 + fn 2 |
| Initial depletion Dr,0 (or assume ≈ 0 after heavy wetting) | Eq. 87 | Ch. 8 |
| fw for drip (Table 20: trickle 0.3–0.4) | Kc_ini (Eq. 60/61), or few for the dual approach (Eq. 75) | Ch. 6; Ch. 7 |
| Daily applied irrigation (net, field average) | Eq. 85 | Ch. 8 |

FAO-56 recommends the dual approach for high-frequency microirrigation ([Ch. 5, Table 10][ch5]). The single Kc path with the Eq. 60 fw adjustment for Kc_ini is the simpler option FAO-56 also documents. The planner must pick one (see 5.2).

### 5.2 What FAO-56 does NOT specify (planner decisions, NOT from FAO-56)

> Everything in this subsection is **not from FAO-56**. These are gaps the planner design must fill.

- **Drip hardware conversion.** FAO-56 has no emitter flow rate, emitter or lateral spacing, or method to turn a net depth (mm) into run time (h:min) or litres per plant. Converting mm over the plot area to minutes of drip is a planner decision.
- **Gross depth and efficiency.** No application efficiency, distribution uniformity or leaching fraction is applied. Annex 8 uses net depth only.
- **Wetted-volume bucket for drip.** FAO-56 uses fw for surface evaporation (Kc_ini, few). It does not reduce TAW or RAW to the wetted soil volume under drip. Whether TAW is computed over the whole plot or only the wetted strip is a planner decision.
- **Trigger and depth policy.** Annex 8 uses "depletion > RAW → refill to field capacity the next morning". FAO-56 allows I ≤ Dr and irrigation "before or at" RAW. It does not set a fixed daily or high-frequency drip policy (e.g. replace yesterday's ETc every day), a minimum event size, a maximum per event, or whether to fire before RAW to avoid the 1-day stress lag.
- **Forecast rain.** FAO-56 balances observed P. Whether to hold back irrigation because rain is *forecast*, and how far to trust a forecast, is not covered.
- **Runoff and effective rain.** No RO method is given (left to hydrology texts). Annex 8 assumes RO = 0. The only rain filter is "< ~0.2 ET0 per day can be ignored".
- **Choosing among Table 11 variants and ranges.** FAO-56 does not say which regional row to use, how to treat pepper "25/30", where to sit in tomato Kc_end 0.70-0.90 or Zr 0.7-1.5, or when to use the staked-crop values (1.20 / 1.15). It says only "use local information".
- **Missing u2/RHmin.** Whether to apply Eq. 62/65 at all (vs. Table 12 as-is), and with what data, is up to the planner. Tables 15/16 give generic classes.
- **Mulch.** Whether plots use plastic mulch, and which reduction to apply from the 10–30% range, is a planner input. FAO-56 gives only ranges (Ch. 10).
- **Initial state and resets.** Where Dr,0 comes from (measurement, or "assume field capacity at planting") and how to reset after a missed day or an unknown irrigation is not specified beyond Eq. 87.
- **End of irrigation season.** Annex 8 stops irrigating at half of the late season for beans and says this "may need to be modified for some other crops". No rule is given for tomato or pepper.

---

## 6. Could not verify / caveats

- **Equation images:** the `/3/x0490E/*.gif` image URLs redirect to openknowledge.fao.org. Eqs. 59, 61, 62, 63, 65, 66, 84, 98, 8-1 and 8-3 and the Figure 8.1 spreadsheet were read from the `/4/x0490e/` mirror GIFs instead. Eqs. 56–58, 60, 69, 75, 80–83 and 85–88 are plain text on the `/3/` pages.
- **Figures 29, 30, 41, 8.2 and 8.3** (Kc_ini charts, p vs ETc, Annex 8 Kc and depletion plots) are images and were not read in detail. Only their captions and the text that refers to them were used.
- **Annex 7** (Kc_ini numerical method, Eq. 7-3) was not read. It is referenced only.
- **Box 8.1** HTML transcription has typos in cell names (noted in §4.2). Column meanings come from the Fig. 8.1 images.
- The full Figure 8.1 (all ~170 days) was not checked row by row. Only the first rows (May 15–27) visible in the three image panels were read.

---

## Sources

Pages read (all fetched 2026-11-15):

- Index: https://www.fao.org/3/x0490E/x0490e00.htm
- Chapter 5 – Introduction to crop evapotranspiration (ETc): https://www.fao.org/3/x0490E/x0490e0a.htm
- Chapter 6 – ETc, single crop coefficient (Kc): https://www.fao.org/3/x0490E/x0490e0b.htm
- Chapter 7 – ETc, dual crop coefficient (Kc = Kcb + Ke): https://www.fao.org/3/x0490E/x0490e0c.htm
- Chapter 8 – ETc under soil water stress conditions: https://www.fao.org/3/x0490E/x0490e0e.htm
- Chapter 9 – ETc for natural, non-typical and non-pristine vegetation: https://www.fao.org/3/x0490E/x0490e0f.htm
- Chapter 10 – ETc under various management practices: https://www.fao.org/3/x0490E/x0490e0g.htm
- Annex 8 – Calculation example for applying the dual Kc procedure in irrigation scheduling: https://www.fao.org/3/x0490E/x0490e0p.htm

Equation and figure images (mirror):

- https://www.fao.org/4/x0490e/x0490e2a.gif (Table 12 header, Kc_ini¹)
- https://www.fao.org/4/x0490e/x0490e2b.gif (Eq. 59)
- https://www.fao.org/4/x0490e/x0490e2c.gif (Eq. 61)
- https://www.fao.org/4/x0490e/x0490e2d.gif (Eq. 62)
- https://www.fao.org/4/x0490e/x0490e2e.gif (Eq. 63)
- https://www.fao.org/4/x0490e/x0490e2i.gif (Eq. 65)
- https://www.fao.org/4/x0490e/x0490e2k.gif (Eq. 66)
- https://www.fao.org/4/x0490e/x0490e2w.gif (Eq. 84)
- https://www.fao.org/4/x0490e/x0490e38.gif (Eq. 98)
- https://www.fao.org/4/x0490e/x0490e5z.gif (Eq. 8-1)
- https://www.fao.org/4/x0490e/x0490e60.gif (Eq. 8-3)
- https://www.fao.org/4/x0490e/x0490e7e.gif, https://www.fao.org/4/x0490e/x0490e7f.gif, https://www.fao.org/4/x0490e/x0490e7g.gif (Figure 8.1 spreadsheet panels)

[ch5]: https://www.fao.org/3/x0490E/x0490e0a.htm
[ch6]: https://www.fao.org/3/x0490E/x0490e0b.htm
[ch7]: https://www.fao.org/3/x0490E/x0490e0c.htm
[ch8]: https://www.fao.org/3/x0490E/x0490e0e.htm
[ch9]: https://www.fao.org/3/x0490E/x0490e0f.htm
[ch10]: https://www.fao.org/3/x0490E/x0490e0g.htm
[an8]: https://www.fao.org/3/x0490E/x0490e0p.htm
