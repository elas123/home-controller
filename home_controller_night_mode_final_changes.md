# Home Controller — Night Mode Final Changes (Markdown)

**File purpose:** This document captures the *final* Night Mode behavior and the exact code patches you asked for, so you can paste them into `home_controller.py` and keep a clear record of the logic.

---

## ✅ Final Behavior (authoritative overview)

### 23:00 Failsafe
- Preconditions: **not** Away, and Night hasn’t already started today.
- If **LR Apple TV is OFF-ish** → **Night immediately** with `run_cutover=True`.
- If **LR Apple TV is ON-ish** → **postpone Night**: force Evening, set **“waiting for bedroom TV”**; **do not** start the timer here.

> **OFF-ish / ON-ish**: OFF-ish = one of `off`, `unavailable`, `unknown`, `""`, `none`.

### After 23:00 while *waiting for bedroom TV*
- When **LR TV becomes OFF-ish**, **start a 30-minute timer**.
- If **BR TV turns ON** while **LR TV is OFF-ish** (any time before timeout) → **Night immediately** with `run_cutover=True` (the timer is cancelled inside `_enter_night`).
- If the **30 minutes expire** and we’re still waiting → **force Night** with `run_cutover=True`.
- If **LR TV turns back ON** during the countdown → **ignore it**; the 30‑minute timer **continues** (your requested change).

### “Living Room lights OFF after cutoff” path (unchanged from your latest handler)
- After cutoff (ideally **23:00**), if LR lights are manually turned **off**:
  - If still **waiting** *and* **LR TV is OFF-ish** → **clear waiting**, **Night** with `run_cutover=True`.
  - Otherwise → **Night** with `run_cutover=False` (respects the manual action).

### Before 23:00
- **BR TV ON** while **LR TV OFF-ish** → after 5s debounce, **Night** with `run_cutover=True`.
- **BR TV ON** while **LR TV ON** → **no Night** (logs that LR TV is still on).
- **LR TV alone** does **not** trigger Night before 23:00.

---

## 🧩 Code Patches (drop‑in)

> Paste these near the related sections in your file. They assume your existing structure and decorators.

### 1) Constants & helpers (globals section)
```python
# Night waiting timeout (start only after LR TV turns OFF post-23:00)
WAIT_FOR_BR_TV_TIMEOUT_MIN = 30
_waiting_timeout_task = None

def _offish(s: str) -> bool:
    s = (s or "").lower()
    return s in ("off", "unavailable", "unknown", "", "none")
```

### 2) Timeout helpers
```python
@catch_hc_error("_start_waiting_timeout")
def _start_waiting_timeout():
    """Start/replace the post-23:00 waiting timeout (30 min) for BR TV."""
    global _waiting_timeout_task
    _cancel_task_if_running(_waiting_timeout_task, "start_waiting_timeout")
    _waiting_timeout_task = task.create(_waiting_timeout_runner())

@catch_hc_error("_cancel_waiting_timeout")
def _cancel_waiting_timeout(reason: str = "cancel_waiting_timeout"):
    """Cancel the BR-TV waiting timeout, if any."""
    global _waiting_timeout_task
    _cancel_task_if_running(_waiting_timeout_task, reason)

@catch_hc_error("_waiting_timeout_runner")
async def _waiting_timeout_runner():
    """If BR TV never turns on after LR TV went off, force Night after 30 minutes."""
    try:
        await asyncio.sleep(WAIT_FOR_BR_TV_TIMEOUT_MIN * 60)
        if _is_waiting_for_bedroom_tv() and _get_home_state() not in ("Night", "Away"):
            log.info("[HC] Waiting timeout expired; BR TV did not turn on. Forcing Night.")
            _clear_waiting_for_bedroom_tv("waiting_timeout_expired")
            _enter_night(run_cutover=True, reason="waiting_timeout")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"[HC] waiting_timeout_runner error: {e}")
```

### 3) 23:00 failsafe — **no timer start here**
```python
@catch_hc_error("_failsafe_23_handler")
def _failsafe_23_handler():
    """23:00 failsafe for Night mode."""
    if _get_home_state() == "Away":
        return
    if _night_started_on() == _today_str():
        return

    lr_st = str(_get(LIVINGROOM_TV) or "").lower()

    if not _offish(lr_st):
        # Postpone Night; enter WAITING (no timer yet).
        _postpone_night_until_bedroom_tv("failsafe_23_lr_tv_on")
        return

    _enter_night(run_cutover=True, reason="failsafe_23")
```

### 4) LR TV change trigger — **start timer only when LR goes OFF-ish** (and never cancel)
```python
@state_trigger(f"{LIVINGROOM_TV}")
@catch_hc_trigger_error("livingroom_tv_change")
def _livingroom_tv_changed(value=None, old_value=None, **kwargs):
    """After 23:00 while WAITING:
       - If LR TV becomes OFF-ish -> start 30-minute timer
       - Ignore LR TV turning back ON (timer keeps running)"""
    if not _is_waiting_for_bedroom_tv():
        return
    if _now().time() < dt_time(23, 0):
        return
    if _get_home_state() in ("Night", "Away"):
        return

    async def _maybe_start():
        try:
            await asyncio.sleep(2)  # small debounce
            curr = str(_get(LIVINGROOM_TV) or "").lower()
            if _is_waiting_for_bedroom_tv() and _get_home_state() not in ("Night", "Away") and _offish(curr):
                log.info("[HC] LR TV is OFF after 23:00 while waiting → starting 30-min BR-TV timer.")
                _start_waiting_timeout()
            # NOTE: If LR TV turns back ON, we do nothing; timer continues.
        except Exception as e:
            log.warning(f"[HC] livingroom_tv_changed apply error: {e}")

    task.create(_maybe_start())
```

### 5) Bedroom TV debounced — **immediate Night** when LR is OFF-ish
```python
async def _bedroom_tv_debounced():
    """Debounced Bedroom TV to Night transition"""
    try:
        await asyncio.sleep(BEDROOM_TV_DEBOUNCE_SECONDS)
        br_state = str(_get(BEDROOM_TV) or "").lower()
        if not _offish(br_state):  # BR TV ON-ish
            lr_state = str(_get(LIVINGROOM_TV) or "").lower()
            if _offish(lr_state):
                _enter_night(run_cutover=True, reason=f"bedroom_tv_triggered_night:{br_state}")
            else:
                _set_last_action("bedroom_tv_on_but_living_room_still_on")
    except Exception as e:
        log.warning(f"[HC] debounce error: {e}")
```

### 6) Cancel timer when Night starts or waiting is cleared
```python
@catch_hc_error("_enter_night")
def _enter_night(run_cutover: bool, reason: str):
    _cancel_waiting_timeout("enter_night")  # cancel countdown
    # ... existing body remains ...
```

```python
@catch_hc_error("_clear_waiting_for_bedroom_tv")
def _clear_waiting_for_bedroom_tv(source: Optional[str] = None):
    if not _is_waiting_for_bedroom_tv():
        return
    _cancel_waiting_timeout("clear_waiting_flag")  # cancel countdown
    # ... existing body remains ...
```

> Your **LR lights OFF after cutoff** handler from earlier is compatible with this flow and needs no change. If desired, you can add a 2s debounce similar to the others.

---

## 🧪 Test Matrix (quick scenarios)

| Time  | LR TV | BR TV | Action/Event                         | Expected Result                         |
|------:|:-----:|:-----:|--------------------------------------|-----------------------------------------|
| 22:45 | OFF   | ON    | BR turns ON                          | Night (cutover=True) after 5s           |
| 23:00 | ON    | any   | Failsafe runs                        | Evening + WAITING (no timer)            |
| 23:05 | OFF   | OFF   | LR turns OFF                         | Start 30-min timer                      |
| 23:10 | OFF   | ON    | BR turns ON                          | Night immediately; timer canceled       |
| 23:36 | OFF   | OFF   | Timer expires                        | Night (cutover=True)                    |
| 23:20 | ON    | OFF   | LR turns back ON during countdown    | **Ignored**; timer continues            |
| 23:40 | OFF   | OFF   | LR lights manually OFF after cutoff  | Night (per your handler’s branch)       |

---

## Notes / Recommendations
- Ensure your **cutoff** used by “LR lights OFF after cutoff” is **23:00** (per spec). If your `_refresh_daily_constants()` still sets cutoff from sunset, consider restoring a fixed `EVENING_DEFAULT_CUTOFF=dt_time(23,0)` and only deriving `evening_start` from sunset.
- Keep the small **2s debounce** to avoid flapping states from media players and helpers.

---

**End of file.**
