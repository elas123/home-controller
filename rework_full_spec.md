# REWORK — Full Spec (Early Morning, Day, Evening, Night)


> This spec is deterministic, restart‑safe, presence‑aware, and keeps room‑level behavior out of the global controller.

---

## EARLY MORNING MODE — SET IN STONE

### Workday Detection Rules (NEVER CHANGE)
1. **Kitchen motion between 04:50 and 05:00 (inclusive of start, exclusive of end) ⇒ WORKDAY.**
2. **Kitchen motion at or after 05:00:00 ⇒ DAY OFF.**

### Early Morning Activation
- Early Morning mode **ONLY** starts when **kitchen motion** triggers. Time alone never starts it.
- The **time** of the first kitchen motion determines **workday vs day‑off** classification.

### WORKDAY BEHAVIOR (SET IN STONE)
- **Trigger:** Early Morning starts by kitchen motion in **04:50–04:59**.
- **Ramp:** **Work ramp only**. Start **10%** → end **50%** brightness; color‑temp lights go **2000K** → **4000K**.
- **Work ramp end:** **05:40**. Do **not** auto‑set Away at 05:40.
- **After 05:40:** stay in Early Morning at final levels until iPhone presence flips to **Away**; then cancel any active ramp, set **Away**, and turn off lights.

### NON‑WORK RAMP SYSTEM (SET IN STONE)
- **Starts:** Early Morning by kitchen motion **@ ≥ 05:00**.
- **Start values:** **10%**, **2000K** (same as work ramp start).
- **End time:** Exactly when **Day** commits (varies daily; see Day logic).
- **End brightness:** Determined by priority:
  1. Teaching/Learning DB
  2. Adaptive learning (learned values)
  3. Intelligent calculation
  4. Hardcoded fallback
- **End temperature:** **5000K** (to differentiate from the work ramp).
- **Transition:** Smooth ramp from start values to the computed Day commit targets; **finish exactly at Day commit** (no visible jump).

### BULLET SUMMARY (Early Morning)
- Kitchen motion **04:50–04:59** ⇒ **Workday**; work ramp 10%/2000K → 50%/4000K; ends **05:40**; end EM only by **presence→Away**.
- Kitchen motion **≥ 05:00:00** ⇒ **Day Off**; non‑work ramp 10%/2000K → dynamic%/5000K; ends exactly at **Day commit** (seamless to Day).
- Early Morning **only** starts by **kitchen motion**; never by clock.

---

## EVENING MODE — WINDOW & STARTUP (SET IN STONE)

### Definitions
- **Evening Window:** from **sunset − 15 minutes** until **23:00** local (unless an `input_datetime.evening_time_cutoff` explicitly overrides; if present, that time becomes the end of the window).
- **Helper values (restart‑safe, published by tiny helpers):**
  - `pyscript.sunset_today` (ISO local string)
  - `pyscript.sunrise_today` (ISO local string)
  - `sensor.evening_start_local = sunset_today − 00:15:00`
  - `binary_sensor.in_evening_window = on` when `evening_start_local ≤ now < cutoff_today` **AND** hour ≥ **15**

### Evening Activation (SET IN STONE)
- Evening **ONLY** starts when `binary_sensor.in_evening_window == on` (PM guard applies).
- Missed‑trigger protection: On startup/reload, if `in_evening_window == on` **and not Away**, set **Evening** immediately and mark Evening active.
- **No bounce back from Night**: see Night monotonic rules below.

---

## DAY MODE — HYBRID GATE (NO LUX; SET IN STONE)

**Goal:** Seasonal, bright‑enough, never too early.

### Inputs
- `sensor.day_earliest_time` = **07:30** floor (or `input_datetime.day_earliest_time` if present).
- `sensor.day_min_start` = `pyscript.sunrise_today + 00:30:00`.
- **Monthly elevation targets** (`sensor.day_elev_target`):  
  Jan **12°**, Feb **11°**, Mar **10°**, Apr **9°**, May **9°**, Jun **8°**, Jul **8°**, Aug **9°**, Sep **10°**, Oct **11°**, Nov **11°**, Dec **12°**.

### Readiness Logic
1. `time_gate_ok = now ≥ max(day_min_start, day_earliest_time)`
2. `elev_gate_ok = sun.sun.elevation ≥ day_elev_target`
3. `not_in_evening = (binary_sensor.in_evening_window == off)`
4. `binary_sensor.day_ready_now = time_gate_ok AND elev_gate_ok AND not_in_evening`  
   Hysteresis: once **on**, turn **off** only if elevation drops below `(target − 3°)` for ≥ 2 minutes.

### Activation
- Controller **proposes Day** only when `day_ready_now == on`. **No clock‑only shortcut.**
- **Non‑Work EM → Day handoff:** ramp ends at `day_commit_time = max(day_min_start, day_earliest_time, learned_day_start)`. At that moment, mode flips to **Day** with **no jump**.

---

## NIGHT MODE — MONOTONIC + TV‑FIRST + FAILSAFE‑ONLY‑IF‑NEEDED (SET IN STONE)

### Monotonic daily sequence (one‑way)
- Within a single local day, modes are one‑way: **Day → Evening → Night**.
- **Once Night starts on a date, it never goes back to Evening on that date.**
- Implementation marker (conceptual): **`night_started_on = YYYY‑MM‑DD`** (record when Night first starts).

### Night triggers
1) **Bedroom Apple TV turns ON (any state except `off`/`unavailable`) → Set Night immediately.**  
   - Apply a small **5s debounce** to avoid flapping.
   - Set `night_started_on = today`.
2) **Failsafe at 23:00 local** → **Only fire if all are true:**  
   - Current mode is **Evening**  
   - **Not Away**  
   - `night_started_on != today`  
   → then **Set Night**. (If Living‑Room TV behavior is used, see next section.)

### Night Cutover (what happens when Night is set)
- **Turn off every light that is ON.**  
- Cutover is a **single** global action on Night **entry** (no per‑room logic here).  
- Room‑level packages can still do their own Night policies separately (e.g., blocking motion).

### Living‑Room TV exception at 23:00 (optional behavior)
- If you use a living‑room exemption: when 23:00 failsafe sets Night **and** the **Living‑Room Apple TV** is **on**, set Night **without** running the cutover and mark **cutover_pending = on**.  
- When the **Bedroom Apple TV** later turns **on**, run the **cutover immediately** and clear **cutover_pending**.  
- If never triggered, **cutover_pending** clears automatically at the **first transition out of Night** (e.g., EM/Day).

### Bounce elimination
- After Night starts (by TV or failsafe), `night_started_on = today` blocks any return to Evening until the date rolls over at midnight.

### Startup / reload
- Restart **inside the Evening window** and `night_started_on != today` → set/keep **Evening** (not Away).
- Restart **at/after 23:00** and not Away:
  - If `night_started_on != today` → **Set Night** (failsafe substitute on boot).
  - If `night_started_on == today` → keep **Night**.

### Manual overrides
- After **23:00**, **Night is sticky**. Manual flips are ignored unless you explicitly call a force service.

### Quick acceptance checks
1) 21:30 Bedroom TV ON → Night starts; 21:45 TV OFF → **stays Night** (no Evening bounce).  
2) No TV all evening → 23:00 → Night starts (failsafe fired).  
3) Night started at 20:55 (TV), then restart at 22:10 → comes back as **Night** (`night_started_on == today`).  
4) Restart at 22:10 (no TV so far) → comes back **Evening**; at 23:00, Night starts (failsafe).  
5) Away at 23:00 → failsafe skipped; remains **Away**.

---

## STARTUP / RELOAD DECISION TABLE (presence‑aware)

If **Away**, always keep **Away** (controller never auto‑overrides Away).

| Time now | in_evening_window | ≥ 23:00 | Phones | Action |
|---|---:|---:|---|---|
| 00:00–04:44 | n/a | yes | both home | **Night** (Night rules apply) |
| 04:45–07:29 | n/a | no  | both home | Hold (no forced EM; wait for **kitchen motion**) |
| 07:30–sunset−15m | off | no | both home | Evaluate **Day** via `day_ready_now`; else stay |
| sunset−15m–22:59 | on  | no | both home | **Evening** |
| ≥ 23:00        | n/a | yes | both home | **Night** (failsafe rules; optional LR‑TV exception) |
| any            | any | any | any away | **Away** |

---

## OBSERVABILITY (MUST‑HAVE SENSORS / FLAGS)

- `pyscript.home_state` (**Day / Evening / Night / Early Morning / Away**)
- `sensor.pys_last_action` (timestamps + reason strings for major transitions)
- `pyscript.sunset_today`, `pyscript.sunrise_today` (ISO local)
- `sensor.evening_start_local` (ISO local), `binary_sensor.in_evening_window` (on/off)
- `sensor.day_min_start`, `sensor.day_earliest_time`, `sensor.day_elev_target`, `binary_sensor.day_ready_now`, `sensor.day_ready_reason`
- **Night monotonic marker:** `sensor.night_started_on` (date string), or equivalent attribute
- **Optional:** `binary_sensor.pys_night_cutover_pending` (on/off) if using LR‑TV exception

---

## NIGHT MODE — DECISIONS LOCKED

- **Monotonic guard:** **Use `night_started_on` (date marker)**. Once Night starts on a date, **never** re‑enter Evening that date; auto‑clears at midnight.
- **Bedroom TV trigger:** **any state ≠ `off`/`unavailable`** (with ~5s debounce) ⇒ **Night**.
- **Failsafe 23:00:** **only** if mode is **Evening**, **not Away**, and `night_started_on != today`.
- **Night cutover:** **Turn off every light that is ON** (single global action on Night entry).
- **LR‑TV exception at 23:00 (if used):** Night without cutover; set **cutover_pending = on**; run cutover when Bedroom TV later turns on; auto‑clear pending when Night ends.
- **Room‑level rules:** stay separate in room packages (kitchen/bath/living/bedroom).

---

## OPTIONAL: ROOM POLICY MATRIX (To be defined in room packages; not in controller)

| Room | Night rule | Notes |
|---|---|---|
| Kitchen | Block auto‑on during Night | Manual allowed? yes/no |
| Bathroom | Allow specific “nightlight” entity at low level; block others | Exact cap % if desired |
| Living Room | Local rules around TV; controller handles Night entry & optional pending | — |
| Bedroom | Normal Night; TV **sets Night** | — |
| Hallway/Laundry | Block auto‑on during Night | — |
| Closet | Follows bedroom/bath pattern | — |

---

## APPENDIX — WHY NO “RESET TIMES” & WHY HELPERS MAY BE LATE

- **No reset times needed:** Using **`night_started_on`** (date marker) eliminates the old “evening_done_today” boolean and any “reset at 00:05/04:45” confusion. The date rolls over; the guard clears itself.
- **Why helpers may be late at boot:** On a fresh restart, the tiny helper that publishes `pyscript.sunset_today` / `pyscript.sunrise_today` might still be initializing. Until those are present, the controller simply **doesn’t start Evening** from the window; it logs one line and reevaluates once helpers appear.

---

## COMPLETE ONE‑PAGE SUMMARY (for quick reference)

- **Early Morning:** **Motion‑only** start. 04:50–04:59 ⇒ Workday (work ramp to 05:40). ≥ 05:00 ⇒ Day‑off (non‑work ramp to Day commit). No time‑based EM starts.
- **Day:** Hybrid gate (≥ max(sunrise+30m, 07:30) **AND** elevation ≥ monthly target), and **not** in Evening. Hysteresis 3°.
- **Evening:** Window **sunset−15 → 23:00**. Starts only when `in_evening_window == on` and not Away. Startup respects window.
- **Night:** **TV‑first** (bedroom TV on ⇒ Night) and **failsafe‑only‑if‑needed** at 23:00. **Monotonic** per day via `night_started_on`. **Cutover** on entry = **turn off every light that is ON**. Optional LR‑TV exception defers cutover until bedroom TV on. Room rules remain in room packages.
