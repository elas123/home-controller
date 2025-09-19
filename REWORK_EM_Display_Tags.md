# REWORK — Early Morning **Display Tags** (EM — Work / EM — Day‑Off) — Design

*Design doc for adding **display‑only** tags that clarify Early Morning classification without adding new modes.*  
*Scope: One global controller mode (**Early Morning**), plus UX tags for dashboards/room policies. Version: 1.0*

---

## 1) Purpose

Keep the controller simple (one **Early Morning** mode), but make the UI and room logic crystal‑clear via **display‑only tags** that show whether EM is **Work** or **Day‑Off** — without changing modes or adding duplicate logic.

---

## 2) What the tags are

### 2.1 `sensor.home_state_detail` (primary display tag)
- **Values**
  - `"EM — Work"` when `pyscript.home_state == "Early Morning"` **and** EM route = work
  - `"EM — Day‑Off"` when `pyscript.home_state == "Early Morning"` **and** EM route = day_off
  - Otherwise mirrors the base mode: `"Day" | "Evening" | "Night" | "Away"`
- **Purpose**: Single, human‑readable field for dashboards/logs, so EM variants are obvious at a glance.

### 2.2 Simple flags for automations/UI
- `binary_sensor.em_is_work` → **on** iff EM route = work; otherwise **off**
- `binary_sensor.em_is_day_off` → **on** iff EM route = day_off; otherwise **off**
- `binary_sensor.em_active` → **on** iff `pyscript.home_state == "Early Morning"`; otherwise **off**
- **Purpose**: Dead‑simple conditions for room packages or Lovelace conditions.

### 2.3 “Until” and preview (optional, display‑only)
- `sensor.em_until`
  - **Work lane**: `"05:40:00"` (local time)
  - **Day‑Off lane**: **ISO** or local time equal to **Day commit**
- `sensor.em_targets_preview`
  - `"10%/2000K → 50%/4000K @ 05:40"` (work)
  - `"10%/2000K → <dynamic>%/5000K @ <commit>"` (day‑off)
- **Purpose**: Nice UX hints on chips/cards; not used for control.

### 2.4 Contract (optional, for debugging)
- `sensor.em_contract` (JSON string/attributes): `{"route":"work|day_off","start":"<iso>","end":"05:40"|"day_commit:<iso>"}`

---

## 3) Inputs these tags derive from (no new modes)
- `pyscript.home_state` (authoritative global mode)
- **EM classification facts (helpers)**
  - `input_text.em_route_key` → `"work" | "day_off"`
  - `input_datetime.em_start_ts` → ISO local timestamp
  - `input_boolean.em_active` → `on/off`
  - *(optional)* `input_text.em_until` → `"05:40:00"` or commit time
- **Day commit input (derived elsewhere)**
  - `sensor.day_commit_time` — the commit timestamp used for EM Day‑Off handoff
- *(FYI)* EM ramp targets (`sensor.sleep_in_ramp_brightness`, `sensor.sleep_in_ramp_kelvin`) remain publish‑only and unchanged.

> These tags are **pure derivations**. They do not change controller behavior or drive lights.
 
---

## 4) State mapping logic (deterministic)

| Base `pyscript.home_state` | `em_route_key` | `home_state_detail` | `em_active` | `em_is_work` | `em_is_day_off` | `em_until` |
|---|---|---:|:---:|:---:|:---:|---|
| Early Morning | work | **EM — Work** | on | on | off | `05:40:00` |
| Early Morning | day_off | **EM — Day‑Off** | on | off | on | `<day_commit_time>` |
| Day | any/blank | **Day** | off | off | off | blank |
| Evening | any/blank | **Evening** | off | off | off | blank |
| Night | any/blank | **Night** | off | off | off | blank |
| Away | any/blank | **Away** | off | off | off | blank |

Edge rules:
- If `em_route_key` is blank while `home_state == Early Morning`, set `home_state_detail = "Early Morning"` and all EM flags **off** (visible anomaly; should not happen once classification is set).

---

## 5) Where to use the tags

**Dashboards**
- Show `home_state_detail` as the main status chip.
- Conditionally show `em_until` under the chip while `em_active` is **on**.
- Optional “targets preview” as a subtitle for flair.

**Room packages**
- If you need per‑lane tweaks, branch on `em_is_work` / `em_is_day_off`.
- Otherwise, rooms just follow the published **EM ramp target sensors** as today.

**Logs/History**
- Filter by `home_state_detail` for crystal‑clear traces without joining on the EM profile.

---

## 6) Startup / Restart expectations (display‑only tags)

- On rehydrate, once EM helpers are read, the tags derive instantly:
  - Work path ⇒ `home_state_detail = "EM — Work"`, `em_active = on`, `em_until = 05:40:00`.
  - Day‑Off path ⇒ `home_state_detail = "EM — Day-Off"`, `em_active = on`, `em_until = <commit>`.
- After EM ends, tags revert to the base mode and flags turn **off**.

---

## 7) Minimal helper prerequisites (already in Super‑Helper Package)

- `input_text.em_route_key`
- `input_datetime.em_start_ts`
- `input_boolean.em_active`
- *(optional)* `input_text.em_until`

These already survive reload/restart and allow the tags to be derived deterministically.

---

## 8) Testing checklist (must pass)

- 04:59 motion ⇒ tags show **EM — Work**, `em_active=on`, `em_until=05:40`.  
- 05:05 motion ⇒ tags show **EM — Day‑Off**, `em_until=<commit time>`.  
- Reboot mid‑EM ⇒ tags show correct variant immediately after restore.  
- After EM handoff (work: presence→Away post‑05:40; day‑off: at commit) ⇒ tags clear and detail mirrors base mode.  
- Non‑EM modes ⇒ tags always mirror `"Day|Evening|Night|Away"` with EM flags **off**.

---

## 9) Naming conventions

- Use exact IDs above to keep dashboards and room packages portable.  
- Title format: `EM — Work` / `EM — Day‑Off` (en‑dash, consistent casing).

---

## 10) Notes & non‑goals

- This doc defines **UX tags only**. It does **not** change the controller’s mode machine or room logic.  
- If you later decide to split modes, these tags can remain for continuity (they’ll just mirror the split).

---

*End of document — v1.0*
