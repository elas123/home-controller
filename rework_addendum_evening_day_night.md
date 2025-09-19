# REWORK — Addendum (Evening, Day & Night)

---

## EVENING → NIGHT FAILSAFE — OPTIMIZED (NO BOUNCE, NO RESET TIMES)
**Supersede note:** This policy **replaces** any prior use of an `evening_done_today` boolean. Use the **date-stamped** `night_started_on` guard instead; no separate reset time is needed.

**Goal:** Night should be **event-driven** and **monotonic** (never go back to Evening once Night starts). The **failsafe** runs **only** if the **Bedroom Apple TV didn’t start Night** earlier.

### Monotonic daily sequence (one-way, per calendar date)
- Within a single local day: **Day → Evening → Night** is **one-way**.  
- Once **Night** starts on a given date, **do not** re-enter Evening again until the **next day**.
- Implementation marker (conceptual): `night_started_on = YYYY-MM-DD` (today’s date when Night first starts).

### When Evening starts (edge-based, not constant polling)
- Evening **starts** only on the **edge** of entering the window (`sunset − 15m`) and if not Away.  
- Track: `evening_started_on = YYYY-MM-DD`.  
- Evening **does not** start again if `night_started_on == today` (Night already happened today).

### Night triggers (and when the failsafe is allowed)
1) **Bedroom Apple TV turns ON** (any time before 23:00) → **Set Night immediately**.  
   - Set `night_started_on = today`.
2) **Failsafe at 23:00** (local time) → **only fire if**:  
   - Current mode is **Evening**, and  
   - `night_started_on != today`, and  
   - **Not Away**.  
   → Then **Set Night**.  
   → If these conditions aren’t met, **do nothing** (failsafe is skipped because Night already started earlier).

> Result: The failsafe is used *only* when the Bedroom Apple TV didn’t turn on earlier and you’re still in Evening at 23:00.

### Bounce elimination (why this can’t ping-pong)
- After Night starts (either trigger), you have `night_started_on = today` → the controller refuses to re-enter Evening again **that date**.  
- Turning the Bedroom Apple TV **off** at 21:45 does **not** bring back Evening; you stay in Night until the next mode change (e.g., morning/away).

### Startup / reload behavior (restart-safe)
- If restart occurs **inside the Evening window** and `night_started_on != today` → set/keep **Evening**.  
- If restart occurs **at/after 23:00** and not Away:  
  - If `night_started_on != today` → **Set Night** (failsafe substitution).  
  - If `night_started_on == today` → **keep Night** (already done earlier).

### Return-home / Away rules
- If **Away** at 23:00, **do not** set Night (failsafe skipped).  
- On return home **after 23:00**, set **Night** (already after failsafe time).

### Manual overrides
- Manual changes after 23:00 are **ignored** unless a force service is explicitly called. Night is sticky.

### Acceptance checks (no-bounce version)
1) **21:30 Bedroom TV ON** → Night starts; at 21:45 TV OFF → **stays Night** (no Evening bounce).  
2) **No TV all evening** → 23:00 → Night starts (failsafe fired).  
3) **Night started at 20:55 (TV), then restart at 22:10** → Comes back as **Night** (because `night_started_on == today`).  
4) **Restart at 22:10 (no TV so far)** → Comes back as **Evening**; at 23:00, Night starts (failsafe).  
5) **Away at 23:00** → Failsafe skipped; remains **Away**.
