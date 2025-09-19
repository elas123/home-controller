# REWORK — Master Spec (Updated)

This document supersedes previous notes where Evening ramp was optional. Evening ramp is now **SET IN STONE** with exact targets.

## EARLY MORNING MODE LOGIC — SET IN STONE
### Workday Detection (NEVER CHANGE)
1) Kitchen motion **04:50–05:00** ⇒ **WORKDAY**
2) Kitchen motion **≥ 05:00:00** ⇒ **DAY OFF**
Only kitchen motion starts Early Morning. Time can’t start it.

### Early Morning Activation
- On first kitchen motion, set **Early Morning** and classify **work** vs **day_off** per rules above.

### Workday (SET IN STONE)
- **Ramp:** 10% / 2000K → 50% / 4000K, smooth
- **Hold after 05:40**: remain in **Early Morning** at final levels until **phones go Away** (presence-only exit).

### Non‑Work (SET IN STONE)
- **Start:** 10% / 2000K  
- **End (dynamic):** land at **Day** targets **exactly at `day_commit_time`**  
- **End temperature:** **5000K**  
- **Priority for end brightness:** Teaching/Learning → Adaptive → Intelligent → Fallback
- **Seamless handoff:** At `day_commit_time`, lights already match Day; controller flips to **Day** with **no jump**.

## DAY MODE — HYBRID (SUNRISE + ELEVATION + FLOOR) — SET IN STONE
- `binary_sensor.day_ready_now == on` only when:
  - time ≥ max(`sensor.day_min_start` (= sunrise + 30m), `input_datetime.day_earliest_time` (default 07:30))
  - AND `sun.sun.elevation` ≥ monthly target (Jan 12°, Feb 11°, Mar 10°, Apr 9°, May 9°, Jun 8°, Jul 8°, Aug 9°, Sep 10°, Oct 11°, Nov 11°, Dec 12°)
- Hysteresis: off only if elevation < target − 3°, small debounce (2–5 min).
- Controller proposes Day only when **not** in Evening window.

**Publishers used by Morning Ramp (from controller):**
- `sensor.day_commit_time` = max(day_min_start, day_earliest_time, learned_day_start?)
- `sensor.day_target_brightness` = brightness via priority stack (fallback 70% if none)

## EVENING MODE — WINDOW & RAMP — SET IN STONE
### Evening Window (unchanged)
- Start = **sunset − 15m**; Cutoff = **`input_datetime.evening_time_cutoff`** (default **23:00**)
- `binary_sensor.in_evening_window == on` when `evening_start_local ≤ now < cutoff` and `now.hour ≥ 15`
- Startup/reload: if inside window and not Away, set **Evening** immediately.
- **Evening stays Evening** until Night cutover; do not restart same night if `evening_done_today == on`.

### Evening Ramp — NOW SET IN STONE
- **Time:** **20:00 → 21:00 (local)**  
- **Targets:** **hold brightness at 50%**, smooth **color temperature from 4000K → 2000K**  
- **Scope (temperature-capable lights):** **Lamp One, Lamp Two, Closet Light** (others ignore)  
- **Guards:** only when `home_state == "Evening"`, `binary_sensor.in_evening_window == on`, **not Away**  
- **Ramp starts once per day**; restart-safe (on startup between 20:00–21:00, it resumes).  
- This ramp is **independent** of TV exceptions; TV logic only affects **Night** cutover.

## NIGHT MODE — SET IN STONE
- **Cutover triggers:**
  - Bedroom Apple TV turns **on** ⇒ switch to **Night** immediately.
  - **23:00 failsafe** ⇒ switch to **Night** (unless LR Apple TV is on; see below).
- **LR Apple TV “pending” exception:** If `media_player.apple_tv_4k_livingroom == on` at 23:00, set **Night** mode but **defer mass-off** (set `pys_night_cutover_pending = on`); finish cutover when Bedroom Apple TV turns on.
- **Night cutover action:** **Turn off every light that is ON except WLEDs.**
- Away is never auto-overridden.

## TRANSITION PRIORITY & SAFETY — SET IN STONE
- **Early Morning (workday):** only presence→Away can end it (not time/elevation).
- **Early Morning (non‑work):** only ramp completion at `day_commit_time` ends it.
- **Evening logic** only considered 15:00 → cutoff within Evening window.
- **Away** is never auto-overridden.
- **Startup/Reload:** evaluate `in_evening_window` and `day_ready_now` immediately; behave as if triggers were never missed.

## OBSERVABILITY (MUST-HAVE SENSORS)
- Evening: `pyscript.sunset_today`, `sensor.evening_start_local`, `binary_sensor.in_evening_window`
- Day: `pyscript.sunrise_today`, `sensor.day_min_start`, `sensor.day_earliest_time`, `sensor.day_elev_target`, `binary_sensor.day_ready_now`, `sensor.day_ready_reason`, **`sensor.day_commit_time`**, **`sensor.day_target_brightness`**
- Early Morning lifecycle: `sensor.pys_morning_ramp_profile`, `sensor.pys_morning_ramp_reason`, `sensor.pys_last_action`, `sensor.pys_em_end_reason`, `sensor.pys_em_end_time`
- Night: `binary_sensor.pys_night_cutover_pending` (if LR TV on at 23:00)

## CONFIGURATION
- `input_datetime.evening_time_cutoff` (default 23:00)
- `input_datetime.day_earliest_time` (default 07:30)
- **Evening ramp knobs (fixed by spec for now):** 20:00→21:00, **50%**, **4000K→2000K**

## CRITICAL HELPERS (REQUIRED)
- `day_schedule.py` publishes: `pyscript.sunrise_today`, `pyscript.sunset_today`, `sensor.day_min_start`, `sensor.day_elev_target`, `binary_sensor.day_ready_now`, `sensor.day_ready_reason`
- Controller publishes: **`sensor.day_commit_time`**, **`sensor.day_target_brightness`**

## ACCEPTANCE TESTS (FAST CHECKS)
- Weekend morning: ramp lands at Day targets at `day_commit_time`; flip to Day with no visual jump.
- Workday: after 05:40, EM holds until phones go Away.
- 20:00–21:00: Evening ramp holds 50% and warms 4000K→2000K smoothly.
- 23:00: Night cutover; defer mass-off if LR TV on; finish when Bedroom TV turns on.
