"""
debug_dragger.py — Debug-rich drag helper for diagnosing pick-up + drag issues.

Common failure causes
---------------------
1. Wrong touch device   — sendevent goes to keyboard or sensor, not touchscreen
2. Wrong hw coords      — scaling from Android logical → hardware is off
3. Hold too short       — Hay Day needs ≥ ~0.7 s to register long-press pick-up
4. Wrong wheat offset   — finger lands on empty sky, not the wheat icon
5. Sendevent permission — /dev/input/eventN may be 0600 root; check with `ls -l`

Use the test_ methods below to isolate which layer is broken before doing
a full field drag.
"""

import os
import time


class DebugDragger:
    """
    Wraps MemuController / TouchInjector with test modes and verbose output.

    Args:
        controller  : MemuController instance
        overlay     : BotOverlay (for log output) or None
        script_dir  : directory to save generated scripts (default cwd)
    """

    def __init__(self, controller, overlay=None, script_dir=None):
        self.ctrl       = controller
        self.ov         = overlay
        self.script_dir = script_dir or os.getcwd()

    def _log(self, msg):
        print(msg)
        if self.ov:
            self.ov.log(msg)

    # ── device diagnostics ────────────────────────────────────────────────────

    def list_input_devices(self):
        """
        Print all /dev/input/event* devices and their permissions.
        Helps verify which device is the touchscreen and whether root is needed.
        """
        self._log("=== Input Devices ===")
        try:
            ls = self.ctrl.adb.shell("ls", "-l", "/dev/input/", check=False)
            for line in ls.splitlines():
                self._log(f"  {line}")
        except Exception as e:
            self._log(f"  [ERR] ls failed: {e}")

        self._log("--- getevent names ---")
        try:
            raw = self.ctrl.adb.shell("getevent", "-i", check=False, timeout=10)
            for line in raw.splitlines():
                if line.startswith("add device") or "name:" in line.lower():
                    self._log(f"  {line.strip()}")
        except Exception as e:
            self._log(f"  [ERR] getevent -i failed: {e}")

        self._log(f"  → touch injector using: {self.ctrl.touch._device}")
        self._log(
            f"  → hw max: {self.ctrl.touch._hw_max_x}x{self.ctrl.touch._hw_max_y}  "
            f"logical: {self.ctrl.touch._android_w}x{self.ctrl.touch._android_h}"
        )

    def show_hw_coords(self, android_points, label=""):
        """
        Log the hardware sendevent coordinates for a list of Android points.
        Use this to verify the coordinate scaling is correct.
        """
        self._log(f"=== HW coord check {label} ===")
        for i, (ax, ay) in enumerate(android_points[:5]):
            hx, hy = self.ctrl.touch._to_hw(ax, ay)
            self._log(f"  [{i}] android ({ax},{ay}) → hw ({hx},{hy})")
        if len(android_points) > 5:
            self._log(f"  ... ({len(android_points)} points total)")

    # ── incremental tests ─────────────────────────────────────────────────────

    def test_tap(self, ax, ay, label="tap"):
        """
        Send a single ADB tap, then take a screenshot.
        Use this to verify the wheat icon coordinates are right.
        """
        self._log(f"=== TEST: tap at ({ax},{ay}) [{label}] ===")
        self.ctrl.adb.tap(ax, ay)
        time.sleep(0.3)
        screen = self.ctrl.screenshot()
        self._log("  Screenshot taken — inspect bot_view.png")
        return screen

    def test_hold_only(self, ax, ay, duration=1.0):
        """
        Touch DOWN at (ax,ay), hold for `duration` seconds, then UP.
        Take a screenshot mid-hold to see if the item was picked up.

        This tests whether the long-press mechanism works at all.
        """
        self._log(f"=== TEST: hold-only at ({ax},{ay}) for {duration}s ===")
        self._log("  Sending touch DOWN...")

        inj = self.ctrl.touch
        # Build a minimal hold script: down → sleep → up
        script_lines = ["#!/bin/sh"]
        hx, hy = inj._to_hw(ax, ay)
        script_lines += [
            inj._se(3, 47, 0),                   # ABS_MT_SLOT 0
            inj._se(3, 57, 1),                   # ABS_MT_TRACKING_ID 1
            inj._se(3, 53, hx),                  # ABS_MT_POSITION_X
            inj._se(3, 54, hy),                  # ABS_MT_POSITION_Y
            inj._se(3, 58, 50),                  # ABS_MT_PRESSURE
            inj._se(1, 330, 1),                  # BTN_TOUCH 1
            inj._se(3, 0, hx),                   # ABS_X
            inj._se(3, 1, hy),                   # ABS_Y
            inj._se(0, 0, 0),                    # SYN_REPORT
            f"sleep {duration:.2f}",
            inj._se(3, 57, 4294967295),          # TRACKING_ID -1 (lift)
            inj._se(1, 330, 0),                  # BTN_TOUCH 0
            inj._se(0, 0, 0),                    # SYN_REPORT
        ]
        script = "\n".join(script_lines) + "\n"
        self._save_script(script, "test_hold.sh")

        self._run_script(script, timeout=int(duration) + 5)
        time.sleep(0.3)
        screen = self.ctrl.screenshot()
        self._log("  Hold complete — screenshot taken, check if item was picked up")
        return screen

    def test_simple_drag(self, ax1, ay1, ax2, ay2, hold=0.8, delay=0.02):
        """
        Drag from (ax1,ay1) to (ax2,ay2) in a straight line.
        Tests that sendevent drag works at all on this device.
        Choose two points within a field plot to see a visible result.
        """
        self._log(f"=== TEST: simple drag ({ax1},{ay1}) → ({ax2},{ay2}) ===")
        from .controller import MemuController  # noqa: F401 (static method only)
        pts = MemuController.straight_line(ax1, ay1, ax2, ay2, steps=30)
        self.show_hw_coords(pts, label="simple drag")
        script = self.ctrl.touch.build_drag_script(pts, step_delay=delay, hold_duration=hold)
        self._save_script(script, "test_drag.sh")
        self._run_script(script, timeout=30)
        time.sleep(0.3)
        return self.ctrl.screenshot()

    def dry_run(self, path, soil_bounds, wheat_pos, save_script=True):
        """
        Build the drag script and show the plan without executing the drag.
        Saves the script so you can inspect every sendevent line.
        """
        self._log(f"=== DRY RUN: {len(path)} points ===")
        self.show_hw_coords(path[:3], label="start")
        self.show_hw_coords(path[-3:], label="end")

        script = self.ctrl.touch.build_drag_script(
            path,
            step_delay=self.ctrl.touch.step_delay,
            hold_duration=0.8,
        )

        n_moves = sum(1 for l in script.splitlines() if l.startswith("sleep"))
        est_s   = n_moves * self.ctrl.touch.step_delay + 0.8
        self._log(f"  Script: {script.count(chr(10))} lines, "
                  f"~{n_moves} move steps, est. {est_s:.1f}s runtime")

        if save_script:
            path_out = self._save_script(script, "hayday_drag.sh")
            self._log(f"  Script saved → {path_out}")

        # Show plan on overlay
        if self.ov:
            min_x, min_y, max_x, max_y, cx, cy = soil_bounds
            self.ov.set_state(
                soil_bounds=soil_bounds,
                wheat_pos=wheat_pos,
                path=path,
                status=f"DRY RUN — {len(path)} pts, ~{est_s:.0f}s",
            )

    # ── script helpers ────────────────────────────────────────────────────────

    def _save_script(self, script, filename):
        """Write script to disk for inspection."""
        path = os.path.join(self.script_dir, filename)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(script)
        self._log(f"  [saved] {path}")
        return path

    def _run_script(self, script, timeout=60):
        """Push and execute a shell script on the device."""
        import tempfile
        remote = "/data/local/tmp/hayday_test.sh"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, encoding="utf-8", newline="\n"
        ) as tf:
            tf.write(script)
            local = tf.name
        try:
            self.ctrl.adb.run("-s", self.ctrl.adb.device_address,
                               "push", local, remote)
        finally:
            os.unlink(local)
        result = self.ctrl.adb.shell("sh", remote, check=False, timeout=timeout)
        self.ctrl.adb.shell("rm", "-f", remote, check=False)
        if result:
            self._log(f"  [device output] {result[:200]}")
