"""Unit tests for the drag-path geometry in memu/controller.py.

The bot's planting accuracy depends entirely on these two pure functions
producing a correct, fully-covering path. ADB / OpenCV / emulator layers
are not exercised here — only the deterministic geometry.
"""

from memu.controller import MemuController


class TestStraightLine:
    def test_includes_both_endpoints(self):
        pts = MemuController.straight_line(0, 0, 10, 20, steps=4)
        assert pts[0] == (0, 0)
        assert pts[-1] == (10, 20)

    def test_returns_steps_plus_one_points(self):
        assert len(MemuController.straight_line(0, 0, 9, 9, steps=9)) == 10

    def test_midpoint_is_interpolated(self):
        pts = MemuController.straight_line(0, 0, 100, 0, steps=10)
        assert (50, 0) in pts

    def test_all_points_are_int_tuples(self):
        pts = MemuController.straight_line(3, 7, 41, 99, steps=7)
        assert all(
            isinstance(p, tuple) and len(p) == 2 and all(isinstance(c, int) for c in p)
            for p in pts
        )

    def test_degenerate_single_step(self):
        assert MemuController.straight_line(5, 5, 5, 5, steps=1) == [(5, 5), (5, 5)]


class TestZigzagPath:
    FIELD = dict(min_x=0, min_y=0, max_x=200, max_y=300)

    def _path(self, spacing=40):
        return MemuController.zigzag_path(
            10, 10, 100, 150, spacing=spacing, **self.FIELD
        )

    def test_starts_at_the_wheat_tool(self):
        pts = self._path()
        assert pts[0] == (10, 10)

    def test_points_are_int_tuples(self):
        assert all(
            isinstance(p, tuple) and len(p) == 2 and all(isinstance(c, int) for c in p)
            for p in self._path()
        )

    def test_rows_cover_field_top_to_bottom(self):
        ys = [y for _, y in self._path()]
        # Coverage should reach near both the top and bottom of the field.
        assert min(ys) <= self.FIELD["min_y"] + 5
        assert max(ys) >= self.FIELD["max_y"] - 50

    def test_x_stays_within_field_plus_uturn_bulge(self):
        spacing = 40
        xs = [x for x, _ in self._path(spacing=spacing)]
        # U-turns are documented to bulge at most ~spacing/2 outside the field.
        assert min(xs) >= self.FIELD["min_x"] - spacing
        assert max(xs) <= self.FIELD["max_x"] + spacing

    def test_smaller_spacing_yields_denser_path(self):
        assert len(self._path(spacing=20)) > len(self._path(spacing=80))

    def test_deterministic(self):
        assert self._path() == self._path()
