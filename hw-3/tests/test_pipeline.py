import unittest
from collections import Counter

from lab.domain import VacancyPolicy
from lab.mapreduce import SkillMapper


class PolicyTests(unittest.TestCase):
    def row(self, **changes):
        value = {
            "vacancy_id": "1",
            "name": "Разработчик 1C",
            "role": "Программист, разработчик",
            "area": "Москва",
            "key_skills": " SQL;sql; 1C; 1С ; ; Python  API ",
            "salary_from": "100000",
            "salary_to": "200000",
            "currency": "RUR",
            "gross": "false",
        }

        return value | changes

    def test_segment(self):
        self.assertTrue(VacancyPolicy.matches(self.row()))
        self.assertTrue(VacancyPolicy.matches(self.row(name="Программист 1С:ERP")))

        for title in ("1С / Разработчик", "Программист (1C)", "Разработчик_1С"):
            with self.subTest(title=title):
                self.assertTrue(VacancyPolicy.matches(self.row(name=title)))

        for changes in (
            {"name": "Консультант 1С"},
            {"role": "Аналитик"},
            {"name": "Разработчик C++"},
            {"name": "Разработчик 21C"},
        ):
            self.assertFalse(VacancyPolicy.matches(self.row(**changes)))

    def test_skills_are_a_set(self):
        self.assertEqual(VacancyPolicy.parse(self.row()).skills, ("1с", "python api", "sql"))

    def test_salary_policy(self):
        self.assertEqual(VacancyPolicy.salary(self.row()), 150000)
        self.assertEqual(VacancyPolicy.salary(self.row(salary_to="")), 100000)

        for changes in (
            {"gross": "true"},
            {"currency": "USD"},
            {"salary_to": "50000"},
            {"salary_from": "-1"},
            {"salary_from": "", "salary_to": ""},
        ):
            self.assertIsNone(VacancyPolicy.salary(self.row(**changes)))

    def test_combiner_and_failure(self):
        plain, _ = SkillMapper.execute([self.row(), self.row(vacancy_id="2")], False)
        combined, _ = SkillMapper.execute([self.row(), self.row(vacancy_id="2")], True)
        self.assertEqual(Counter(plain), combined)
        self.assertEqual(sum(combined.values()), 14)

        with self.assertRaises(RuntimeError):
            SkillMapper.execute([self.row()], True, fail=True)


if __name__ == "__main__":
    unittest.main()
