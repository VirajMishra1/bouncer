import unittest

from eval.plot_pareto import _xy, build_svg, points, H, PAD, W


class PlotTests(unittest.TestCase):
    def test_corners_map_to_axis_bounds(self) -> None:
        # (benign=0, attack=0) -> bottom-left; (1, 1) -> top-right
        self.assertEqual(_xy(0.0, 0.0), (PAD, H - PAD))
        self.assertEqual(_xy(1.0, 1.0), (W - PAD, PAD))

    def test_build_svg_has_a_point_per_system(self) -> None:
        summaries = {
            "deterministic": {"benign_allow_rate": 0.833, "attack_block_rate": 1.0},
            "nemotron-super": {"benign_allow_rate": 1.0, "attack_block_rate": 1.0},
        }
        self.assertEqual(len(points(summaries)), 2)
        svg = build_svg(summaries)
        self.assertTrue(svg.startswith("<svg"))
        self.assertEqual(svg.count("<circle"), 2)
        self.assertIn("nemotron-super", svg)


if __name__ == "__main__":
    unittest.main()
