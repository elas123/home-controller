# REWORK Simulator — Setup & Usage Guide

This simulator gives you a repeatable way to exercise the Home Controller without touching real devices. It drives the same entity IDs the controller expects (motion, door, presence, TVs, helpers) and records every action in dedicated logs so you can validate outcomes quickly.

## 1. Files to deploy

Copy these into Home Assistant (keep them in one package folder so they load together):

| File | Target | Purpose |
| --- | --- | --- |
| `super_helper_package.yaml` | HA package | Durable helpers for EM/Night contract (per REWORK spec). |
| `em_display_tags.yaml` | HA package | Display-only EM tags (`sensor.home_state_detail`, etc.). |
| `mock_entities.yaml` | HA package | Simulator-only helpers/log sensors (motion flags, logs, time freeze, phone presence mirrors). |
| `simulation_package.yaml` | HA package | Input buttons + automations that call the simulator PyScript services. |
| `simulation_controls.py` | `/config/pyscript/` | Simulator services & watchdogs. |
| `sim_dashboard.yaml` | Lovelace manual card | Ready-made control panel. |

Reload PyScript and YAML packages after copying.

## 2. What the simulator covers

- Motion pulses for kitchen, bathroom, hallway sensors (real IDs + simulator mirrors).
- Presence toggles for both phones (`device_tracker.iphone15`, `device_tracker.work_iphone`).
- Bathroom door open/close (`binary_sensor.bathroom_contact_contact`).
- Bedroom & Living Room TV power state (drives Night transitions) with mirrored sensors for dashboards.
- Early Morning helpers: force work/day-off ramps, reset, time-freeze.
- Live logs and flags for home state, ramp state, and presence events.

Every simulator action writes to one of these logs:

- `sensor.home_state_log` — home-state transitions & time freeze actions.
- `sensor.ramp_log` — ramp enable/disable + EM active flag.
- `sensor.presence_log` — phone presence, door, TV edges.

## 3. Control panel quick start

1. Add a **Manual card** in Lovelace → paste `sim_dashboard.yaml`.
2. Set a fake time (optional): choose `Sim Time`, press **Apply Time**. Clear with **Clear Time**.
3. Trigger motion: press **Kitchen Motion** (duration uses the slider). This drives both kitchen motion sensors and the mock helper so history/debug cards light up.
4. Exercise bathroom logic: use **Door Open/Door Close**, pair with **Bathroom Motion** to validate hold behaviour.
5. Toggle phone presence with **Leaves/Arrives** and watch `sensor.sim_iphone_15_status` / `sensor.sim_work_iphone_status` update to `home`/`away` in the panel.
6. Use **Bedroom/Living TV On/Off** buttons and confirm `sensor.sim_bedroom_tv_state` / `sensor.sim_living_tv_state` change and the presence log records the edge.
7. Test Night entry: set phones to `home`, run **Bedroom TV On**. After the debounce you should see Night engage and the cutover logs update.
8. Run route checks: **Force Work Ramp** / **Force Day-Off Ramp**, then fire kitchen motion to confirm the controller selects the correct EM lane and updates `sensor.home_state_detail`.

## 4. Verification checklist

- **Kitchen work ramp**: Freeze time 04:55, press *Kitchen Motion*. Check ramp logs show workday route and `input_text.em_route_key = work`.
- **Day-off ramp**: Freeze time 05:05, press *Kitchen Motion*. Controller should set route `day_off` and `sensor.em_until` should match the day commit time.
- **Bathroom hold**: Start motion, press *Door Close*. Light should lock at 100%. Press *Door Open* to resume adaptive brightness.
- **Night via Bedroom TV**: With presence `home` and Evening mode active, tap *Bedroom TV On* — `pyscript.home_state` must flip to Night after 5s and `input_boolean.night_cutover_pending` clears.
- **Away guard**: Set both phones to **Leaves**, confirm controller switches to Away and ignores motion pulses.
- **Logs refresh**: Every button press should append to the appropriate log and flash the corresponding flag sensor (`binary_sensor.*_event_sim`).
- **Presence mirrors**: `sensor.sim_iphone_15_status` and `sensor.sim_work_iphone_status` should track the simulated phones; the binary presence sensors (`binary_sensor.sim_presence_*`) stay in sync for dashboard badges.
- **TV mirrors**: `sensor.sim_bedroom_tv_state` and `sensor.sim_living_tv_state` should reflect the buttons immediately, even if the real media_player entities are unavailable.

Repeat runs are deterministic — clear/reset helpers with **Reset Early Morning** or by toggling the relevant helper entities.

## 5. Tips

- Keep `input_boolean.als_dry_run` **on** while testing so real lights/services are not touched.
- For timeline reviews, pin `sensor.home_state_detail`, `sensor.em_until`, and the three log sensors to the same dashboard view.
- If you need to script batches, call the services directly (e.g. from Developer Tools → Services → `sim.trigger_motion` with `entity: ["binary_sensor.kitchen_motion_sim", ...]`).

With this setup you can replay any edge case from the REWORK spec without waiting for real-world conditions.
