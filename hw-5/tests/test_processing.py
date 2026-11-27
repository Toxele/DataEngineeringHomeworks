import csv
import io
import unittest

from batch.processing import PairCalculation


class PairCalculationTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "name": "Разработчик 1C",
                "role": "Программист, разработчик",
                "key_skills": "SQL;Python;sql",
            },
            {
                "name": "Программист 1С",
                "role": "Программист, разработчик",
                "key_skills": "SQL;Python;1c",
            },
            {
                "name": "Разработчик Java",
                "role": "Программист, разработчик",
                "key_skills": "SQL;Java",
            },
            {"name": "Бухгалтер 1С", "role": "Бухгалтер", "key_skills": "SQL;Python"},
        ]

    def test_variant_filter_and_unique_skills(self):
        result = PairCalculation()
        result.consume(self.rows)
        self.assertEqual(result.rows, 4)
        self.assertEqual(result.selected, 2)
        self.assertEqual(result.counts[("python", "sql")], 2)
        self.assertEqual(sum(result.counts.values()), 4)

    def test_split_and_merge_preserve_every_frequency(self):
        expected = PairCalculation()
        expected.consume(self.rows)
        merged = PairCalculation()

        for index in range(3):
            part = PairCalculation()
            part.consume(self.rows[index::3])
            merged.merge(csv.DictReader(io.StringIO(part.csv())))

        self.assertEqual(merged.counts, expected.counts)

    def test_top_orders_equal_counts_by_skill_names(self):
        result = PairCalculation()
        result.consume(self.rows)
        self.assertEqual(
            result.top(3),
            [
                {"skills": ["python", "sql"], "frequency": 2},
                {"skills": ["1с", "python"], "frequency": 1},
                {"skills": ["1с", "sql"], "frequency": 1},
            ],
        )


if __name__ == "__main__":
    unittest.main()
