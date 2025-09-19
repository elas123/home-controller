# REWORK — Home Controller **Super‑Helper Package** (Design & Mirror Plan)

*Authoritative design document for durable state helpers, MQTT mirror, and reconciliation logic.*  
*Scope: Home Controller only (no room logic, no code). Version: 1.0*

---

## 1) Goals

- **Restart‑safe:** Controller picks up **exactly** where it left off after any reload/restart.
- **Deterministic:** Behavior is a pure function of **now + durable facts** (“contract”).
- **Spec‑clean:** Room behavior stays out of the controller; only **Night cutover** touches lights.
- **Visible & auditable:** All durable facts live in HA Helpers and are mirrored to MQTT (retained) with health signals to detect drift.

---

## 2) Canonical Truths (excerpt from REWORK)

- **Early Morning** starts **only** from **kitchen motion**.  
  04:50–04:59 ⇒ **Workday**; ≥ 05:00 ⇒ **Day‑Off**.  
  Work ramp: **10%/2000K → 50%/4000K** ends **05:40**; hold until **presence→Away**.  
  Day‑Off ramp: **10%/2000K → dynamic%/5000K**, finishes **exactly at Day commit**; flips to **Day** with **no jump**.
- **Day gate:** `now ≥ max(sunrise+30m, 07:30 floor)` **AND** `sun elevation ≥ monthly target` **AND** `not in Evening window` (3° hysteresis).
- **Evening window:** `sunset − 15m → cutoff (23:00 default)`, PM guard; startup inside window ⇒ **Evening**.
- **Night:** Bedroom TV (debounced) ⇒ **Night**; **23:00 failsafe** (Evening, not Away, and not started today) ⇒ **Night**; monotonic via `night_started_on` date marker. **Cutover** on entry turns off **all lights** (room packages may add exceptions).

---

## 3) Durable Helper Entities (Authoritative Store)

> Keep all helpers in one HA package (the “Super‑Helper Package”) so they load together. These are the **only** values that must survive restarts. Everything else is derived.

### 3.1 Early Morning (EM) Contract

| Entity ID | Domain / Type | Allowed Values | Default | Purpose |
|---|---|---|---|---|
| `input_text.em_route_key` | input_text | `"work"` \| `"day_off"` \| `""` | `""` | Which lane was chosen by first kitchen motion. |
| `input_datetime.em_start_ts` | input_datetime (date+time) | ISO local timestamp | blank | When EM started (first kitchen motion). |
| `input_boolean.em_active` | input_boolean | `on/off` | `off` | Convenience flag for dashboards & rehydrate checks. |
| `input_text.em_until` *(optional)* | input_text | `"05:40:00"` or ISO commit time | `""` | Display‑only: when EM ends. |

**Notes:**  
- Route is set **once per day** on first kitchen motion; later motions are ignored that date.  
- Targets published as sensors are **derived** from `(now, em_start_ts, em_until, route_key)` — no persistence needed.

### 3.2 Night Monotonic + LR‑TV Exception

| Entity ID | Domain / Type | Allowed Values | Default | Purpose |
|---|---|---|---|---|
| `input_text.night_started_on` | input_text | `YYYY‑MM‑DD` \| `""` | `""` | Monotonic guard: once set to today, no Evening that date. |
| `input_boolean.night_cutover_pending` | input_boolean | `on/off` | `off` | LR‑TV exception: Night without cutover; run when Bedroom TV turns on. |

### 3.3 Evening Cutoff & Day Inputs

| Entity ID | Domain / Type | Allowed Values | Default | Purpose |
|---|---|---|---|---|
| `input_datetime.evening_time_cutoff` | input_datetime (time) | `HH:MM:SS` | `23:00:00` | Overrides Evening window end if set. |
| `input_datetime.day_earliest_time` | input_datetime (time) | `HH:MM:SS` | `07:30:00` | Floor for Day gate (user‑overridable). |
| `input_number.day_elev_target_override` | input_number | integer degrees or blank | blank | Optional override for monthly elevation target. |

> **Sunrise/Sunset** should be published separately as persistent helpers (e.g., `input_datetime.sunrise_today`, `input_datetime.sunset_today`) by a tiny “sun‑times” publisher, or rely on your existing reliable source.

---

## 4) Display‑Only Tags (nice UX; no logic required)

- `sensor.home_state_detail`: `"EM — Work"`, `"EM — Day‑Off"`, or mirrors base mode `"Day|Evening|Night|Away"`.
- `binary_sensor.em_is_work` / `binary_sensor.em_is_day_off`: on/off for dead‑simple conditions.
- `binary_sensor.em_active` (mirrors helper): on during EM.
- `sensor.em_until`: mirrors helper for dashboards.

*(These can be sensors derived from the helpers. No persistence required beyond Helpers themselves.)*

---

## 5) MQTT Mirror (Safety Copy)

Mirror the same contract to **retained** MQTT topics (QoS 1). The controller is the **single writer**. Room packages do **not** write.

### Topics & Payloads

- **Early Morning contract** — `home/rework/controller/em/contract`  
  ```json
  {"route_key":"work|day_off","start_ts":"<ISO>","end_kind":"fixed|commit","active":true,"until":"<clock or ISO>","updated_at":"<ISO>","version":1}
  ```

- **Night state** — `home/rework/controller/night/state`  
  ```json
  {"night_started_on":"YYYY-MM-DD","cutover_pending":false,"updated_at":"<ISO>","version":1}
  ```

- **Evening cutoff** — `home/rework/controller/evening/cutoff`  
  ```json
  {"evening_cutoff":"HH:MM:SS","updated_at":"<ISO>","source":"helper","version":1}
  ```

- **Day floor** — `home/rework/controller/day/floor`  
  ```json
  {"day_earliest_time_floor":"HH:MM:SS","updated_at":"<ISO>","version":1}
  ```

- **(Optional) Day elevation override** — `home/rework/controller/day/elev_override`  
  ```json
  {"target_deg":10,"updated_at":"<ISO>","version":1}
  ```

**Broker notes:** All topics **retained**, **QoS 1**. Include `updated_at` and `version` in every payload.

---

## 6) Reconciliation Policy (Helpers ↔ MQTT)

**Priority of truth:**  
1) **Helpers** (authoritative & UI‑visible)  
2) **MQTT retained** (fallback only if a helper value is missing/blank/invalid)  
3) **Safe defaults** (e.g., `07:30` floor, `23:00` cutoff, no elevation override)

### On startup/reload (rehydrate)

1. Read Helpers. If all required values present & valid ⇒ **use Helpers** and mark data source = `"helpers"`.
2. If any required value is missing/blank ⇒ read the corresponding **MQTT** topic:
   - If MQTT has it ⇒ **restore Helpers** from MQTT and mark data source = `"mqtt_fallback"`.
   - If MQTT also missing ⇒ use safe defaults and mark **contract incomplete** (send a persistent notification).
3. After rehydrate, **republish** the authoritative contract to MQTT (idempotent).

### Periodic guard (every 5–10 min)

- Compute a short **CRC/hash** of the Helper contract and compare with the last retained MQTT payload(s).
- If mismatch:
  - If **Helpers are newer** (`updated_at` Helpers > MQTT by ≥ 30s) ⇒ overwrite MQTT; log `"helpers_newer"`.
  - If **MQTT is newer** (by ≥ 5 min) **and** contract incomplete ⇒ repair Helpers from MQTT; log `"mqtt_newer"`.
  - Otherwise flag **mismatch** for manual attention with a reason like `"field_mismatch: em_start_ts"`.

**Clock skew:** Prefer relative recency windows; if system time is suspect, prefer Helpers and alert.

---

## 7) Boot / Rehydrate Flow (Deterministic)

1) **Presence guard:** If any phone is away ⇒ set **Away** and stop (controller never overrides Away).  
2) **Load sun inputs** and compute: `evening_start_local`, `in_evening_window`, Day gate readiness, `day_commit_time`, `day_target_brightness`.  
3) **Rehydrate EM:** If `em_active == on` (or route key set and before end condition), set **Early Morning** and publish ramp targets from `(now, em_start_ts, em_until, route)`.  
4) Else choose **Night / Evening / Day**:  
   - If time ≥ cutoff: if `night_started_on != today` and not Away ⇒ **Night** (LR‑TV may defer cutover); else keep **Night**.  
   - Else if `in_evening_window == on` and `night_started_on != today` ⇒ **Evening**.  
   - Else if `day_ready_now == on` ⇒ **Day**.  
   - Else keep prior (default to **Day** if unknown).  
5) **TV edges:** If Bedroom TV is currently ON and `night_started_on != today` ⇒ **Night** immediately (debounce applies for live changes).

---

## 8) Health & Observability (Display‑only)

- `sensor.controller_data_source` → `"helpers" | "mqtt_fallback" | "mixed"`  
- `sensor.controller_rehydrate_reason` → `"cold_boot" | "reload" | "inputs_changed"`  
- `binary_sensor.controller_contract_complete` → on/off  
- `sensor.contract_crc` → short hash of `{em_contract, night_state, cutoff, floor}`  
- `binary_sensor.helper_mqtt_mismatch` → on/off  
- `sensor.helper_mqtt_drift_reason` → `"helpers_newer" | "mqtt_newer" | "field_mismatch:<name>"`

---

## 9) Test Checklist (must pass)

- **04:59 motion** ⇒ EM—Work; reboot at 05:10 ⇒ still EM—Work; at 05:41, still EM until presence→Away; Away ends EM.  
- **05:05 motion** ⇒ EM—Day‑Off; flips to Day **exactly at commit** with no jump.  
- **No motion before 10:00** ⇒ never enters EM.  
- **Startup inside evening window** ⇒ Evening (not Away).  
- **Bedroom TV 21:30** ⇒ Night; reboot at 22:10 ⇒ stays Night.  
- **23:00 failsafe** fires only if Evening, not Away, and not started today.  
- **Sunrise missing on boot** ⇒ Day gate waits on 07:30 floor until sunrise appears; no premature Day.  
- **MQTT up, Helpers wiped** ⇒ controller restores from MQTT and continues seamlessly.

---

## 10) Maintenance

- **Backups:** HA snapshot includes Helpers; broker retains mirrors independently.  
- **Security:** Use dedicated MQTT credentials with TLS if available.  
- **Single writer:** Only the **controller** writes Helpers and contract topics.  
- **Visibility:** Surface the health sensors on a small Lovelace card.

---

## 11) Naming Conventions

- Keep all contract helpers prefixed with a clear namespace, e.g., `em_*`, `night_*`.  
- MQTT topics under a single root: `home/rework/controller/...`  
- Include `version` and `updated_at` fields in every MQTT payload.

---

*End of document — v1.0*
