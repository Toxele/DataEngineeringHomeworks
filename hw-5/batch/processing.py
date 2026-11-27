import csv
import io
from collections import Counter
from itertools import combinations

from lab.domain import VacancyPolicy


class PairCalculation:
    def __init__(self):
        self.counts = Counter()
        self.rows = 0
        self.selected = 0

    def consume(self, rows):
        for row in rows:
            self.rows += 1

            if VacancyPolicy.matches(row):
                skills = VacancyPolicy.skills(row["key_skills"])
                self.counts.update(combinations(skills, 2))
                self.selected += 1

    def merge(self, rows):
        for row in rows:
            self.counts[(row["skill_1"], row["skill_2"])] += int(row["frequency"])

    def csv(self):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["skill_1", "skill_2", "frequency"])
        writer.writerows([*pair, count] for pair, count in sorted(self.counts.items()))

        return stream.getvalue()

    def top(self, count=10):
        values = sorted(self.counts.items(), key=lambda item: (-item[1], item[0]))[:count]

        return [{"skills": list(pair), "frequency": frequency} for pair, frequency in values]
