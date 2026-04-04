"""
touch_injector.py – Pure ADB sendevent touch injection.

How it works
------------
Android's input subsystem uses the Linux evdev interface.  The `sendevent`
shell command writes raw input events to /dev/input/eventN.  By sending:

  touch-DOWN → move → move → … → touch-UP

as ONE continuous shell script we get a true, unbroken drag gesture —
unlike `input swipe`, which issues a full DOWN+MOVE+UP per call, making
chained swipes stutter and re-anchor the touch pointer each time.

Protocol (Type B / slot-based, Android ≥ 4.0)
----------------------------------------------
Touch DOWN:
  EV_ABS  ABS_MT_SLOT         0       ← slot 0 (first finger)
  EV_ABS  ABS_MT_TRACKING_ID  1       ← any positive id = finger present
  EV_ABS  ABS_MT_POSITION_X   x
  EV_ABS  ABS_MT_POSITION_Y   y
  EV_ABS  ABS_MT_PRESSURE     50      ← many devices require a non-zero pressure
  EV_KEY  BTN_TOUCH            1
  EV_ABS  ABS_X                x      ← single-touch compatibility layer
  EV_ABS  ABS_Y                y
  EV_SYN  SYN_REPORT           0      ← commit this frame

Move:
  EV_ABS  ABS_MT_POSITION_X   x
  EV_ABS  ABS_MT_POSITION_Y   y
  EV_ABS  ABS_X                x
  EV_ABS  ABS_Y                y
  EV_SYN  SYN_REPORT           0
  sleep   <step_delay>

Touch UP:
  EV_ABS  ABS_MT_TRACKING_ID  4294967295   ← unsigned -1 = finger lifted
  EV_KEY  BTN_TOUCH            0
  EV_SYN  SYN_REPORT           0

Device detection
----------------
We parse `adb shell getevent -p` to find the device that reports
ABS_MT_POSITION_X (code 0x35) and get its max X/Y values (hardware
resolution).  Android logical coordinates are then scaled to hardware
coordinates before being written into the script.

Execution strategy
------------------
The script can be hundreds of lines for a large spiral.  We push it as a
file to /data/local/tmp/hayday_drag.sh and run `sh` on it.  This avoids
ARG_MAX limits, keeps the ADB round-trips to a minimum, and means the
entire drag runs on the device with accurate timing.
"""

import re
import time
import tempfile
import os

# ── sendevent event constants ─────────────────────────────────────────────────
EV_SYN = 0
EV_KEY = 1
EV_ABS = 3

SYN_REPORT           = 0
BTN_TOUCH            = 330
ABS_X                = 0
ABS_Y                = 1
ABS_MT_SLOT          = 47
ABS_MT_POSITION_X    = 53
ABS_MT_POSITION_Y    = 54
ABS_MT_TRACKING_ID   = 57
ABS_MT_PRESSURE      = 58

TRACKING_ID_UP       = 4294967295   # unsigned int(-1) = finger lifted

REMOTE_SCRIPT_PATH   = "/data/local/tmp/hayday_drag.sh"


class TouchInjector:
    """
    Builds and executes sendevent drag scripts via ADB.

    Args:
        adb_client   : an ADBClient instance
        step_delay   : seconds between move events (default 0.015)
        pressure     : ABS_MT_PRESSURE value to report (0 = skip; 50 = typical)
    """

    def __init__(self, adb_client, step_delay=0.015, pressure=50):
        self.adb = adb_client
        self.step_delay = step_delay
        self.pressure = pressure

        self._device = None          # /dev/input/eventN
        self._hw_max_x = None        # hardware X resolution - 1
        self._hw_max_y = None        # hardware Y resolution - 1
        self._android_w = None       # logical Android width
        self._android_h = None       # logical Android height

    # ── setup ─────────────────────────────────────────────────────────────────

    def setup(self, android_w, android_h):
        """
        Detect touch device and store Android logical resolution.
        Call this once after ADB connect.
        """
        self._android_w = android_w
        self._android_h = android_h
        self._device, self._hw_max_x, self._hw_max_y = self._detect_touch_device()
        print(
            f"[Touch] device={self._device}  "
            f"hw={self._hw_max_x+1}×{self._hw_max_y+1}  "
            f"logical={android_w}×{android_h}"
        )

    def _detect_touch_device(self):
        """
        Parse `getevent -p` output.
        Returns (device_path, max_x, max_y).
        Falls back to /dev/input/event0 with Android resolution as hw resolution.
        """
        try:
            raw = self.adb.shell("getevent", "-p", check=False, timeout=15)
        except Exception:
            raw = ""

        current_dev = None
        current_max_x = None
        current_max_y = None

        # getevent -p output looks like:
        #   add device N: /dev/input/eventX
        #     name: "..."
        #     events:
        #       ABS (0003): 0035  : value 0, min 0, max 1079, ...
        #                   0036  : value 0, min 0, max 1919, ...

        for line in raw.splitlines():
            dev_match = re.match(r"\s*add device\s+\d+:\s+(/dev/input/\S+)", line)
            if dev_match:
                # Save previous device if it had both axes
                if current_dev and current_max_x is not None and current_max_y is not None:
                    print(f"[Touch] Found touch device: {current_dev}")
                    return current_dev, current_max_x, current_max_y
                current_dev = dev_match.group(1)
                current_max_x = None
                current_max_y = None
                continue

            # Match absolute axis lines:  "  0035  : value 0, min 0, max 1079, ..."
            abs_match = re.match(
                r"\s+([0-9a-fA-F]{4})\s*:\s*value\s+\d+,\s*min\s+\d+,\s*max\s+(\d+)",
                line,
            )
            if abs_match and current_dev:
                code = int(abs_match.group(1), 16)
                max_val = int(abs_match.group(2))
                if code == ABS_MT_POSITION_X:
                    current_max_x = max_val
                elif code == ABS_MT_POSITION_Y:
                    current_max_y = max_val

        # Check last device
        if current_dev and current_max_x is not None and current_max_y is not None:
            print(f"[Touch] Found touch device: {current_dev}")
            return current_dev, current_max_x, current_max_y

        # Fallback
        print("[Touch] Could not detect touch device, defaulting to /dev/input/event0")
        fallback_x = (self._android_w or 720) - 1
        fallback_y = (self._android_h or 1280) - 1
        return "/dev/input/event0", fallback_x, fallback_y

    # ── coordinate mapping ────────────────────────────────────────────────────

    def _to_hw(self, ax, ay):
        """Map Android logical coordinates to hardware input coordinates."""
        if self._android_w and self._android_h:
            hx = int(ax * self._hw_max_x / (self._android_w - 1))
            hy = int(ay * self._hw_max_y / (self._android_h - 1))
        else:
            hx, hy = int(ax), int(ay)
        hx = max(0, min(self._hw_max_x, hx))
        hy = max(0, min(self._hw_max_y, hy))
        return hx, hy

    # ── script building ───────────────────────────────────────────────────────

    def _se(self, ev_type, code, value):
        """Return one sendevent shell line."""
        return f"sendevent {self._device} {ev_type} {code} {value}"

    def _syn(self):
        return self._se(EV_SYN, SYN_REPORT, 0)

    def build_drag_script(self, android_points, step_delay=None, hold_duration=0.8):
        """
        Build a complete sh script that performs a continuous drag.

        android_points : list of (ax, ay) in Android logical coordinates
        step_delay     : seconds between move events (overrides instance default)
        hold_duration  : seconds to hold at the start position before moving.
                         Use ~0.8 s so Hay Day registers the long-press
                         (item pick-up) before the drag begins.

        Returns the script as a string.
        """
        if not android_points:
            return ""

        delay = step_delay if step_delay is not None else self.step_delay
        lines = ["#!/bin/sh"]

        # ── touch DOWN ───────────────────────────────────────────────────────
        hx0, hy0 = self._to_hw(*android_points[0])
        lines += [
            self._se(EV_ABS, ABS_MT_SLOT,         0),
            self._se(EV_ABS, ABS_MT_TRACKING_ID,  1),
            self._se(EV_ABS, ABS_MT_POSITION_X,   hx0),
            self._se(EV_ABS, ABS_MT_POSITION_Y,   hy0),
        ]
        if self.pressure:
            lines.append(self._se(EV_ABS, ABS_MT_PRESSURE, self.pressure))
        lines += [
            self._se(EV_KEY, BTN_TOUCH,            1),
            self._se(EV_ABS, ABS_X,                hx0),
            self._se(EV_ABS, ABS_Y,                hy0),
            self._syn(),
        ]

        # ── hold at start (long-press to pick up item) ────────────────────────
        lines.append(f"sleep {hold_duration:.3f}")

        # ── move events ───────────────────────────────────────────────────────
        # Keep only ABS_MT_POSITION_X/Y + SYN_REPORT per move (3 calls).
        # ABS_X/ABS_Y are single-touch compat events only needed at touch-down;
        # omitting them from moves halves the sendevent call count and
        # cuts total script execution time significantly.
        prev_hx, prev_hy = hx0, hy0
        for ax, ay in android_points[1:]:
            hx, hy = self._to_hw(ax, ay)
            if hx == prev_hx and hy == prev_hy:
                continue
            lines += [
                self._se(EV_ABS, ABS_MT_POSITION_X, hx),
                self._se(EV_ABS, ABS_MT_POSITION_Y, hy),
                self._syn(),
            ]
            if delay > 0:
                lines.append(f"sleep {delay:.4f}")
            prev_hx, prev_hy = hx, hy

        # ── touch UP ──────────────────────────────────────────────────────────
        lines += [
            self._se(EV_ABS, ABS_MT_TRACKING_ID, TRACKING_ID_UP),
            self._se(EV_KEY, BTN_TOUCH,           0),
            self._syn(),
        ]

        return "\n".join(lines) + "\n"

    # ── execution ─────────────────────────────────────────────────────────────

    def drag(self, android_points, step_delay=None, hold_duration=None):
        """
        Execute a continuous drag through `android_points`.

        hold_duration : seconds to hold at start before moving (default 0.8 s).
                        This is the long-press that picks up items in Hay Day.

        Writes the script to the device and runs it as a single shell process.
        Returns when the drag is complete.
        """
        if not android_points:
            return

        if self._device is None:
            raise RuntimeError("TouchInjector not set up — call setup() first")

        script = self.build_drag_script(
            android_points,
            step_delay=step_delay,
            hold_duration=hold_duration if hold_duration is not None else 0.8,
        )
        n_lines = script.count("\n")
        print(f"[Touch] Drag script: {len(android_points)} points, {n_lines} lines")

        # Push script to device
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, encoding="utf-8", newline="\n"
        ) as tf:
            tf.write(script)
            local_tmp = tf.name

        try:
            self.adb.run(
                "-s", self.adb.device_address,
                "push", local_tmp, REMOTE_SCRIPT_PATH,
            )
        finally:
            os.unlink(local_tmp)

        # Estimate total duration for timeout.
        # Each sendevent call spawns a child process (~5 ms overhead on Android).
        # Add sleep time on top, then a generous headroom.
        n_lines    = script.count("\n")
        n_sleeps   = sum(1 for l in script.splitlines() if l.startswith("sleep"))
        delay      = step_delay if step_delay is not None else self.step_delay
        sleep_s    = n_sleeps * delay + hold_duration
        sendevent_s = (n_lines - n_sleeps) * 0.006   # ~6 ms per sendevent call
        estimated_s = sleep_s + sendevent_s
        timeout     = max(60, int(estimated_s * 1.5) + 15)

        print(f"[Touch] Executing drag (~{estimated_s:.1f}s, timeout={timeout}s)...")
        try:
            self.adb.shell(
                "sh", REMOTE_SCRIPT_PATH,
                check=False,
                timeout=timeout,
            )
        finally:
            self.adb.shell("rm", "-f", REMOTE_SCRIPT_PATH, check=False)

        print("[Touch] Drag complete")
