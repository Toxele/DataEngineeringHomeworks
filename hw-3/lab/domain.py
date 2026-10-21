import re
from dataclasses import dataclass

TITLE_SEPARATORS = re.compile(r"[^a-zа-яё0-9]+")
DEVELOPER_KEYWORDS = ("программист", "разработчик", "developer")


@dataclass(frozen=True)
class Vacancy:
    identifier: str
    region: str
    skills: tuple[str, ...]
    salary: float | None


class VacancyPolicy:
    @staticmethod
    def matches(row: dict) -> bool:
        title = row["name"].lower()
        words = TITLE_SEPARATORS.split(title.replace("1c", "1с"))

        return (
            row["role"] == "Программист, разработчик"
            and "1с" in words
            and any(keyword in title for keyword in DEVELOPER_KEYWORDS)
        )

    @staticmethod
    def skills(value: str) -> tuple[str, ...]:
        skills = {
            " ".join(item.lower().split()).replace("1c", "1с")
            for item in value.split(";")
            if item.strip()
        }

        return tuple(sorted(skills))

    @staticmethod
    def salary(row: dict) -> float | None:
        if row["currency"] != "RUR" or row["gross"].lower() != "false":
            return None

        try:
            lo = float(row["salary_from"]) if row["salary_from"] else None
            hi = float(row["salary_to"]) if row["salary_to"] else None
        except ValueError:
            return None

        if any(x is not None and x <= 0 for x in (lo, hi)):
            return None

        if lo is not None and hi is not None and lo > hi:
            return None

        return (lo + hi) / 2 if lo is not None and hi is not None else lo or hi

    @classmethod
    def parse(cls, row: dict) -> Vacancy:
        return Vacancy(
            row["vacancy_id"], row["area"], cls.skills(row["key_skills"]), cls.salary(row)
        )
