"""
MemuController – pure-ADB controller for MEmu.

All input (taps, drags) goes through ADB.  No Windows mouse hijacking.
"""
import math
import os
import time

import cv2

from .adb import ADBClient
from .touch_injector import TouchInjector


class MemuController:
    """
    High-level controller for a MEmu Android emulator instance.

    Args:
        adb_path        : path to adb.exe
        device_address  : e.g. "127.0.0.1:21503"
        step_delay      : seconds between drag move events (default 0.015)
        log             : callable for status messages (default print)
    """

    def __init__(
        self,
        adb_path,
        device_address,
        step_delay=0.015,
        log=None,
    ):
        self.adb = ADBClient(adb_path, device_address)
        self.touch = TouchInjector(self.adb, step_delay=step_delay)
        self._log = log or print
        self._local_screenshot = os.path.join(os.getcwd(), "_hayday_screen.png")
        self._screen_cache = None

    # ── setup ─────────────────────────────────────────────────────────────────

    def connect(self):
        """Connect ADB and initialise the touch injector."""
        self.adb.connect()
        try:
            w, h = self.adb.get_screen_size()
        except Exception as e:
            self._log(f"[Controller] Could not get screen size: {e}  — assuming 720×1280")
            w, h = 720, 1280
        self.touch.setup(w, h)

    # ── screenshot ────────────────────────────────────────────────────────────

    def screenshot(self):
        """Capture and return the current screen as a BGR numpy array."""
        self.adb.screenshot(self._local_screenshot)
        screen = cv2.imread(self._local_screenshot)
        self._screen_cache = screen
        return screen

    # ── basic input ───────────────────────────────────────────────────────────

    def tap(self, ax, ay):
        """Tap at Android logical coordinates."""
        self._log(f"[Controller] tap ({ax}, {ay})")
        self.adb.tap(ax, ay)

    def long_press(self, ax, ay, duration_ms=800):
        """Long-press (hold in place) at Android logical coordinates."""
        self._log(f"[Controller] long_press ({ax}, {ay}) {duration_ms}ms")
        self.adb.long_press(ax, ay, duration_ms)

    # ── drag ──────────────────────────────────────────────────────────────────

    def drag_path(self, android_points, step_delay=None, hold_duration=None):
        """
        Perform a continuous drag through a list of Android (ax, ay) points.

        The entire sequence is a single unbroken touch gesture (DOWN → moves → UP).

        hold_duration : seconds to hold at the first point before starting to move.
                        Set to ~0.8 to simulate a long-press pick-up.
        """
        if not android_points:
            return
        self._log(f"[Controller] drag_path: {len(android_points)} points")
        self.touch.drag(android_points, step_delay=step_delay, hold_duration=hold_duration)

    # ── path generation ───────────────────────────────────────────────────────

    @staticmethod
    def straight_line(ax1, ay1, ax2, ay2, steps=20):
        """Return interpolated points from (ax1,ay1) to (ax2,ay2)."""
        return [
            (
                int(ax1 + (ax2 - ax1) * i / steps),
                int(ay1 + (ay2 - ay1) * i / steps),
            )
            for i in range(steps + 1)
        ]

    @staticmethod
    def zigzag_path(
        start_ax, start_ay,
        cx, cy,
        min_x, min_y, max_x, max_y,
        spacing=40,
        point_spacing=None,
    ):
        """
        Drag path:
          1. Wheat → top-left of field  (unclamped lead-in).
          2. Horizontal rows left↔right across the field top-to-bottom.
             At each edge the finger makes a tight semicircular U-turn so
             there is no sharp corner and no wasted movement — every part
             of the detected field is covered without lifting.

        The U-turns bulge just outside the field boundary (right of max_x /
        left of min_x) by `spacing/2` pixels — the game ignores touches
        outside the soil so this is fine.

        Fields are never skipped because each row overlaps the turn of the
        previous one by exactly the turn radius.
        """
        if point_spacing is None:
            point_spacing = spacing

        r = max(4, spacing // 2)   # U-turn radius = half the row gap

        # ── helpers ───────────────────────────────────────────────────────

        def free_seg(x1, y1, x2, y2):
            """Unclamped — for lead-in from wheat (which lives outside the field)."""
            dist  = max(abs(x2 - x1), abs(y2 - y1), 1)
            steps = max(1, dist // point_spacing)
            return [(int(x1 + (x2-x1)*i/steps),
                     int(y1 + (y2-y1)*i/steps))
                    for i in range(steps + 1)]

        def row(x_from, x_to, y):
            """Horizontal row clamped to field bounds."""
            dist  = max(abs(x_to - x_from), 1)
            steps = max(1, dist // point_spacing)
            return [(max(min_x, min(max_x, int(x_from + (x_to-x_from)*i/steps))),
                     max(min_y, min(max_y, int(y))))
                    for i in range(steps + 1)]

        def right_uturn(x_edge, y_top):
            """
            Semicircle at the RIGHT edge:
              (x_edge, y_top) → arc right → (x_edge, y_top + 2r)
            Center = (x_edge, y_top + r), radius = r, clockwise.
            """
            cy_t = y_top + r
            n    = max(8, int(math.pi * r / point_spacing))
            return [(int(x_edge + r * math.cos(-math.pi/2 + math.pi*i/n)),
                     int(cy_t   + r * math.sin(-math.pi/2 + math.pi*i/n)))
                    for i in range(n + 1)]

        def left_uturn(x_edge, y_top):
            """
            Semicircle at the LEFT edge:
              (x_edge, y_top) → arc left → (x_edge, y_top + 2r)
            Center = (x_edge, y_top + r), radius = r, counter-clockwise.
            """
            cy_t = y_top + r
            n    = max(8, int(math.pi * r / point_spacing))
            return [(int(x_edge + r * math.cos(-math.pi/2 - math.pi*i/n)),
                     int(cy_t   + r * math.sin(-math.pi/2 - math.pi*i/n)))
                    for i in range(n + 1)]

        # ── build path ────────────────────────────────────────────────────

        pts = []

        # Lead-in: wheat → field centre
        pts += free_seg(start_ax, start_ay, cx, cy)

        # Small circle at centre
        circle_r = spacing
        n_circle  = max(16, int(2 * math.pi * circle_r / point_spacing))
        for i in range(n_circle + 1):
            angle = -math.pi / 2 + 2 * math.pi * i / n_circle
            pts.append((
                max(min_x, min(max_x, int(cx + circle_r * math.cos(angle)))),
                max(min_y, min(max_y, int(cy + circle_r * math.sin(angle)))),
            ))

        # Move from centre to top-left to start the zigzag rows
        pts += free_seg(pts[-1][0], pts[-1][1], min_x, min_y)

        going_right = True
        y = min_y

        while y <= max_y:
            if going_right:
                pts += row(min_x, max_x, y)
                next_y = y + spacing
                if next_y <= max_y:
                    pts += right_uturn(max_x, y)   # connects row y → row y+spacing
            else:
                pts += row(max_x, min_x, y)
                next_y = y + spacing
                if next_y <= max_y:
                    pts += left_uturn(min_x, y)

            if next_y > max_y:
                break
            y           = next_y
            going_right = not going_right

        return pts
