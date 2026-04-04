"""
viewer.py — OpenCV bot view window, always responsive.

Threading model
---------------
  Bot thread  → viewer.update() / viewer.log()   write shared state under a lock
  Main thread → viewer.tick()                    reads state, redraws, calls waitKey

The main thread calls tick() in a tight loop so Windows never marks the window
as "not responding", even while ADB is blocked executing a 60-second drag script.
"""

import threading
import cv2
import numpy as np
import os

WINDOW    = "HayDay Bot View"
SAVE_PATH = os.path.join(os.getcwd(), "bot_view.png")

_C_FIELD  = (0,   210,  0)
_C_CENTER = (255, 140,  0)
_C_WHEAT  = (0,   0,   255)
_C_PATH   = (0,   220, 255)
_C_TEXT   = (255, 255, 255)
_C_SHADOW = (0,   0,   0)
_FONT     = cv2.FONT_HERSHEY_SIMPLEX


class BotViewer:
    def __init__(self, scale=0.6):
        self.scale   = scale
        self._open   = False
        self._lock   = threading.Lock()
        # Shared state — written by bot thread, read by main thread
        self._screen = None
        self._soil   = None
        self._wheat  = None
        self._path   = None
        self._status = ""
        self._log    = []

    # ── bot-thread API (thread-safe) ──────────────────────────────────────────

    def log(self, msg):
        print(msg)
        with self._lock:
            self._log.append(str(msg))
            if len(self._log) > 30:
                self._log.pop(0)

    def update(self, screen=None, soil_bounds=None, wheat_pos=None,
               path=None, status=None):
        with self._lock:
            if screen      is not None: self._screen = screen.copy()
            if soil_bounds is not None: self._soil   = soil_bounds
            if wheat_pos   is not None: self._wheat  = wheat_pos
            if path        is not None: self._path   = path
            if status      is not None: self._status = str(status)

    # ── main-thread API ───────────────────────────────────────────────────────

    def tick(self, wait_ms=40):
        """Redraw and pump OpenCV events. Call from main thread in a loop."""
        with self._lock:
            screen = self._screen
            soil   = self._soil
            wheat  = self._wheat
            path   = self._path
            status = self._status
            log    = list(self._log)

        if not self._open:
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
            cv2.setWindowProperty(WINDOW, cv2.WND_PROP_TOPMOST, 1)
            self._open = True

        if screen is None:
            cv2.waitKey(wait_ms)
            return

        frame = screen.copy()
        self._draw_field(frame, soil)
        self._draw_path(frame, path)
        self._draw_wheat(frame, wheat)
        self._draw_log(frame, log)
        self._draw_status(frame, status)

        cv2.imwrite(SAVE_PATH, frame)

        if self.scale != 1.0:
            h, w = frame.shape[:2]
            frame = cv2.resize(frame,
                               (int(w * self.scale), int(h * self.scale)),
                               interpolation=cv2.INTER_AREA)

        cv2.imshow(WINDOW, frame)
        cv2.waitKey(wait_ms)

    def close(self):
        if self._open:
            cv2.destroyWindow(WINDOW)
            self._open = False

    # ── drawing (main thread only) ────────────────────────────────────────────

    def _draw_field(self, frame, bounds):
        if not bounds:
            return
        min_x, min_y, max_x, max_y, cx, cy = bounds
        overlay = frame.copy()
        cv2.rectangle(overlay, (min_x, min_y), (max_x, max_y), _C_FIELD, -1)
        cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
        cv2.rectangle(frame, (min_x, min_y), (max_x, max_y), _C_FIELD, 2)
        fw, fh = max_x - min_x, max_y - min_y
        self._txt(frame, min_x + 4, min_y + 16, f"field {fw}x{fh}px", _C_FIELD, sz=0.45)
        r = 12
        cv2.line(frame, (cx - r, cy), (cx + r, cy), _C_CENTER, 2)
        cv2.line(frame, (cx, cy - r), (cx, cy + r), _C_CENTER, 2)
        cv2.circle(frame, (cx, cy), 5, _C_CENTER, -1)
        self._txt(frame, cx + 14, cy + 4, f"({cx},{cy})", _C_CENTER, sz=0.45)

    def _draw_path(self, frame, path):
        if not path or len(path) < 2:
            return
        step = max(1, len(path) // 300)
        pts  = path[::step]
        if pts[-1] != path[-1]:
            pts.append(path[-1])
        arr = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(frame, [arr], False, _C_PATH, 1, cv2.LINE_AA)
        cv2.circle(frame, pts[0],  5, _C_PATH,  -1)
        cv2.circle(frame, pts[-1], 5, _C_WHEAT, -1)
        self._txt(frame, 8, 70, f"path: {len(path)} pts", _C_PATH, sz=0.45)

    def _draw_wheat(self, frame, wheat_pos):
        if not wheat_pos:
            return
        wx, wy = int(wheat_pos[0]), int(wheat_pos[1])
        cv2.circle(frame, (wx, wy), 14, _C_WHEAT, 2)
        cv2.line(frame, (wx - 18, wy), (wx + 18, wy), _C_WHEAT, 1)
        cv2.line(frame, (wx, wy - 18), (wx, wy + 18), _C_WHEAT, 1)
        self._txt(frame, wx + 18, wy, f"wheat ({wx},{wy})", _C_WHEAT, sz=0.45)

    def _draw_log(self, frame, log):
        if not log:
            return
        h, w   = frame.shape[:2]
        pw     = 310
        lh     = 14
        ph     = len(log) * lh + 20
        cv2.rectangle(frame, (w - pw, 0), (w, ph), (20, 20, 20), -1)
        cv2.rectangle(frame, (w - pw, 0), (w, ph), (60, 60, 60),  1)
        for i, line in enumerate(log):
            col = _C_TEXT
            lo  = line.lower()
            if any(k in lo for k in ("error", "✗", "fail", "exception")):
                col = (80, 80, 255)
            elif any(k in lo for k in ("✓", "complete", "done", "success")):
                col = (80, 220, 80)
            elif any(k in lo for k in ("drag", "hold", "tap", "plant", "→")):
                col = (60, 160, 255)
            elif "===" in line:
                col = (200, 130, 255)
            self._txt(frame, w - pw + 6, 16 + i * lh, line[:44], col, sz=0.38)

    def _draw_status(self, frame, status):
        if status:
            self._txt(frame, 8, 26, status, _C_TEXT, sz=0.55)

    def _txt(self, frame, x, y, text, color, sz=0.5):
        cv2.putText(frame, text, (x+1, y+1), _FONT, sz, _C_SHADOW, 2,  cv2.LINE_AA)
        cv2.putText(frame, text, (x,   y),   _FONT, sz, color,     1,  cv2.LINE_AA)
