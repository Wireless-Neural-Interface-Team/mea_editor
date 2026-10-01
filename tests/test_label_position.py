"""Map-label side and rotation for native JSON only."""

from __future__ import annotations

import unittest

from mea_editor.electrode import (
    DEFAULT_LABEL_ORIENTATION,
    DEFAULT_LABEL_POSITION,
    LABEL_ORIENTATIONS,
    LABEL_POSITIONS,
    map_label_item_pos,
    normalize_label_orientation,
    normalize_label_position,
    outside_label_gap,
    rotated_label_item_aabb,
)


class LabelPositionTests(unittest.TestCase):
    def test_normalize_known_values(self) -> None:
        for value in LABEL_POSITIONS:
            self.assertEqual(normalize_label_position(value), value)
            self.assertEqual(normalize_label_position(value.upper()), value)

    def test_normalize_falls_back_to_below(self) -> None:
        self.assertEqual(DEFAULT_LABEL_POSITION, "below")
        self.assertEqual(normalize_label_position(None), "below")
        self.assertEqual(normalize_label_position(""), "below")
        self.assertEqual(normalize_label_position("diagonal"), "below")

    def test_outside_offsets(self) -> None:
        above = map_label_item_pos("above", half_x=10.0, half_y=8.0, text_w=6.0, text_h=4.0, gap=2.0)
        below = map_label_item_pos("below", half_x=10.0, half_y=8.0, text_w=6.0, text_h=4.0, gap=2.0)
        left = map_label_item_pos("left", half_x=10.0, half_y=8.0, text_w=6.0, text_h=4.0, gap=2.0)
        right = map_label_item_pos("right", half_x=10.0, half_y=8.0, text_w=6.0, text_h=4.0, gap=2.0)
        self.assertEqual(above, (-3.0, 14.0))
        self.assertEqual(below, (-3.0, -10.0))
        self.assertEqual(left, (-18.0, 2.0))
        self.assertEqual(right, (12.0, 2.0))


class LabelOrientationTests(unittest.TestCase):
    def test_normalize_known_values(self) -> None:
        self.assertEqual(DEFAULT_LABEL_ORIENTATION, 0)
        for value in LABEL_ORIENTATIONS:
            self.assertEqual(normalize_label_orientation(value), value)
            self.assertEqual(normalize_label_orientation(float(value)), value)
            self.assertEqual(normalize_label_orientation(str(value)), value)
            self.assertEqual(normalize_label_orientation(f"{value}°"), value)

    def test_normalize_aliases_and_fallback(self) -> None:
        self.assertEqual(normalize_label_orientation("horizontal"), 0)
        self.assertEqual(normalize_label_orientation("vertical"), 90)
        self.assertEqual(normalize_label_orientation(None), 0)
        self.assertEqual(normalize_label_orientation(""), 0)
        self.assertEqual(normalize_label_orientation(45), 0)

    def test_rotated_aabb_90(self) -> None:
        min_x, min_y, max_x, max_y = rotated_label_item_aabb(6.0, 4.0, 90)
        self.assertAlmostEqual(min_x, -4.0)
        self.assertAlmostEqual(min_y, -6.0)
        self.assertAlmostEqual(max_x, 0.0)
        self.assertAlmostEqual(max_y, 0.0)

    def test_outside_offsets_keep_contact_clear_when_rotated(self) -> None:
        x, y = map_label_item_pos(
            "below",
            half_x=10.0,
            half_y=8.0,
            text_w=6.0,
            text_h=4.0,
            gap=2.0,
            orientation=90,
        )
        self.assertAlmostEqual(x, 2.0)
        self.assertAlmostEqual(y, -10.0)

    def test_outside_gap_adds_a_space_on_the_long_axis(self) -> None:
        self.assertEqual(outside_label_gap("left", 0, gap=2.0, space_w=3.0), 5.0)
        self.assertEqual(outside_label_gap("right", 180, gap=2.0, space_w=3.0), 5.0)
        self.assertEqual(outside_label_gap("above", 90, gap=2.0, space_w=3.0), 5.0)
        self.assertEqual(outside_label_gap("below", 270, gap=2.0, space_w=3.0), 5.0)
        self.assertEqual(outside_label_gap("above", 0, gap=2.0, space_w=3.0), 2.0)
        self.assertEqual(outside_label_gap("below", 180, gap=2.0, space_w=3.0), 2.0)
        self.assertEqual(outside_label_gap("left", 90, gap=2.0, space_w=3.0), 2.0)
        self.assertEqual(outside_label_gap("right", 270, gap=2.0, space_w=3.0), 2.0)

    def test_outside_offsets_include_space_width_when_needed(self) -> None:
        left = map_label_item_pos(
            "left",
            half_x=10.0,
            half_y=8.0,
            text_w=6.0,
            text_h=4.0,
            gap=2.0,
            orientation=0,
            space_w=3.0,
        )
        right = map_label_item_pos(
            "right",
            half_x=10.0,
            half_y=8.0,
            text_w=6.0,
            text_h=4.0,
            gap=2.0,
            orientation=180,
            space_w=3.0,
        )
        above = map_label_item_pos(
            "above",
            half_x=10.0,
            half_y=8.0,
            text_w=6.0,
            text_h=4.0,
            gap=2.0,
            orientation=90,
            space_w=3.0,
        )
        below = map_label_item_pos(
            "below",
            half_x=10.0,
            half_y=8.0,
            text_w=6.0,
            text_h=4.0,
            gap=2.0,
            orientation=270,
            space_w=3.0,
        )
        self.assertEqual(left, (-21.0, 2.0))
        self.assertAlmostEqual(right[0], 21.0)
        self.assertAlmostEqual(right[1], -2.0)
        self.assertAlmostEqual(above[0], 2.0)
        self.assertAlmostEqual(above[1], 19.0)
        self.assertAlmostEqual(below[0], -2.0)
        self.assertAlmostEqual(below[1], -19.0)


if __name__ == "__main__":
    unittest.main()
