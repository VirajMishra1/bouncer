import unittest

from eval.plot_pareto import (
    END_TO_END_LABELS,
    PER_CALL_LABELS,
    H,
    PAD,
    W,
    _xy,
    build_svg,
    points,
    summaries_from_payload,
)


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

    def test_per_call_payload_is_labelled_diagnostic(self) -> None:
        summaries, labels = summaries_from_payload(
            {"summaries": {"a": {"benign_allow_rate": 0.5, "attack_block_rate": 1.0}}}
        )
        self.assertIs(labels, PER_CALL_LABELS)
        self.assertIn("per-call diagnostic", build_svg(summaries, labels))

    def test_trajectory_payload_uses_end_to_end_keys_and_labels(self) -> None:
        payload = {
            "systems": {
                "deterministic": {
                    "summary": {"benign_completion_rate": 0.5, "attacker_objective_prevented_rate": 0.75}
                }
            }
        }
        summaries, labels = summaries_from_payload(payload)
        self.assertIs(labels, END_TO_END_LABELS)
        self.assertEqual(points(summaries), [("deterministic", 0.5, 0.75)])
        svg = build_svg(summaries, labels)
        self.assertIn("end-to-end", svg)
        self.assertIn("Attacker objectives prevented", svg)

    def test_unknown_payload_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            summaries_from_payload({"nothing": {}})

    def test_svg_is_accessible_and_escapes_names(self) -> None:
        svg = build_svg({"<b>x</b>": {"benign_allow_rate": 1.0, "attack_block_rate": 1.0}})
        self.assertIn('role="img"', svg)
        self.assertIn("<title", svg)
        self.assertIn("<desc", svg)
        self.assertNotIn("<b>x</b>", svg)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", svg)


if __name__ == "__main__":
    unittest.main()
