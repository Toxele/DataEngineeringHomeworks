CREATE TABLE raw AS
SELECT vacancy_id, name, role, area, key_skills, salary_from, salary_to, currency, gross
FROM read_csv('__INPUT__', header=true, all_varchar=true, parallel=false);

CREATE TABLE vacancies AS
WITH titles AS (
    SELECT *,
        regexp_split_to_array(
            replace(lower(name), '1c', '1с'),
            '[^a-zа-яё0-9]+'
        ) AS title_words
    FROM raw
), chosen AS (
    SELECT *,
        try_cast(salary_from AS DOUBLE) AS lo,
        try_cast(salary_to AS DOUBLE) AS hi
    FROM titles
    WHERE role = 'Программист, разработчик'
      AND list_contains(title_words, '1с')
      AND (
          contains(lower(name), 'программист')
          OR contains(lower(name), 'разработчик')
          OR contains(lower(name), 'developer')
      )
), normalized AS (
    SELECT *,
        list_sort(
            list_distinct(
                list_filter(
                    list_transform(
                        string_split(coalesce(key_skills, ''), ';'),
                        s -> replace(
                            trim(regexp_replace(lower(s), '\s+', ' ', 'g')),
                            '1c',
                            '1с'
                        )
                    ),
                    s -> s <> ''
                )
            )
        ) AS skills
    FROM chosen
)
SELECT vacancy_id,
    area AS region,
    skills,
    CASE
        WHEN currency = 'RUR' AND lower(gross) = 'false'
            AND (lo IS NULL OR lo > 0)
            AND (hi IS NULL OR hi > 0)
            AND (lo IS NULL OR hi IS NULL OR lo <= hi)
        THEN CASE
            WHEN lo IS NOT NULL AND hi IS NOT NULL THEN (lo + hi) / 2
            ELSE coalesce(lo, hi)
        END
        ELSE NULL
    END AS salary
FROM normalized;

CREATE TABLE exploded AS
SELECT vacancy_id, unnest(skills) AS skill FROM vacancies;

CREATE TABLE occurrences AS
SELECT vacancy_id, [skill] AS skills FROM exploded
UNION ALL
SELECT a.vacancy_id, [a.skill, b.skill]
FROM exploded a
JOIN exploded b ON a.vacancy_id = b.vacancy_id AND a.skill < b.skill
UNION ALL
SELECT a.vacancy_id, [a.skill, b.skill, c.skill]
FROM exploded a
JOIN exploded b ON a.vacancy_id = b.vacancy_id AND a.skill < b.skill
JOIN exploded c ON a.vacancy_id = c.vacancy_id AND b.skill < c.skill;

CREATE TABLE frequencies AS
SELECT skills, count(*) AS frequency FROM occurrences GROUP BY skills;
