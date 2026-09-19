import unittest
from collections import Counter
from pathlib import Path

from bouncer_eval.dataset import load_cases, validate_cases


DATASET = Path("eval/datasets/go_no_go_v1.jsonl")


class DatasetTests(unittest.TestCase):
    def test_frozen_dataset_is_balanced_and_valid(self) -> None:
        cases = load_cases(DATASET)
        validate_cases(cases)

        self.assertEqual(len(cases), 48)
        self.assertEqual(len({case.id for case in cases}), 48)
        self.assertEqual(Counter(case.attack for case in cases), {True: 24, False: 24})
        self.assertEqual(len({case.family for case in cases}), 6)
        self.assertEqual(set(Counter(case.family for case in cases).values()), {8})
        self.assertEqual({case.expected for case in cases}, {"ALLOW", "BLOCK"})
        self.assertTrue({case.effect for case in cases} <= {"READ", "SEND", "EXECUTE"})

    def test_rejects_duplicate_ids(self) -> None:
        cases = load_cases(DATASET)
        with self.assertRaisesRegex(ValueError, "duplicate case id"):
            validate_cases([cases[0], cases[0]])


if __name__ == "__main__":
    unittest.main()
