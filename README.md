# RCADS cockpit 0.1.0

Gun-radio control software for a four-field protocol on CRSF. It does not implement EdgeTX or ELRS, and it does not drive the car.

Wire text: `MODE,READY,RISK,TAKEOVER`  
Example: `L3,1,23,5`

## Tests (this machine)

```
py -3 sim/test_rcads.py
py -3 sim/rcads_sim.py --once
```

28 protocol/control tests passed. There is no RadioMaster MT12 on this machine, so the Lua script has not been run on hardware.

## Install on an EdgeTX gun radio (MT12)

1. Unzip `rcads-edgetx-0.1.0.zip` onto the radio SD card, keeping `SCRIPTS/TELEMETRY/rcads.lua`.
2. Model → Display → Script → `rcads`.
3. Wheel = CH1, trigger = CH2, SA = mode request.
4. ENTER walks the onboard demo if no vehicle is sending FM.

## Publish

EdgeTX Lua is released as a GitHub repo + Release zip. It is not an app-store app. After `gh auth login`:

```
gh repo create rc-ads-cockpit --public --source . --remote origin --push
gh release create v0.1.0 dist/rcads-edgetx-0.1.0.zip dist/rcads-cockpit-0.1.0-src.zip --title "v0.1.0" --notes "First cockpit + four-field CRSF protocol."
```
