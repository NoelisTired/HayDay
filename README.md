# HayDay Bot

HayDay Bot is a Windows-based Hay Day automation experiment built around MEmu, ADB input injection, and OpenCV field detection.

The bot currently does one thing: it plants. It detects the soil area on screen, estimates where the wheat tool should be, generates a drag path, and performs one continuous sowing gesture through ADB.

It does not harvest yet. It is also still unstable.

This repo is best understood as a working prototype for computer vision and emulator control, not as a polished end-user tool.

## Current Status

- Planting works in some setups
- Harvesting is not implemented
- Detection is sensitive to soil appearance and screen state
- Coordinate tuning is manual
- Stability is still rough
- PRs are open

If you are expecting a one-click bot, this is not there yet.

## Why This Exists

The main goal of this project was to get reliable farm plot detection and use that detection to drive in-game input without relying on the Windows mouse. That means:

- screenshots come from the emulator through ADB
- taps and drags are injected through ADB
- OpenCV is used to isolate the field area
- a debug viewer shows what the bot thinks it sees before it commits to the drag

That separation matters because it makes the interaction model more deterministic than desktop mouse automation.

## What The Bot Does Right Now

The current `memu_bot.py` flow is:

1. Connect to MEmu through ADB
2. Capture a screenshot
3. Detect the farm soil region
4. Tap the field center to trigger the game's camera adjustment
5. Capture another screenshot
6. Detect the field again after the auto-scroll
7. Compute the wheat icon position from a fixed offset relative to the detected field center
8. Build a zigzag drag path that covers the field
9. Show the path in the viewer
10. Execute one long-press drag gesture over that path
11. Save screenshots for debugging

## Main Features

- Pure ADB control for taps and drags
- OpenCV-based soil detection
- Multi-template color matching for different soil states
- Morphological closing to merge furrow lines into one usable region
- Bounding box recovery with `minAreaRect`
- Live debug overlay through the local viewer
- Screenshot capture at key stages for troubleshooting
- Adjustable offsets and spacing from one config block

## What It Does Not Do

- Harvest crops
- Replant in a loop safely
- Detect inventory state reliably
- Handle every farm layout or zoom level
- Automatically recalibrate offsets
- Automatically recover from all bad detections
- Handle shop logic or broader gameplay flows

## Repository Layout

- `memu_bot.py`  
  Main entry point. Runs the bot flow, captures screenshots, logs steps, computes offsets, and executes the sowing drag.

- `soil_detector.py`  
  OpenCV-based detector that isolates the field from soil color and returns center and bounds data.

- `memu/adb.py`  
  ADB client wrapper.

- `memu/controller.py`  
  High-level emulator controller. Handles screenshots, taps, drags, and path generation.

- `memu/touch_injector.py`  
  Low-level touch event injection.

- `memu/viewer.py`  
  Debug window and overlay rendering.

- `memu/debug_dragger.py`  
  Utilities for visualizing or inspecting drag coordinates.

- `templates/`  
  Soil sample images used for color matching.

## How Detection Works

The field detector is intentionally simple, but layered enough to survive some ugly in-game visuals.

### 1. Template Sampling

Two soil template images are loaded from `templates/soil1.JPG` and `templates/soil2.JPG`.

For each template, the detector computes the average color. That gives a rough color signature for the kinds of soil the bot expects to see.

### 2. Color Difference Masks

For the current screenshot, the detector measures per-pixel difference from each sampled soil color.

Pixels that fall within the threshold are treated as soil-like:

- one mask is generated for `soil1`
- one mask is generated for `soil2`

### 3. Mask Combination

The two masks are merged with:

```python
cv2.bitwise_or(mask1, mask2)
```

This matters because the ground can shift visually depending on events, stains, or other seasonal changes.

### 4. Morphological Closing

The combined mask is passed through:

```python
cv2.morphologyEx(current_mask, cv2.MORPH_CLOSE, kernel)
```

This helps bridge the horizontal furrow lines into a more solid area so contour detection sees one useful region instead of fragmented stripes.

### 5. Contour Filtering

Contours are found, then small contours are discarded using a minimum contour area threshold. This removes a lot of garbage detections like stray patches and irrelevant blobs.

### 6. Largest Valid Contour

The largest remaining contour is assumed to be the field.

### 7. Stable Bounds

Two related shapes are extracted:

- `cv2.minAreaRect(largest)` gives a rotated rectangle and center
- `cv2.boundingRect(largest)` is used for practical path coverage bounds

The rotated rectangle is useful because it still produces a clean enclosing box even when corners are partly broken or visually noisy.

### 8. Contour Approximation

For contour simplification and visualization, the detector also uses:

```python
approx = cv2.approxPolyDP(largest, epsilon, True)
```

That line was a key tip from Hadean-Eon-Dev and helped clean up the shape logic.

## Detection Notes

The detector in this repo is not a general Hay Day vision system. It is a practical detector tuned around one problem: finding a big region of plantable soil reliably enough to drive a drag path.

It can still fail when:

- the soil colors no longer resemble the templates
- UI elements obscure too much of the plot
- the camera is in an unusual position
- seasonal visuals or event art introduce misleading colors
- road textures or unrelated brown regions look close enough to soil

## How Pathing Works

The path generator lives in `memu/controller.py`.

At a high level, it does this:

1. Starts from the configured wheat icon position
2. Leads the drag into the detected field
3. Makes a small circle around the center
4. Moves toward the top-left region
5. Sweeps the field in horizontal rows
6. Uses rounded U-turns at the edges so the drag remains continuous

This is not just cosmetic. The rounded U-turns reduce wasted motion and avoid abrupt corners that can behave poorly in touch-driven interactions.

The main path controls are:

- `RING_SPACING`
- `STEP_DELAY`
- `HOLD_DURATION`

## How Input Works

All game interaction in the current implementation goes through ADB.

That means:

- screenshots are captured from the emulator
- taps are sent as Android-level input
- drags are executed as one unbroken touch gesture

This avoids depending on the Windows cursor and keeps the bot logic tied to emulator coordinates instead of desktop window placement.

## Requirements

This project is currently written around a Windows + MEmu setup.

### Required

- Windows
- Python 3
- MEmu
- Hay Day running inside MEmu
- `adb.exe` accessible at the configured path
- OpenCV and NumPy

### Python Packages

Install at minimum:

```bash
pip install opencv-python numpy
```

Optional but useful for coordinate inspection:

```bash
pip install mouseinfo
```

## Setup

### 1. Clone The Repository

```bash
git clone <your-repo-url>
cd HayDay
```

### 2. Install Python Dependencies

```bash
pip install opencv-python numpy
```

Optional:

```bash
pip install mouseinfo
```

### 3. Check Soil Templates

Make sure `templates/soil1.JPG` and `templates/soil2.JPG` match the kind of soil your farm currently shows in-game.

If they do not, detection quality will drop immediately.

### 4. Configure ADB And Device Address

Open `memu_bot.py` and check:

- `ADB_PATH`
- `DEVICE_ADDRESS`

By default, this repo expects MEmu's ADB path and a local emulator address similar to `127.0.0.1:21503`.

### 5. Tune The Wheat Offset

The most important settings in `memu_bot.py` are:

- `WHEAT_OFFSET_X`
- `WHEAT_OFFSET_Y`

These offsets describe where the wheat icon is relative to the detected field center in Android logical pixels.

If these are wrong, the bot will drag from the wrong starting point even when field detection is correct.

### 6. Start From A Clean Screen

Before running:

- make sure the farm is visible
- avoid blocking UI where possible
- make sure the field is actually in frame
- keep the emulator state consistent between test runs

## Running The Bot

Once configured:

```bash
python memu_bot.py
```

The debug viewer should open and the bot will log each step as it progresses.

## Output And Debugging

The bot saves screenshots into `screenshots/` during important moments such as:

- initial field location
- post-scroll re-detection
- final result

These images are useful when:

- the detector misses the field
- the wrong region is selected
- the wheat offset is wrong
- the path covers the wrong area

## Configuration Reference

These values live near the top of `memu_bot.py`.

### `ADB_PATH`

Path to `adb.exe`.

### `DEVICE_ADDRESS`

The MEmu device endpoint, usually something like `127.0.0.1:21503`.

### `WHEAT_OFFSET_X` and `WHEAT_OFFSET_Y`

Offset from detected field center to the wheat icon.

This is the first thing to tune when the red crosshair in the debug view is not sitting on the wheat tool.

### `RING_SPACING`

Distance between path rows.

Smaller spacing means denser coverage but more points and more drag time.

### `STEP_DELAY`

Delay between points in the drag path.

Lower is faster. Too aggressive can make behavior less reliable depending on the emulator and input method.

### `HOLD_DURATION`

How long the finger is held on the starting point before the drag begins.

This helps simulate the long-press needed before the sowing drag.

### `VIEW_SCALE`

Scale factor for the debug viewer window.

## Tuning Tips

### If The Bot Detects The Road Instead Of The Field

- update the soil templates
- raise or lower the color threshold in `soil_detector.py`
- inspect saved screenshots
- check whether event textures introduced soil-like colors elsewhere

### If The Red Crosshair Is Not On The Wheat Tool

- adjust `WHEAT_OFFSET_X`
- adjust `WHEAT_OFFSET_Y`
- use repeated screenshots and small changes instead of large jumps

### If The Field Is Detected But Coverage Looks Wrong

- inspect `RING_SPACING`
- check the bounding box after re-detection
- verify the camera state after the center tap and auto-scroll

### If You Need Exact Coordinates

Hadean-Eon-Dev recommended this during debugging:

```python
import mouseinfo
mouseinfo.MouseInfoWindow()
```

That was useful for pinning down exact positions during setup and experimenting with offsets.

## Known Problems

- Planting only
- No harvesting flow
- No inventory management flow
- No robust retry logic
- No adaptive thresholding
- Template matching is brittle across visual changes
- One emulator profile can behave differently from another
- Some starting screens will still break the run

## Roadmap

Possible next steps for the project:

- add harvesting
- add crop state detection
- improve tool selection logic
- reduce dependency on manually tuned offsets
- add template refresh helpers
- handle more emulator resolutions cleanly
- improve error recovery and retries
- add setup instructions for additional emulator configurations

## Contributing

PRs are open.

If you want to contribute, useful areas would be:

- harvesting support
- detector stability
- better coordinate calibration
- safer path generation
- emulator compatibility improvements
- test images for different soil and event states
- cleaner configuration management

If you open a PR, include:

- what setup you tested on
- what behavior changed
- screenshots if the change affects detection or overlays

## Acknowledgements

Thanks to Hadean-Eon-Dev for the help that unlocked part of the detector work.

The key hint shared was:

```python
approx = cv2.approxPolyDP(largest, epsilon, True)
```

That helped with contour cleanup and field-shape handling.

Another useful pointer was using:

```python
import mouseinfo
mouseinfo.MouseInfoWindow()
```

to inspect coordinates during setup and debugging.

From there, the detector in this repo was pushed further with additional research and testing:

- combining masks for multiple soil states
- using `cv2.bitwise_or` to merge them
- applying `cv2.MORPH_CLOSE` to bridge furrow gaps
- using `cv2.minAreaRect` to recover a more stable field box when corners are imperfect

So the credit is split the right way:

- Hade supplied the useful contour and coordinate-debugging pointers
- the detector in this repo expanded on those ideas with extra processing and tuning work

## Disclaimer

This repository is shared for educational purposes, reverse-engineering practice, computer vision experimentation, and emulator control research.

Use it at your own risk.

If you choose to automate interactions in a game, you are responsible for understanding the relevant rules, terms, and consequences yourself.
