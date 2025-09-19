# REWORK

I want to be called rework

## EARLY MORNING MODE LOGIC - SET IN STONE

### Workday Detection Rules (NEVER CHANGE):
1. **Kitchen motion sensors trigger between 4:50 AM and 5:00 AM ANY DAY OF THE WEEK = WORKDAY**
   - End of story, no deviating from that logic
   
2. **Kitchen motion sensors trigger AFTER 5:00 AM = DAY OFF** 
   - End of story, these are the two logic that are set in stone they never change ever

### Early Morning Mode Activation:
- **If WORKDAY (motion 4:50-5:00 AM):** Start Early Morning mode when kitchen motion triggers
- **If DAY OFF (motion after 5:00 AM):** Start Early Morning mode when kitchen motion triggers

**Bottom Line:** Early morning mode ONLY starts when kitchen motion triggers - that is what turns on early morning mode. The TIME of the trigger determines if it's a workday or day off.

## WORKDAY BEHAVIOR - SET IN STONE

### Morning Ramp for Workdays:
- **Trigger:** Early morning mode starts (kitchen motion 4:50-5:00 AM)
- **Ramp Type:** Work ramp ONLY - no other ramps
- **End Time:** 5:40 AM (when I leave for work, system goes to away mode, lights turn off)

### Work Ramp Specifications:
- **Brightness:** Start at 10% → End at 50%
- **Transition:** Smooth transition from 10% to 50%
- **Temperature Control Lights (Lamp One, Lamp Two, Closet Light):**
  - Start: 2000K → End: 4000K

## NON-WORK RAMP SYSTEM - SET IN STONE

### Non-Work Ramp Specifications:
- **Start Values:** 10% brightness, 2000K temperature (same start as work ramp)
- **End Time:** Dynamic - when day mode is supposed to start (different every day)
- **End Brightness:** Dynamic priority hierarchy:
  1. Teaching/Learning data - if available from database
  2. Adaptive learning sensors - learned brightness values  
  3. Intelligent brightness sensors - calculated values
  4. Hardcoded fallbacks - as last resort
- **End Temperature:** 5000K (so you can tell the difference from work ramp)
- **Temperature Control Lights:** Lamp One, Lamp Two, Closet Light only
- **Transition Logic:** Calculate minutes between Early Morning mode start (kitchen motion trigger) and day mode start time
- **Smooth Transition:** From start values to end values over calculated time period
- **Seamless Handoff:** Transition ends exactly when day mode is supposed to start - NO jarring of lights, you won't even notice the transition because lights match exactly what day mode brightness should be

## COMPLETE BULLET STYLE SUMMARY

### WORKDAY DETECTION (SET IN STONE - NEVER CHANGE):
• Kitchen motion sensors trigger between 4:50 AM and 5:00 AM ANY DAY OF THE WEEK = WORKDAY
• Kitchen motion sensors trigger AFTER 5:00 AM = DAY OFF
• End of story, no deviating from these two logic rules

### EARLY MORNING MODE ACTIVATION:
• Early morning mode ONLY starts when kitchen motion triggers
• Kitchen motion trigger is what turns on early morning mode
• The TIME of the kitchen motion trigger determines if it's a workday or day off

### TWO SEPARATE RAMP SYSTEMS:

#### WORK RAMP SYSTEM (Kitchen motion 4:50-5:00 AM):
• **Start:** 10% brightness, 2000K temperature
• **End:** 50% brightness, 4000K temperature  
• **Duration:** Fixed end time at 5:40 AM (when leaving for work)
• **Lights affected:** Lamp One, Lamp Two, Closet Light (for temperature)
• **Transition:** Smooth ramp from start to end values
• **Result:** System goes to away mode at 5:40 AM, lights turn off

#### NON-WORK RAMP SYSTEM (Kitchen motion after 5:00 AM):
• **Start:** 10% brightness, 2000K temperature
• **End Time:** Dynamic - when day mode is supposed to start (different every day)
• **End Brightness:** Dynamic priority hierarchy:
  1. Teaching/Learning data (from database)
  2. Adaptive learning sensors (learned brightness values)  
  3. Intelligent brightness sensors (calculated values)
  4. Hardcoded fallbacks (as last resort)
• **End Temperature:** 5000K (to differentiate from work ramp)
• **Transition:** Smooth ramp calculated over time between Early Morning start and Day mode start
• **Result:** Seamless handoff to day mode - no jarring light changes, you won't notice the transition


---

REWORK — Addendum (Evening & Day)
This addendum extends the original REWORK spec. It keeps all “set-in-stone” Early Morning and ramp rules intact, and adds bullet-proof logic for Evening and Day—with no lux dependencies. Everything here is deterministic, restart-safe, and presence-aware.
EVENING MODE — BULLET-PROOF BY SUNSET (SET IN STONE)
Definitions
Evening Window = from sunset − 15 minutes until Evening Cutoff (default 22:00 unless overridden by input_datetime.evening_time_cutoff).
Today Sensors (restart-safe; published by a tiny helper script):
pyscript.sunrise_today (ISO local string)
pyscript.sunset_today (ISO local string)
sensor.evening_start_local = sunset_today − 15m
binary_sensor.in_evening_window = on when evening_start_local ≤ now < cutoff_today
Evening Activation (SET IN STONE)
Evening mode ONLY starts when binary_sensor.in_evening_window is on.
Evening NEVER starts in the morning. Guard: the controller only considers Evening between 15:00 and cutoff.
Missed-Trigger Protection: On startup/reload, if in_evening_window == on (and not Away), immediately set Evening and mark evening_mode_active = on.
Evening Ramp (OPTIONAL)
If enabled, Evening start may launch a smooth ramp to:
EV_RAMP_TARGET_BRI (e.g., 20%)
EV_RAMP_TARGET_K (e.g., 2000K)
Landing exactly at EV_RAMP_END_TIME (e.g., 21:00).
If not enabled, Evening only changes mode—no light ramp.
Evening Locks (unchanged from base)
While evening_mode_active == on, mode stays Evening until explicitly ended.
If evening_done_today == on, do not restart Evening the same night; controller will steer to Night around cutoff.
End Evening on your existing triggers (e.g., bedtime media, cutoff).
DAY MODE — HYBRID (SUNRISE + ELEVATION + FLOOR) (SET IN STONE)
Goal: Seasonal, bright-enough, no lux, and never too early (no 6:30am).
Signals & Knobs (published by a tiny helper script day_schedule.py)
pyscript.sunrise_today (restart-safe)
sensor.day_min_start = sunrise_today + 30m (time gate)
sensor.day_earliest_time = 07:30 (floor; if input_datetime.day_earliest_time exists, use it; else 07:30)
sensor.day_elev_target = monthly map (degrees above horizon) (elevation gate)
Jan 12° · Feb 11° · Mar 10° · Apr 9° · May 9° · Jun 8° · Jul 8° · Aug 9° · Sep 10° · Oct 11° · Nov 11° · Dec 12°
(You may raise any month by +1° if you want it a bit later; e.g., set Sep = 11° to nudge later toward ~8:30.)
binary_sensor.day_ready_now = on only when:
now ≥ max(day_min_start, day_earliest_time) AND
sun.sun.elevation ≥ day_elev_target
Hysteresis: once on, turn off only if elevation drops below (day_elev_target − 3°); apply a small debounce (e.g., 2–5 min) to avoid flapping.
sensor.day_ready_reason (e.g., time_ok, elev=10.7° ≥ 10°)
Day Activation (SET IN STONE)
The controller proposes Day only when binary_sensor.day_ready_now == on and you are not in the Evening window.
No hour-only shortcuts. Day is never driven purely by clock time.
Seasonal behavior: later in winter (higher target), earlier in summer (lower target), but never before 07:30 due to the floor.
Non-Work Early Morning → Day (Seamless Handoff)
Non-Work Ramp ends exactly at:
day_commit_time = max(day_min_start, day_earliest_time, learned_day_start)
learned_day_start comes from your existing priority stack:
Teaching/Learning data (DB)
Adaptive learning (learned values)
Intelligent calculation
Fallback
At day_commit_time, ramp finishes at the Day targets and mode flips to Day—no light jump.
EARLY MORNING & WORKDAY AWAY (CLARIFIED; SET IN STONE)
(Restate key pieces that interact with Day/Evening; unchanged from base intent, but made explicit for bullet-proofing.)
Early Morning Start (unchanged; hard rules)
Kitchen motion 04:50–05:00 ⇒ classify WORKDAY; start Early Morning and Work Ramp.
Kitchen motion ≥ 05:00:00 ⇒ classify DAY OFF; start Early Morning and Non-Work Ramp.
No other way to start Early Morning. Time can’t start it.
Workday Behavior (presence-only Away)
Work Ramp: 10%/2000K → 50%/4000K, smooth, ends at 05:40.
Do NOT auto-set Away at 05:40.
After 05:40, stay in Early Morning at final levels until iPhone presence flips to away.
When iPhone leaves: cancel any active ramp (if still running), set Away, turn off lights.
(This is the only EM end on workdays.)
Non-Work Behavior (unchanged)
Non-Work Ramp: 10%/2000K → dynamic%/5000K (your existing priority stack), smooth over computed duration.
Ends exactly at day_commit_time (above) → mode becomes Day, seamless.
TRANSITION PRIORITY & SAFETY (SET IN STONE)
While Early Morning is active:
Workday: only presence → Away may end it. No time/elevation/sunset logic can override.
Non-Work: only non-work ramp completion at day_commit_time may end it. No other logic can override.
Evening is considered only in PM (≥ 15:00) and only inside the Evening Window.
Away is never auto-overridden.
Startup/Reload: Evaluate in_evening_window and day_ready_now immediately and behave as if you never missed the triggers.
OBSERVABILITY (MUST-HAVE SENSORS)
To keep everything auditable in Developer Tools → States:
Evening
pyscript.sunset_today (ISO local)
sensor.evening_start_local
binary_sensor.in_evening_window
Day
pyscript.sunrise_today
sensor.day_min_start (sunrise + 30m)
sensor.day_earliest_time (defaults to 07:30)
sensor.day_elev_target (current month’s °)
binary_sensor.day_ready_now (true/false)
sensor.day_ready_reason (text: why it flipped)
Early Morning Lifecycle
sensor.pys_morning_ramp_profile = work | day_off
sensor.pys_morning_ramp_reason (e.g., motion@04:55)
sensor.pys_last_action (timestamps of key transitions)
(Optional) sensor.pys_em_end_reason / sensor.pys_em_end_time (e.g., presence_away)
CONFIGURATION (ALL OPTIONAL; DEFAULTS PROVIDED)
input_datetime.evening_time_cutoff → Evening cutoff (default 22:00)
input_datetime.day_earliest_time → Day floor (default 07:30)
Monthly elevation targets → override any month’s default if you want it later/earlier
(e.g., set Sep = 11° to push toward ~8:30)
Evening ramp targets: EV_RAMP_TARGET_BRI, EV_RAMP_TARGET_K, EV_RAMP_END_TIME
No lux anywhere in this addendum.
COMPLETE BULLET STYLE SUMMARY
EVENING (SET IN STONE)
• Evening Window = sunset − 15m → cutoff (default 22:00)
• Start Evening only when in_evening_window == on (PM only)
• On startup, if window is active → set Evening immediately
• (Optional) Ramp to targets by EV_RAMP_END_TIME
• Locks: evening_mode_active keeps Evening; evening_done_today prevents restarts
DAY (SET IN STONE; NO LUX)
• Hybrid Gate: time ≥ max(sunrise + 30m, 07:30) AND elevation ≥ monthly target
• Monthly targets (°): Jan 12 · Feb 11 · Mar 10 · Apr 9 · May 9 · Jun 8 · Jul 8 · Aug 9 · Sep 10 · Oct 11 · Nov 11 · Dec 12
• Controller proposes Day only when day_ready_now == on and not in Evening
• Non-Work EM: ramp ends exactly at max(sunrise+30m, 07:30, learned_day_start) → seamless Day
EARLY MORNING & WORKDAY AWAY (SET IN STONE)
• 04:50–05:00 motion ⇒ WORKDAY; start EM + Work Ramp (10%/2000K → 50%/4000K; ends 05:40)
• ≥ 05:00 motion ⇒ DAY OFF; start EM + Non-Work Ramp (→ Day commit)
• No auto-Away at 05:40; on workdays, EM ends only when iPhone goes away
• Non-work days: EM ends only at ramp completion (Day commit time)
PRIORITY & SAFETY
• EM cannot be ended by time/elevation/sunset—only by its designated exits
• Evening evaluated only 15:00 → cutoff within the window
• Away never auto-overridden
• Startup honors windows immediately (no missed triggers)



---

## NIGHT MODE — MONOTONIC + TV-FIRST + FAILSAFE-ONLY-IF-NEEDED (SET IN STONE)

### Monotonic daily sequence (one-way)
- Within a single local day, modes are one-way: **Day → Evening → Night**.
- **Once Night starts on a date, it never goes back to Evening on that date.**
- Implementation marker (conceptual): **`night_started_on = YYYY-MM-DD`** (record when Night first starts).

### Night triggers
1) **Bedroom Apple TV turns ON (any state except `off`/`unavailable`) → Set Night immediately.**  
   - Apply a small **5s debounce** to avoid flapping.
   - Set `night_started_on = today`.
2) **Failsafe at 23:00 local** → **Only fire if all are true:**  
   - Current mode is **Evening**  
   - **Not Away**  
   - `night_started_on != today`  
   → then **Set Night**.

### Night Cutover (what happens when Night is set)
- **Turn off every light that is ON.**
- Cutover is a **single** global action on Night **entry** (no per-room logic here).

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

## NIGHT MODE — DECISIONS LOCKED (NO ROOM RULES HERE)
- **Monotonic guard:** **Use `night_started_on` (date marker)**. Once Night starts on a date, **never** re-enter Evening that date; auto-clears at midnight.
- **Bedroom TV trigger:** **any state ≠ `off`/`unavailable`** (with ~5s debounce) ⇒ **Night**.
- **Failsafe 23:00:** **only** if mode is **Evening**, **not Away**, and `night_started_on != today`.
- **Night cutover:** **Turn off every light that is ON** (single global action on Night entry).
