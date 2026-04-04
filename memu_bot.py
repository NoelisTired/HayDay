"""
memu_bot.py — HayDay wheat-seeding bot.

Architecture:
  Bot thread  — all ADB work (screenshots, tap, drag)
  Main thread — cv2 window loop, never blocks, always responsive
"""

import os
import sys
import threading
import time

sys.path.insert(0, ".")

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

_shot_counter = 0

def save_screenshot(screen, label: str):
    global _shot_counter
    _shot_counter += 1
    fname = f"{_shot_counter:02d}_{label}.png"
    path = os.path.join(SCREENSHOTS_DIR, fname)
    import cv2 as _cv2
    _cv2.imwrite(path, screen)
    return fname

import cv2
from memu import MemuController, BotViewer, DebugDragger
from soil_detector import SoilDetector

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

ADB_PATH       = r"C:\Program Files\Microvirt\MEmu\adb.exe"
DEVICE_ADDRESS = "127.0.0.1:21503"

# Wheat tool offset from detected farm centre (Android logical pixels).
# Tune these until the red crosshair in Bot View lands on the wheat icon.
WHEAT_OFFSET_X = -120   # negative = left
WHEAT_OFFSET_Y = -100   # negative = up

RING_SPACING   = 40     # px between raster lines
STEP_DELAY     = 0      # 0 = no sleep; sendevent overhead (~6ms) paces it naturally
HOLD_DURATION  = 0.8    # seconds to hold at wheat before dragging

VIEW_SCALE     = 0.6    # Bot View window scale


# ─────────────────────────────────────────────────────────────────────────────
# Bot (runs in background thread)
# ─────────────────────────────────────────────────────────────────────────────

def bot_main(view: BotViewer):
    detector = SoilDetector()
    ctrl = MemuController(
        adb_path=ADB_PATH,
        device_address=DEVICE_ADDRESS,
        step_delay=STEP_DELAY,
        log=view.log,
    )
    dbg = DebugDragger(ctrl, overlay=None)
    dbg._log = view.log

    def shot(status="", save_label=None):
        view.update(status=status)
        view.log(f"  [screenshot] capturing screen...")
        screen = ctrl.screenshot()
        view.log(f"  [screenshot] resolution: {screen.shape[1]}x{screen.shape[0]}px")
        if save_label:
            fname = save_screenshot(screen, save_label)
            view.log(f"  [screenshot] saved → screenshots/{fname}")
        view.log(f"  [detect] running soil detector...")
        center = detector.getSoilCenter(screen)
        bounds = detector.getSoilBounds(screen) if center else None
        if center:
            view.log(f"  [detect] soil centre: {center}")
        else:
            view.log(f"  [detect] no soil detected")
        view.update(screen=screen, soil_bounds=bounds, status=status)
        return screen, center, bounds

    try:
        # ── Step 1: Connect ───────────────────────────────────────────────────
        view.log("━" * 50)
        view.log("STEP 1 — Connect to device")
        view.log("━" * 50)
        view.log(f"  ADB path    : {ADB_PATH}")
        view.log(f"  Device      : {DEVICE_ADDRESS}")
        view.update(status="Connecting...")
        ctrl.connect()
        view.log("  ✓ Connected successfully")

        # ── Step 2: Locate farm ───────────────────────────────────────────────
        view.log("")
        view.log("━" * 50)
        view.log("STEP 2 — Locate farm")
        view.log("━" * 50)
        view.log("  Taking initial screenshot and running soil detection...")
        _, center, _ = shot("Locating farm...", save_label="locate_farm")
        if center is None:
            view.log("  ✗ Farm not detected")
            view.log("    → Check that soil templates match your farm soil colour")
            view.log("    → Ensure the farm is visible and not obstructed by UI")
            view.update(status="ERROR: farm not detected")
            return
        view.log(f"  ✓ Farm centre detected at {center}")

        # ── Step 3: Click centre → trigger auto-scroll ────────────────────────
        view.log("")
        view.log("━" * 50)
        view.log("STEP 3 — Tap farm centre to trigger auto-scroll")
        view.log("━" * 50)
        view.log(f"  Tapping ({center[0]}, {center[1]})...")
        ctrl.tap(center[0], center[1])
        view.log("  ✓ Tap sent")
        for i in range(3, 0, -1):
            view.log(f"  Waiting for auto-scroll... {i}s remaining")
            view.update(status=f"Auto-scrolling... {i}s")
            time.sleep(1)
        view.log("  ✓ Auto-scroll wait complete")

        # ── Step 4: Re-detect after scroll ───────────────────────────────────
        view.log("")
        view.log("━" * 50)
        view.log("STEP 4 — Re-detect field after scroll")
        view.log("━" * 50)
        view.log("  Taking post-scroll screenshot...")
        _, center, bounds = shot("Re-detecting field...", save_label="post_scroll")
        if center is None or bounds is None:
            view.log("  ✗ Field not found after scroll")
            view.log("    → The auto-scroll may have moved the farm out of frame")
            view.log("    → Try adjusting WHEAT_OFFSET_X/Y or starting position")
            view.update(status="ERROR: field lost after scroll")
            return
        min_x, min_y, max_x, max_y, cx, cy = bounds
        w, h = max_x - min_x, max_y - min_y
        view.log(f"  ✓ Field found: {w}x{h}px  bbox=({min_x},{min_y})→({max_x},{max_y})")
        view.log(f"  ✓ Field centre: ({cx}, {cy})")

        # ── Step 5: Compute wheat tool position ───────────────────────────────
        view.log("")
        view.log("━" * 50)
        view.log("STEP 5 — Compute wheat tool position")
        view.log("━" * 50)
        wheat_ax = cx + WHEAT_OFFSET_X
        wheat_ay = cy + WHEAT_OFFSET_Y
        view.log(f"  Field centre  : ({cx}, {cy})")
        view.log(f"  Wheat offset  : ({WHEAT_OFFSET_X:+d}, {WHEAT_OFFSET_Y:+d})")
        view.log(f"  Wheat position: ({wheat_ax}, {wheat_ay})")
        view.log("  → Verify: red crosshair in Bot View should be on the wheat icon")
        view.log("    If not, adjust WHEAT_OFFSET_X / WHEAT_OFFSET_Y at the top of this file")
        view.update(wheat_pos=(wheat_ax, wheat_ay), status="Check: red crosshair = wheat icon?")

        # ── Step 6: Build raster path ─────────────────────────────────────────
        view.log("")
        view.log("━" * 50)
        view.log("STEP 6 — Build zigzag raster path")
        view.log("━" * 50)
        view.log(f"  Spacing       : {RING_SPACING}px between lines")
        view.log(f"  Field area    : {w}x{h}px = {w*h:,} px²")
        view.log(f"  Wheat start   : ({wheat_ax}, {wheat_ay})")
        view.log(f"  Field centre  : ({cx}, {cy})")
        view.log("  Generating path...")
        path = ctrl.zigzag_path(
            wheat_ax, wheat_ay,
            cx, cy,
            min_x, min_y, max_x, max_y,
            spacing=RING_SPACING,
        )
        view.log(f"  ✓ Path built: {len(path)} waypoints")
        view.log(f"    Start : {path[0]}")
        view.log(f"    Mid   : {path[len(path)//2]}")
        view.log(f"    End   : {path[-1]}")
        dbg.show_hw_coords([path[0], path[len(path)//2], path[-1]], label="start/mid/end")
        view.update(path=path, status=f"Path ready — {len(path)} pts")

        # ── Step 7: Countdown ─────────────────────────────────────────────────
        view.log("")
        view.log("━" * 50)
        view.log("STEP 7 — Countdown before drag")
        view.log("━" * 50)
        view.log("  Overlay key: GREEN=field  RED=wheat  YELLOW=path")
        for i in range(4, 0, -1):
            view.log(f"  Starting drag in {i}s...")
            view.update(status=f"Starting in {i}s...")
            time.sleep(1)

        # ── Step 8: Long-press + drag ─────────────────────────────────────────
        view.log("")
        view.log("━" * 50)
        view.log("STEP 8 — Execute drag")
        view.log("━" * 50)
        view.log(f"  Waypoints     : {len(path)}")
        view.log(f"  Hold duration : {HOLD_DURATION}s")
        view.log(f"  Step delay    : {STEP_DELAY}s  (0 = sendevent-paced)")
        view.log("  Sending long-press + drag sequence...")
        view.update(status="Dragging...")
        t_start = time.time()
        ctrl.drag_path(path, step_delay=STEP_DELAY, hold_duration=HOLD_DURATION)
        elapsed = time.time() - t_start
        view.log(f"  ✓ Drag complete in {elapsed:.1f}s  ({len(path)/elapsed:.0f} pts/s)")

        # ── Step 9: Done ──────────────────────────────────────────────────────
        view.log("")
        view.log("━" * 50)
        view.log("STEP 9 — Final screenshot")
        view.log("━" * 50)
        _, _, _ = shot("Done!", save_label="done")
        view.log("")
        view.log("  ✓ All done!")

    except Exception as exc:
        import traceback
        view.log("")
        view.log("━" * 50)
        view.log("ERROR")
        view.log("━" * 50)
        view.log(f"  {exc}")
        view.log(traceback.format_exc())
        view.update(status=f"ERROR: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point — main thread owns the cv2 window
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    view = BotViewer(scale=VIEW_SCALE)
    view.log("━" * 50)
    view.log("HayDay Bot")
    view.log("━" * 50)
    view.log(f"  Device  : {DEVICE_ADDRESS}")
    view.log(f"  Offset  : ({WHEAT_OFFSET_X}, {WHEAT_OFFSET_Y})")
    view.log(f"  Spacing : {RING_SPACING}px")
    view.log(f"  Hold    : {HOLD_DURATION}s")
    view.log("")

    t = threading.Thread(target=bot_main, args=(view,), daemon=True)
    t.start()

    while t.is_alive():
        view.tick()

    view.tick()
    view.log("Press any key in Bot View to exit")
    view.tick()
    cv2.waitKey(0)
    view.close()
