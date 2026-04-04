"""
ADB client for communicating with the MEmu Android device.
"""
import subprocess
import os
import time


class ADBClient:
    """Wraps ADB commands for a specific device."""

    def __init__(self, adb_path, device_address):
        self.adb_path = adb_path
        self.device_address = device_address

    def run(self, *args, check=True, timeout=30):
        """Run an ADB command and return stdout string."""
        full_cmd = [self.adb_path] + list(args)
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                check=check,
                timeout=timeout,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"[ADB] Error: {' '.join(full_cmd)}")
            print(f"  returncode={e.returncode}  stderr={e.stderr.strip()}")
            raise

    def shell(self, *args, check=True, timeout=30):
        """Run an ADB shell command."""
        return self.run("-s", self.device_address, "shell", *args,
                        check=check, timeout=timeout)

    def connect(self):
        """Connect to the ADB device. Returns output string."""
        print(f"[ADB] Connecting to {self.device_address} ...")
        out = self.run("connect", self.device_address)
        print(f"[ADB] {out}")
        return out

    def screenshot(self, local_path):
        """Capture screenshot on device, pull to local_path, clean up remote."""
        remote = "/sdcard/_hayday_shot.png"
        self.shell("screencap", "-p", remote)
        self.run("-s", self.device_address, "pull", remote, local_path)
        self.shell("rm", "-f", remote)

    def get_screen_size(self):
        """
        Return (width, height) of the Android screen.
        Uses `wm size` output like 'Physical size: 720x1280'.
        """
        out = self.shell("wm", "size")
        for line in out.splitlines():
            if "Physical size" in line or "Override size" in line:
                parts = line.split(":")[-1].strip().split("x")
                if len(parts) == 2:
                    return int(parts[0]), int(parts[1])
        # Fallback: parse from `wm size` simpler output
        parts = out.strip().split("x")
        if len(parts) == 2:
            try:
                return int(parts[0].split()[-1]), int(parts[1])
            except ValueError:
                pass
        raise RuntimeError(f"Could not parse screen size from: {out!r}")

    def find_touch_device(self):
        """
        Return the /dev/input/eventN path for the touchscreen.
        Scans getevent output for a device that supports ABS_MT_POSITION_X.
        Falls back to /dev/input/event0 if not found.
        """
        try:
            out = self.shell("getevent", "-p", check=False, timeout=10)
            current_device = None
            for line in out.splitlines():
                if line.startswith("add device"):
                    # "add device 1: /dev/input/event0"
                    current_device = line.split(":")[-1].strip()
                elif "0035" in line or "ABS_MT_POSITION_X" in line:
                    if current_device:
                        print(f"[ADB] Touch device: {current_device}")
                        return current_device
        except Exception:
            pass
        print("[ADB] Could not auto-detect touch device, defaulting to /dev/input/event0")
        return "/dev/input/event0"

    def tap(self, x, y):
        """Send a tap at Android coordinates (x, y)."""
        self.shell("input", "tap", str(int(x)), str(int(y)))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        """Send a single swipe gesture."""
        self.shell(
            "input", "swipe",
            str(int(x1)), str(int(y1)),
            str(int(x2)), str(int(y2)),
            str(int(duration_ms)),
        )

    def long_press(self, x, y, duration_ms=800):
        """Simulate a long press by swiping in place."""
        self.swipe(x, y, x, y, duration_ms)

    def inject_touch_script(self, device_path, script_lines, timeout=120):
        """
        Execute a multi-line sendevent shell script as a single ADB shell call.
        script_lines: list of shell commands (strings).
        """
        script = "; ".join(script_lines)
        return self.shell(script, check=False, timeout=timeout)
