import copy
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from eval.build_dashboard import (
    DEFAULT_ARCHIVED,
    DEFAULT_PER_CALL,
    DEFAULT_TRAJECTORY,
    TIER_B_LABEL,
    TIER_C_LABEL,
    build_dashboard,
    main,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _embedded(page: str) -> dict:
    match = re.search(r'<script id="bouncer-data" type="application/json">(.*?)</script>', page, re.S)
    assert match, "embedded JSON block missing"
    return json.loads(match.group(1))


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.traj = _load(DEFAULT_TRAJECTORY)
        cls.per_call = _load(DEFAULT_PER_CALL)
        cls.archived = _load(DEFAULT_ARCHIVED)

    def build(self, traj=None, per_call=None, archived="default") -> str:
        archived = self.archived if archived == "default" else archived
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "nested" / "index.html"
            build_dashboard(traj or self.traj, per_call or self.per_call, archived, out)
            return out.read_text(encoding="utf-8")

    # ---- content ---------------------------------------------------------
    def test_builds_from_real_result_files(self) -> None:
        page = self.build()
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn("6/6", page)
        self.assertIn("rts-attack-reformulation", page)
        self.assertGreater(page.count('class="chip '), 26)

    def test_embedded_json_round_trips_and_matches_inputs(self) -> None:
        data = _embedded(self.build())
        det = data["trajectory"]["systems"]["deterministic"]["summary"]
        self.assertEqual(det["attacker_objective_prevented"], 6)
        self.assertEqual(det["benign_completed"], 6)
        self.assertEqual(data["trajectory"]["dataset_sha256"], self.traj["dataset_sha256"])
        self.assertEqual(data["per_call"]["summaries"]["nemotron-super"]["correct"], 45)
        self.assertEqual(data["archived_per_call"]["summaries"]["nemotron-super"]["correct"], 48)
        self.assertEqual(len(data["trajectory"]["systems"]["deterministic"]["outcomes"]), 12)
        self.assertEqual(
            [(f["system"], f["case_id"]) for f in data["per_call"]["failures"]],
            [(f["system"], f["case_id"]) for f in self.per_call["failures"]],
        )
        # URLs inside model text are defanged in the embedded copy (no live links on the page)
        self.assertIn("https[:]//ci.company.example/logs", json.dumps(data["per_call"]["failures"]))

    def test_evidence_tiers_are_labelled_and_separate(self) -> None:
        page = self.build()
        self.assertIn("per-call diagnostic — not end-to-end evidence", page)
        self.assertEqual(TIER_B_LABEL, "per-call diagnostic — not end-to-end evidence")
        self.assertIn("original run — labels leaked into the prompt; archived, do not cite", page)
        self.assertEqual(TIER_C_LABEL, "original run — labels leaked into the prompt; archived, do not cite")
        self.assertIn("end-to-end (headline tier)", page)
        # the archived section is collapsed and sits after the per-call tier
        self.assertRegex(page, r'<details class="arch">')
        self.assertLess(page.index('id="tier-b"'), page.index('id="archived"'))

    def test_archived_run_is_not_plotted(self) -> None:
        page = self.build()
        svg = page[page.index("<svg class=\"scatter\"") : page.index("</svg>", page.index("<svg class=\"scatter\""))]
        self.assertEqual(svg.count('class="pt pc"'), 2)  # deterministic + nemotron-super per-call
        self.assertEqual(svg.count('class="pt e2e"'), 3)  # deterministic, text-rules, no-defense (one dot each)
        self.assertNotIn("nemotron-lightning", svg)
        self.assertIn("<title", svg)
        self.assertIn("<desc", svg)
        # archived comparison note: original 48/48 vs leak-fixed 45/48
        self.assertIn("nemotron-super: 48/48 in the original run, 45/48 after the fix", page)

    def test_honesty_notes_present(self) -> None:
        page = self.build()
        self.assertIn("decides from curator labels", page)
        self.assertIn("upper bound for rules, not a fair", page)
        self.assertIn("cannot separate systems yet", page)
        self.assertIn("12 episodes = 6 attack/benign pairs, one pair per attack family", page)
        self.assertIn("not</strong> proof that Bouncer beats anything", page)
        self.assertIn("not included", page)  # nemotron/hybrid trajectory runs
        self.assertIn("hosted API", page)

    def test_not_yet_shown_items(self) -> None:
        page = self.build()
        for item in (
            "AgentDojo",
            "Post-freeze adaptive attacks",
            "NeMo Guardrails comparison",
            "Hybrid / Nemotron trajectory run",
            "Paired bootstrap confidence intervals",
        ):
            self.assertIn(item, page)

    def test_failures_classified_by_loss_type(self) -> None:
        page = self.build()
        self.assertIn("utility loss", page)
        self.assertIn("4 benign actions not allowed", page)
        self.assertIn("0 attacks missed", page)
        self.assertIn("hex-05", page)
        self.assertIn("dst-06", page)
        self.assertIn("verdict contradicts blocking reason", page)

    def test_long_failure_lists_are_truncated_behind_details(self) -> None:
        per_call = copy.deepcopy(self.per_call)
        per_call["failures"] = [
            {"system": "deterministic", "case_id": f"c-{i:02d}", "expected": "ALLOW", "actual": "BLOCK",
             "reason": "x" * 400, "family": "read_to_send"}
            for i in range(10)
        ]
        page = self.build(per_call=per_call)
        self.assertIn("Show 4 more", page)
        self.assertIn('<details class="more">', page)
        self.assertNotIn("x" * 200, page.split("<script id=\"bouncer-data\"")[0])  # reasons truncated to ~160

    def test_dataset_hash_shortened_with_full_value_in_title(self) -> None:
        page = self.build()
        sha = self.traj["dataset_sha256"]
        self.assertIn(f'title="{sha}"', page)
        self.assertIn(sha[:12] + "…", page)

    # ---- structure / a11y / self-containment ------------------------------
    def test_document_structure_and_accessibility(self) -> None:
        page = self.build()
        self.assertIn('<html lang="en">', page)
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', page)
        self.assertIn('class="skip" href="#main"', page)
        self.assertIn('id="main"', page)
        self.assertRegex(page, r"@media \(prefers-reduced-motion:\s*reduce\)")
        self.assertRegex(page, r"<svg class=\"scatter\"[^>]*>\s*<title")
        self.assertIn(":focus-visible", page)
        self.assertEqual(page.count("<h1"), 1)
        self.assertEqual(page.count("<caption>"), page.count("<table"))
        self.assertIn('scope="col"', page)
        self.assertIn('scope="row"', page)
        self.assertIn("<main", page)
        self.assertIn("<footer", page)

    def test_no_external_urls_or_requests(self) -> None:
        page = self.build()
        urls = re.findall(r"https?://[^\s\"'<>)]+", page)
        self.assertEqual([u for u in urls if u != "http://www.w3.org/2000/svg"], [])
        self.assertNotRegex(page, r"<link\b")
        self.assertNotRegex(page, r"<script[^>]+\bsrc=")
        self.assertNotIn("@import", page)
        self.assertNotIn("url(", page)

    def test_no_secret_shaped_strings(self) -> None:
        page = self.build()
        for needle in ("nvapi-", "sk-", "Bearer "):
            self.assertNotIn(needle, page)

    def test_output_is_deterministic(self) -> None:
        self.assertEqual(self.build(), self.build())

    # ---- safety ----------------------------------------------------------
    def test_failure_text_is_escaped_and_cannot_break_out_of_script(self) -> None:
        per_call = copy.deepcopy(self.per_call)
        evil = '<script>alert(1)</script></script><!-- "quoted" & <img src=x onerror=alert(2)> %%DATA%%'
        per_call["failures"] = [
            {"system": "nemotron-super", "case_id": "x<b>1", "expected": "ALLOW", "actual": None,
             "error": "bad </script> error", "reason": evil, "family": "read_to_send"}
        ]
        traj = copy.deepcopy(self.traj)
        traj["systems"]["deterministic"]["outcomes"][0]["trajectory_id"] = "id</script><script>alert(3)"
        page = self.build(traj=traj, per_call=per_call)
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img", page)
        self.assertNotIn("</script></script>", page)
        self.assertNotIn("<!--", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        # exactly the two legitimate script blocks
        self.assertEqual(len(re.findall(r"<script\b", page)), 2)
        self.assertEqual(len(re.findall(r"</script>", page)), 2)
        # embedded JSON still parses and preserves the value
        data = _embedded(page)
        self.assertEqual(data["per_call"]["failures"][0]["reason"], evil)
        # the placeholder inside user text is never re-expanded
        self.assertIn("%%DATA%%", page.split('<script id="bouncer-data"')[0])

    # ---- validation ------------------------------------------------------
    def test_invalid_inputs_raise_clear_errors(self) -> None:
        cases = [
            ("trajectory", lambda t, p: ({}, p), "trajectory"),
            ("no systems", lambda t, p: ({**t, "systems": {}}, p), "systems"),
            ("no sha", lambda t, p: ({k: v for k, v in t.items() if k != "dataset_sha256"}, p), "dataset_sha256"),
            ("bad summary", lambda t, p: (_drop(t, "attacker_objective_prevented"), p), "attacker_objective_prevented"),
            ("no summaries", lambda t, p: (t, {"failures": []}), "summaries"),
            ("bad failures", lambda t, p: (t, {**p, "failures": "nope"}), "failures"),
        ]
        for name, mutate, needle in cases:
            with self.subTest(name):
                traj, per_call = mutate(copy.deepcopy(self.traj), copy.deepcopy(self.per_call))
                with tempfile.TemporaryDirectory() as directory:
                    out = Path(directory) / "index.html"
                    with self.assertRaisesRegex(ValueError, needle):
                        build_dashboard(traj, per_call, None, out)
                    self.assertFalse(out.exists())

    def test_archived_optional_but_validated(self) -> None:
        page = self.build(archived=None)
        self.assertIn("No archived original run was supplied", page)
        with self.assertRaises(ValueError):
            self.build(archived={"summaries": {}})

    def test_cli_success_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out" / "index.html"
            with redirect_stdout(StringIO()):
                code = main(["--out", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>"))

            missing = Path(directory) / "missing.json"
            bad = Path(directory) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            for args, needle in (
                (["--trajectory-json", str(missing)], "not found"),
                (["--per-call-json", str(bad)], "not valid JSON"),
            ):
                err = StringIO()
                target = Path(directory) / "never.html"
                with redirect_stderr(err):
                    code = main([*args, "--out", str(target)])
                self.assertEqual(code, 2)
                self.assertIn(needle, err.getvalue())
                self.assertFalse(target.exists())


def _drop(traj: dict, key: str) -> dict:
    for system in traj["systems"].values():
        system["summary"].pop(key, None)
    return traj


if __name__ == "__main__":
    unittest.main()
