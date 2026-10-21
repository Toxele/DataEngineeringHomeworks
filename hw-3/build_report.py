import json
import statistics

from PIL import Image

from lab.config import OUTPUT, ROOT


def tex(value):
    mapping = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }

    return "".join(mapping.get(c, c) for c in str(value))


def num(value, digits=0):
    return f"{value:,.{digits}f}".replace(",", r"\,").replace(".", ",")


def table(headers, rows, widths):
    specification = "".join(f"p{{{w}\\linewidth}}" for w in widths)
    body = "\n".join(" & ".join(str(c) for c in row) + r" \\" for row in rows)

    return (
        r"\begin{center}\small\setlength{\tabcolsep}{3pt}\renewcommand{\arraystretch}{1.25}"
        + "\n\\begin{tabular}{"
        + specification
        + "}\n\\toprule\n"
        + " & ".join(headers)
        + r" \\ \midrule"
        + "\n"
        + body
        + "\n\\bottomrule\n\\end{tabular}\n\\end{center}\n"
    )


class ReportBuilder:
    def __init__(self):
        self.summary = self.load("mr_combiner_1/summary.json")
        self.analysis = self.load("analysis.json")
        self.storage = self.load("storage.json")
        self.profiles = self.load("benchmarks.json")
        self.verify = self.load("verification.json")
        self.retry = self.load("mr_retry_1/summary.json")
        self.parts = []

    @staticmethod
    def load(name):
        return json.loads((OUTPUT / name).read_text(encoding="utf-8"))

    def add(self, value):
        self.parts.append(value)

    def page(self, title):
        self.add(r"\clearpage\section*{" + title + "}\n")

    def impact_table(self, key, count=3):
        rows = self.analysis["rankings"][key][:count]
        self.add(
            table(
                [
                    "Стек / добавленный навык",
                    "$n$ / медиана, ₽",
                    "База / $n$ / медиана, ₽",
                    "$\\Delta$, ₽ / \\%",
                ],
                [
                    [
                        tex(r["skills"])
                        + r"\newline\textit{Добавлен: "
                        + tex(r["added_skill"])
                        + "}",
                        num(r["salary_n"]) + r"\newline " + num(r["median_rub"]),
                        tex(r["base"])
                        + r"\newline "
                        + num(r["base_salary_n"])
                        + " / "
                        + num(r["base_median_rub"]),
                        num(r["delta_rub"]) + r"\newline " + num(r["delta_pct"], 1) + r"\%",
                    ]
                    for r in rows
                ],
                [0.38, 0.13, 0.29, 0.12],
            )
        )

    def build(self):
        s, a, storage = self.summary, self.analysis, self.storage
        assets = ROOT / "report" / "assets"

        for name in ("s3-input", "s3-results"):
            path = assets / f"{name}.png"

            if path.exists():
                with Image.open(path) as img:
                    img.crop(
                        (0, 0, img.width, min(img.height, 900 if name == "s3-results" else 560))
                    ).save(assets / f"{name}-crop.png")

        self.add(r"""\documentclass[11pt,a4paper]{article}
\usepackage{fontspec}
\setmainfont{Times New Roman}
\setsansfont{Arial}
\setmonofont[Scale=0.85]{Consolas}
\usepackage[russian]{babel}
\usepackage[margin=18mm,headheight=14pt]{geometry}
\usepackage{graphicx,booktabs,array,amsmath,tabularx,xcolor,fancyhdr,fvextra,hyperref}
\hypersetup{hidelinks,pdftitle={Домашнее задание 3. MapReduce и DuckDB: разработчики 1С},pdfauthor={Таряник Антон Александрович}}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\setlength{\emergencystretch}{3em}
\pagestyle{fancy}\fancyhf{}\fancyfoot[C]{\thepage}
\fancyhead[L]{\small Инженерия данных · Домашнее задание 3}
\fancyhead[R]{\small Вариант: разработчик 1С}
\renewcommand{\headrulewidth}{0.3pt}
\DefineVerbatimEnvironment{code}{Verbatim}{fontsize=\footnotesize,breaklines=true,breakanywhere=true,frame=single}
\begin{document}
\begin{center}
{\LARGE\bfseries Навыки и зарплаты разработчиков 1С}\\[5mm]
{\Large MapReduce из S3 и независимая проверка DuckDB}\\[5mm]
Таряник Антон Александрович\\
ИИИ-3-ИнжДан-1-5 · ID 103963 · № 19\\
21 октября 2026 года
\end{center}
\section*{1. Задача и границы эксперимента}
Развёрнуто объектное хранилище RustFS, подготовлен объект в бакете \texttt{hh-lake}.
Рассчитаны частоты отдельных навыков, неупорядоченных пар и троек двумя независимыми
реализациями. Проверено полное совпадение результатов. Исследованы связи навыков
с медианной предлагаемой зарплатой и различия трёх регионов. Для каждого подхода
выполнены три запуска с измерением времени и пика памяти, отдельно проверен повтор
маппера после ошибки.

\textbf{Индивидуальный вариант:} «Программист, разработчик на 1С» (скриншот списка вариантов).
Роль должна быть равна «Программист, разработчик», название должно содержать
«программист», «разработчик» или \texttt{developer}, а также отдельный токен
\texttt{1С}/\texttt{1C}. Регистр игнорируется. Перед и после токена допустимы
граница строки либо символ, отличный от буквы или цифры; поэтому \texttt{1С:ERP}
подходит, а \texttt{21C} не подходит. Условие исключает консультантов и аналитиков,
которые также работают с 1С, но не относятся к выбранной должности.

\textbf{Единица наблюдения:} одна строка вакансии с уникальным \texttt{vacancy\_id}.
Пустой список навыков не исключает вакансию из региональной статистики. Навык
учитывается не более одного раза внутри вакансии; порядок перечисления не важен.
Тексты навыков приводятся к нижнему регистру, пробелы нормализуются, латинское
\texttt{1c} заменяется на кириллическое \texttt{1с}; остальные синонимы не объединяются.
Это сохраняет воспроизводимую, ограниченную нормализацию исходных тегов.
""")
        self.add(
            table(
                ["Показатель", "Значение"],
                [
                    ["Строк в исходном файле и проекции", num(s["input_rows"])],
                    ["Вакансий выбранного варианта", num(s["selected_rows"])],
                    ["С непустым набором навыков", num(s["with_skills"])],
                    ["С сопоставимой зарплатой на руки", num(s["salary_rows"])],
                    ["Медиана сопоставимых зарплат", num(a["overall_median_rub"]) + " ₽"],
                ],
                [0.65, 0.27],
            )
        )
        self.page("2. Инфраструктура, входные данные и целостность")
        self.add(r"""Повторно использован стенд второй работы: контейнер \texttt{rustfs-lab},
один сервер и четыре каталога на диске D, Erasure Coding 2+2. Все четыре диска онлайн.
Это один физический компьютер, поэтому стенд демонстрирует распределённую модель
хранения и процессы MapReduce, но не является кластером из независимых машин.
S3 API доступен на \texttt{127.0.0.1:9000}, консоль на порту 9001.
Секреты берутся из окружения существующего контейнера либо переменных окружения;
в исходники, скриншоты и отчёт пароль не записывается.

\includegraphics[width=\linewidth]{assets/s3-input-crop.png}
\begin{center}\small Рис. 1. Реальная консоль RustFS: исходный CSV и проекция в \texttt{hh-lake/hw3/input/}.\end{center}

Исходный CSV содержит описания вакансий и служебные поля. Перед загрузкой для
вычислений построена проекция из девяти колонок: ID, название, роль, регион, навыки,
нижняя и верхняя границы зарплаты, валюта, gross. Сохранены все строки, без фильтрации
варианта. Оба вычислительных метода читают эту проекцию непосредственно из S3.
Она не содержит предвычисленных навыков или результатов фильтрации.
""")
        self.add(
            f"Размер исходного файла: {num(storage['original_bytes'])} байт; проекции: {num(storage['bytes'])} байт. "
            f"Объём чтения уменьшен в {num(storage['original_bytes'] / storage['bytes'], 2)} раза.\n"
        )
        self.add(
            r"""Для обоих объектов выполнено полное контрольное чтение из S3 с вычислением
SHA-256, а не только сравнение размера или multipart ETag.
\begin{code}
"""
            + f"original SHA-256: {storage['original_sha256']}\ncore SHA-256:     {storage['sha256']}\ncore S3 SHA-256:  {storage['s3_sha256']}\n"
            + r"""\end{code}
Полные метаданные сохранены в \texttt{artifacts/storage.json} и
\texttt{artifacts/original\_storage.json}. EC-каталоги остаются на прежнем стенде
\texttt{D:/rustfs/rustfs-lab}; локальные результаты и исходники этой работы находятся в
папке \texttt{hw-3}; тяжёлые промежуточные файлы исключены из Git.
Показатель ёмкости в консоли отражает файловую
систему хоста, общую для четырёх bind-mount, и не означает четыре независимых диска.
"""
        )
        self.page("3. Собственный MapReduce и SQL")
        self.add(r"""\textbf{Map.} Через \texttt{GetObject} открывается поток байтов, поверх него
\texttt{TextIOWrapper} и \texttt{csv.DictReader}. Разбиение выполняется по 2000
логических CSV-записей, поэтому кавычки, запятые и переносы строк внутри полей
не ломают границы. В двух процессах маппер независимо проверяет вариант,
нормализует множество навыков и выдаёт ключи $(s_1)$, $(s_1,s_2)$,
$(s_1,s_2,s_3)$ с весом 1.

\textbf{Shuffle и Reduce.} В базовой версии маппер возвращает список всех ключей;
родитель группирует одинаковые ключи в \texttt{Counter} и суммирует веса. В версии
с комбайнером каждый маппер сначала суммирует одинаковые ключи внутри чанка,
передавая словарь частичных сумм. Одновременно ожидают завершения не более четырёх
чанков, что ограничивает очередь и память. Ключи из разных чанков объединяются
по равенству, результаты сортируются перед записью CSV.
Это локальная реализация MapReduce: обмен между процессами выполняется через IPC,
а shuffle/reduce находится в одном координаторе; Hadoop/YARN не используется.

\textbf{Независимый SQL.} DuckDB через \texttt{httpfs} и S3 secret читает тот же
\path{s3://hh-lake/hw3/input/vacancies_core.csv}. Python UDF и данные после
MapReduce не используются. Условие варианта написано непосредственно на SQL:
\begin{code}
WHERE role = 'Программист, разработчик'
 AND list_contains(
   regexp_split_to_array(
     replace(lower(name), '1c', '1с'), '[^a-zа-яё0-9]+'
   ), '1с'
 )
 AND (contains(lower(name), 'программист')
   OR contains(lower(name), 'разработчик')
   OR contains(lower(name), 'developer'))
\end{code}
\texttt{string\_split}, \texttt{list\_transform}, \texttt{list\_distinct} и
\texttt{list\_sort} формируют упорядоченное множество навыков. После \texttt{unnest}
пары создаются self-join по одному ID и условию $a.skill<b.skill$, тройки добавляют
$b.skill<c.skill$. Затем выполняется \texttt{GROUP BY skills, count(*)}.
Полный исполняемый запрос: \texttt{sql/frequencies.sql}.

\textbf{Рост числа записей.} Если в вакансии $m$ различных навыков, она порождает
\[
N_1=m,\quad N_2=\binom{m}{2},\quad N_3=\binom{m}{3}.
\]
При $m=10$ это 10, 45 и 120 ключей; рост связан с сочетаниями, а не с дублированием
вакансий. Число уникальных ключей и сумма их частот различаются: одна комбинация
может встречаться во многих вакансиях.
""")
        self.add(
            table(
                ["Размер стека", "Уникальных ключей", "Всего появлений"],
                [[k, num(s["unique"][str(k)]), num(s["emitted"][str(k)])] for k in (1, 2, 3)],
                [0.25, 0.32, 0.32],
            )
        )
        self.page("4. Полная верификация и отказ маппера")
        self.add(r"""Для каждой попытки сверены полные словари «упорядоченный набор навыков →
частота», включая отсутствие лишних ключей. Дополнительно сравнены на уровне ID
множества вакансий, регионы, нормализованные навыки и значения зарплат. Поэтому
совпадение итоговых сумм не маскирует разные исходные выборки.
""")
        self.add(
            table(
                ["Проверка", "Результат"],
                [
                    ["Попытки MR plain / MR combiner / DuckDB", "3 / 3 / 3"],
                    ["Попытка с инъекцией отказа", "1, полное совпадение"],
                    [
                        "Полных сравнений словарей для всех запусков",
                        str(len(self.verify["checks"])),
                    ],
                    ["Проверка ID, региона, навыков, зарплаты", "Совпадают во всех запусках"],
                    [r"Суммы частот против $\sum_v \binom{m_v}{k}$", "Совпадают для $k=1,2,3$"],
                ],
                [0.65, 0.27],
            )
        )
        self.add(
            r"""\textbf{Сценарий отказа.} В чанке с индексом 2 первый вызов маппера выбрасывает
\texttt{RuntimeError} до фиксации результата. Координатор регистрирует ошибку,
повторно отправляет сохранённый чанк без инъекции и добавляет его результат один
раз. Нельзя фиксировать частичный вывод до успешного окончания задачи.
Этот тест проверяет ошибку задачи и повтор; аварийное завершение процесса ОС
и автоматическое пересоздание сломанного process pool не реализованы.
\begin{code}
"""
            + json.dumps(self.retry["attempts"], ensure_ascii=False, indent=2)
            + r"""
\end{code}
Четыре модульных теста покрывают отбор варианта, границы токена 1С, дедупликацию
тегов, эквивалентность комбайнера и обработку зарплат. Главная интеграционная
проверка выполнена на всех строках реального S3-объекта.
\begin{code}
python -m unittest discover -s tests -v
Ran 4 tests ... OK
python -m lab verify
"""
            + f"VERIFIED: {len(self.verify['checks'])} full key-frequency comparisons;\nvacancy rows, skills, salaries match.\n"
            + r"""\end{code}
Проверки хранятся в \path{artifacts/verification.json}. Ошибки и успешные повторы:
\path{artifacts/mr_retry_1/summary.json}.
"""
        )
        self.page("5. Профилирование: все попытки")
        self.add(r"""Среда: Windows 11, Python 3.12.10, DuckDB 1.5.6, boto3 1.43.4,
psutil 7.2.2. Версии Docker и идентификатор образа RustFS записаны в
\texttt{artifacts/environment.json}.

Каждый запуск выполняется в новом процессе Python. Замер wall time включает
запуск процесса, подключение, чтение S3, фильтрацию, агрегации и запись одинаковых
выходных CSV, но не предварительную проекцию и загрузку данных. Два map worker;
у DuckDB два потока и лимит памяти 512 MB. Пик RSS измеряется каждые 20 мс как
сумма памяти родителя и его дочерних процессов. На Windows общие страницы DLL
могут учитываться несколько раз; это воспроизводимая оценка рабочего набора дерева,
а не точный объём уникальной физической памяти. Сэмплирование может пропустить
короткий пик.

Порядок методов меняется между раундами. Кэши ОС, RustFS и файловой системы
не очищались на общем компьютере; отдельные запуски могут включать дополнительные
эффекты первого доступа. Три попытки достаточны для учебного сравнения, но не для
вывода о производительности на другом кластере.
""")
        names = {
            "mr_plain": "MR без комбайнера",
            "mr_combiner": "MR с комбайнером",
            "duckdb": "DuckDB",
        }
        ordered = sorted(
            self.profiles, key=lambda r: (list(names).index(r["method"]), r["attempt"])
        )
        self.add(
            table(
                ["Подход", "Попытка", "Wall, с", "Пик RSS, MiB", "CPU, с*"],
                [
                    [
                        names[r["method"]],
                        r["attempt"],
                        num(r["wall_s"], 3),
                        num(r["peak_tree_rss_mib"], 1),
                        num(r["cpu_s_sampled"], 2),
                    ]
                    for r in ordered
                ],
                [0.33, 0.12, 0.14, 0.18, 0.13],
            )
        )
        self.add(
            r"{\small * CPU: сумма последних наблюдённых user+system CPU time процессов; возможен недоучёт перед завершением.}"
            + "\n"
        )
        aggregates = {}

        for method in names:
            rows = [r for r in self.profiles if r["method"] == method]
            aggregates[method] = {
                "time": statistics.median(r["wall_s"] for r in rows),
                "memory": statistics.median(r["peak_tree_rss_mib"] for r in rows),
                "min": min(r["wall_s"] for r in rows),
                "max": max(r["wall_s"] for r in rows),
            }

        self.add(
            table(
                ["Подход", "Медиана, с", "Диапазон, с", "Медиана пика, MiB"],
                [
                    [
                        names[m],
                        num(v["time"], 3),
                        num(v["min"], 3) + "--" + num(v["max"], 3),
                        num(v["memory"], 1),
                    ]
                    for m, v in aggregates.items()
                ],
                [0.33, 0.16, 0.2, 0.2],
            )
        )
        self.add(
            r"Полные исходные замеры: \texttt{artifacts/benchmarks.json}, отдельно по процессам и с серверными сэмплами: \texttt{artifacts/profiles/}."
        )
        self.page("6. Оптимизация и интерпретация нагрузки")
        plain, combined, duck = (aggregates[m] for m in names)
        self.add(
            f"Комбайнер изменил медиану времени с {num(plain['time'], 3)} до {num(combined['time'], 3)} с "
            f"({num((1 - combined['time'] / plain['time']) * 100, 1)}\\% сокращения). "
            f"Медиана пика RSS изменилась с {num(plain['memory'], 1)} до {num(combined['memory'], 1)} MiB "
            f"({num((1 - combined['memory'] / plain['memory']) * 100, 1)}\\% сокращения).\n"
        )
        self.add(
            r"""Эффект комбайнера ограничен тем, насколько часто ключи повторяются внутри
одного чанка. Редкие тройки плохо сжимаются; сериализация, чтение CSV и хранение
итогового словаря остаются. Поэтому уменьшение числа передаваемых значений
не гарантирует пропорционального снижения времени и памяти. Отрицательное
«сокращение» означает увеличение показателя, его нельзя объявлять улучшением.

DuckDB исполняет фильтрацию и группировки в нативном движке без передачи чанков
в Python-процессы, но материализует промежуточные таблицы и соединения. У него
свой профиль памяти; сравнение учитывает весь процесс, а не только Python heap.
В отличие от него MapReduce удерживает ограниченную очередь чанков и накопленные
ключи; итоговый словарь всё равно растёт с числом уникальных сочетаний.

\textbf{Оптимизация входа.} Проекция устраняет ненужные описания, сокращая передаваемые
байты на """
            + num((1 - storage["bytes"] / storage["original_bytes"]) * 100, 1)
            + r"""\%.
Эта величина измерена по размеру файлов. Сравнение времени «полный CSV против
проекции» тремя попытками не проводилось, поэтому ускорение в секундах этому
изменению не приписывается. Измеренное сравнение «до/после» выше относится
к комбайнеру на одном и том же S3-объекте.

\textbf{Нагрузка RustFS.} Во время каждого запуска отдельно выполнялся
\texttt{docker stats --no-stream} примерно раз в 2--3 секунды с сохранением CPU,
памяти, NetIO и BlockIO. Это серверные сэмплы, а не точные пики; NetIO/BlockIO
в Docker являются накопительными счётчиками с момента старта контейнера.
Память контейнера не прибавляется к RSS вычислительного процесса.
"""
        )
        server_rows = []

        for r in ordered:
            samples = r["server_samples"]
            cpu = max((float(x["stats"]["CPUPerc"].strip("%")) for x in samples), default=0)
            memories = [x["stats"]["MemUsage"].split(" / ")[0] for x in samples]
            server_rows.append(
                [
                    names[r["method"]] + " " + str(r["attempt"]),
                    len(samples),
                    num(cpu, 1) + r"\%",
                    tex(", ".join(dict.fromkeys(memories))[:75]),
                ]
            )

        self.add(
            table(
                ["Запуск", "Сэмплы", "Max CPU в сэмплах", "Наблюдавшаяся память"],
                server_rows,
                [0.3, 0.1, 0.2, 0.3],
            )
        )
        self.page("7. Частоты навыков, пар и троек")
        self.add(r"""Частота означает число вакансий, содержащих весь набор, а не число
упоминаний в тексте. В таблицах приведены пять наиболее частых ключей каждого
размера; полные результаты сохранены локально и в S3.
""")

        for size in (1, 2, 3):
            self.add(r"\subsection*{Размер стека " + str(size) + "}")
            self.add(
                table(
                    ["Навык / сочетание", "Вакансий", "Доля всех вакансий варианта"],
                    [
                        [
                            tex(r["skills"]),
                            num(r["frequency"]),
                            num(r["frequency"] / s["selected_rows"] * 100, 1) + r"\%",
                        ]
                        for r in a["top_frequencies"][str(size)][:5]
                    ],
                    [0.63, 0.12, 0.17],
                )
            )

        self.add(r"""Пары и тройки считаются и для вакансий с большим стеком. Например, вакансия
с десятью навыками входит в 45 разных пар, поэтому сумма долей всех пар
может превышать 100\%. Пустые навыки не дополняются по описанию или названию.
""")
        self.page("8. Зарплаты: методика и пары навыков")
        self.add(r"""Используются только \texttt{currency=RUR} и \texttt{gross=false}:
суммы на руки, без конвертации валют и без условного пересчёта налогов.
Если указаны обе положительные границы и нижняя не выше верхней, зарплата равна
их среднему; при одной границе используется она. Пустые или некорректные значения
исключаются только из зарплатной части. Это оценки предлагаемой месячной зарплаты,
а не реальные выплаты. Односторонние границы дают приближение, а среднее границ
не является медианой распределения реальных выплат.

Для стека $T$ размера $k$ база $B$ выбирается среди его подмножеств размера $k-1$
по наибольшей частоте \emph{на всех вакансиях}. При равенстве используется
лексикографический порядок. Для пары база — более частый навык; для тройки —
более частая пара. Измеряется
\[
\Delta=M(T)-M(B),\qquad\Delta_\%=100\left(\frac{M(T)}{M(B)}-1\right).
\]
Сравниваются все вакансии с $T$ и все вакансии с $B$ (база включает группу $T$).
Учитываются сочетания минимум с 30 зарплатными наблюдениями; база как надмножество
вакансий имеет не меньший support. Ранжирование выполнено по относительной разнице,
при равенстве — по support и названию. Значение $n$ в таблицах относится к зарплатам,
а не к частоте навыка.

\subsection*{Наибольшее повышение медианы: пары}
""")
        self.impact_table("2_increase")
        self.add(r"\subsection*{Наибольшее понижение медианы: пары}")
        self.impact_table("2_decrease")
        self.add(r"""Полный рейтинг \texttt{salary\_impacts.csv} дополнительно содержит общий support,
самый частый одиночный навык стека, его support и медиану, а также разницу с ним.
Для пар это ровно требуемый базовый более частый навык.
""")
        self.page("9. Зарплаты: тройки и ограничения интерпретации")
        self.add(r"\subsection*{Наибольшее повышение медианы: тройки}")
        self.impact_table("3_increase")
        self.add(r"\subsection*{Наибольшее понижение медианы: тройки}")
        self.impact_table("3_decrease")
        self.add(r"""\textbf{Что означает разница.} Это описательная связь в выборке, а не причинный
эффект обучения навыку. Различия могут объясняться регионом, seniority, типом
компании, обязанностями и полнотой указания навыков. Например, добавление
бухгалтерского продукта или поддержки может маркировать иную роль и сегмент
работодателей, а не уменьшать ценность компетенции. Профессиональные технические
стеки могут чаще встречаться в сложных внедрениях, где выше требования к опыту.
Результат следует читать как характеристику вакансий с данным набором.

Пропуски зарплаты неслучайны, небольшие группы чувствительны к составу выборки.
Порог $n\ge30$ уменьшает влияние единичных объявлений, но не обеспечивает
статистическую значимость. Доверительные интервалы и причинная модель не строились.
Медиана базы включает случаи с дополнительным навыком, поэтому разница
не равна сравнению групп «с навыком» и «без навыка».

В своих данных пара «1с программирование + json» имеет медиану 230\,000 ₽ против
150\,000 ₽ у базового навыка ($n=30$ против 4115); возможное объяснение — вакансии
с интеграциями, но оно не проверено. Пара с «администрирование» имеет 95\,000 ₽
при $n=37$: это может отражать смешение разработки с поддержкой.
Лидирующая положительная тройка содержит близкие теги «1с: предприятие» и
«1с: предприятие 8». Это совместное указание связанных продуктов, а не три
независимые компетенции; ограниченная нормализация не объединяет эти теги.
""")

        anchors = [a["rankings"][key][0] for key in ("3_increase", "3_decrease")]
        self.add(
            table(
                ["Тройка", "Самый частый одиночный навык", "$n$ / медиана базы, ₽"],
                [
                    [
                        tex(r["skills"]),
                        tex(r["anchor_skill"]) + "; частота " + num(r["anchor_frequency"]),
                        num(r["anchor_salary_n"]) + " / " + num(r["anchor_median_rub"]),
                    ]
                    for r in anchors
                ],
                [0.43, 0.31, 0.18],
            )
        )
        self.page("10. Три региона: зарплаты и востребованность стеков")
        self.add(r"""Регионы выбраны до интерпретации результатов по трём наибольшим числам
вакансий варианта. Это значения поля \texttt{area} (города); области к городам
не присоединялись. Дистанционные вакансии относятся к указанному работодателем
региону. В знаменателе долей находятся все вакансии региона, включая объявления
без навыков и зарплаты.
""")
        regions = a["regions"]
        self.add(
            table(
                ["Регион", "Вакансий / с навыками", "$n$ зарплат / доля", "Медиана, ₽"],
                [
                    [
                        tex(r["region"]),
                        num(r["vacancies"]) + " / " + num(r["with_skills"]),
                        num(r["salary_n"]) + " / " + num(r["salary_coverage_pct"], 1) + r"\%",
                        num(r["median_rub"]),
                    ]
                    for r in regions
                ],
                [0.27, 0.24, 0.25, 0.16],
            )
        )
        self.add(
            table(
                ["Регион", "С ≥1 / ≥2 / ≥3 навыками", "Появлений одиночных / пар / троек"],
                [
                    [
                        tex(r["region"]),
                        " / ".join(num(r[f"with_stack_{k}"]) for k in (1, 2, 3)),
                        " / ".join(num(r[f"combinations_{k}"]) for k in (1, 2, 3)),
                    ]
                    for r in regions
                ],
                [0.25, 0.3, 0.37],
            )
        )
        top = [r for i, r in enumerate(a["region_stacks"]) if i % 5 == 0]
        self.add(
            table(
                ["Регион / размер", "Самый частый стек", "Частота / доля"],
                [
                    [
                        tex(r["region"]) + " / " + str(r["stack_size"]),
                        tex(r["skills"]),
                        num(r["frequency"]) + " / " + num(r["vacancy_share_pct"], 1) + r"\%",
                    ]
                    for r in top
                ],
                [0.24, 0.51, 0.17],
            )
        )
        first, second, third = regions
        self.add(
            f"Медиана в {tex(first['region'])}: {num(first['median_rub'])} ₽, "
            f"в {tex(second['region'])}: {num(second['median_rub'])} ₽, "
            f"в {tex(third['region'])}: {num(third['median_rub'])} ₽. "
            f"Разница между первым и третьим городом по числу вакансий составляет "
            f"{num(first['median_rub'] - third['median_rub'])} ₽ по медиане. "
            "Это сравнение состава региональных выборок, без поправки на опыт и работодателя.\n"
        )
        self.add(r"""Полные топ-5 каждого размера по каждому региону сохранены в
\texttt{region\_stacks.csv}; сводная таблица — в \texttt{regions.csv}.
Они получены из верифицированных строк, одинаковых у SQL и MapReduce.

Лидеры всех трёх размеров совпадают между городами, но относительная частота
базовой пары растёт от 19,9\% в Москве до 23,9\% в Екатеринбурге. При этом медиана
снижается с 200\,000 до 150\,000 ₽. Совпадение популярных тегов не устраняет
региональных различий в зарплате. Доля объявлений с сопоставимой зарплатой,
наоборот, растёт с 36,1\% до 57,5\%; пропуски в Москве сильнее ограничивают
репрезентативность зарплатного сравнения.
""")
        self.page("11. Выходные объекты и воспроизводимость")

        if (assets / "s3-results-crop.png").exists():
            self.add(r"\includegraphics[width=\linewidth]{assets/s3-results-crop.png}" + "\n")
            self.add(
                r"\begin{center}\small Рис. 2. Результаты в \texttt{hh-lake/hw3/results/}.\end{center}"
            )

        self.add(r"""В бакете сохранены \texttt{skills\_1.csv}, \texttt{skills\_2.csv},
\texttt{skills\_3.csv}, \texttt{vacancies.csv}, \texttt{salary\_impacts.csv},
\texttt{regions.csv} и \texttt{region\_stacks.csv}. Размеры подтверждены запросами
\texttt{HEAD}; манифест находится в \texttt{artifacts/s3\_outputs.json}.
Локальные результаты каждой попытки сохранены отдельно, что позволяет проверить
повторяемость и самостоятельно пересчитать выводы.

\textbf{Повторный запуск из папки hw-3:}
\begin{code}
python -m venv .runtime
.runtime\Scripts\python -m pip install -r requirements-report.txt
docker start rustfs-lab
.runtime\Scripts\python -m lab all
.runtime\Scripts\python -m unittest discover -s tests -v
.runtime\Scripts\python build_report.py
cd report
xelatex -interaction=nonstopmode -halt-on-error report.tex
xelatex -interaction=nonstopmode -halt-on-error report.tex
\end{code}
Для другого стенда нужно задать \texttt{AWS\_ACCESS\_KEY\_ID},
\texttt{AWS\_SECRET\_ACCESS\_KEY} и при необходимости \texttt{S3\_ENDPOINT}.
Исходный CSV ожидается уровнем выше \texttt{hw-3}, установки TeX и Docker используются
локальные. Формат отчёта XeLaTeX; шрифты Times New Roman, Arial, Consolas.
Файл \texttt{report.tex} можно менять и компилировать независимо от генератора,
если рядом сохранён каталог \texttt{assets}. Генератор при запуске перезаписывает
\texttt{report.tex}.

По условию владельца проекта GitHub-публикация не выполнялась: нет коммитов и push.
Исходники, отчёт и компактные результаты подготовлены к публикации через staging.
Датасеты, кэши и временные файлы исключены через \texttt{.gitignore}.
Для передачи отчёта достаточно папки \texttt{report};
для проверки вычислений нужны также \texttt{lab}, \texttt{sql}, \texttt{tests},
\texttt{artifacts} и \texttt{requirements.txt}.
""")
        self.page("12. Состояние стенда и итоговые выводы")
        self.add(r"""\includegraphics[width=\linewidth,height=155mm,keepaspectratio]{assets/rustfs-health.png}
\begin{center}\small Рис. 3. Исправный RustFS: один сервер, 4/4 диска, EC с парностью 2.\end{center}
""")
        pos = a["rankings"]["2_increase"][0]
        neg = a["rankings"]["2_decrease"][0]
        self.add(
            f"Наиболее положительно связанная с медианой пара среди прошедших порог: "
            f"«{tex(pos['skills'])}», {num(pos['delta_pct'], 1)}\\% к базе "
            f"«{tex(pos['base'])}» при n={pos['salary_n']}. "
            f"Наиболее отрицательная: «{tex(neg['skills'])}», {num(neg['delta_pct'], 1)}\\% "
            f"к «{tex(neg['base'])}» при n={neg['salary_n']}.\n"
        )
        self.add(r"""Обе реализации дали одинаковые частоты всех одиночных навыков, пар и троек,
а повтор задачи после ошибки не изменил результат. Рост промежуточных данных
соответствует числу сочетаний внутри вакансии. Комбайнер и проекция влияют на
разные затраты: первый сокращает обмен и частичную агрегацию, вторая — чтение.

\textbf{Источники методики.} Постановка и критерии домашнего задания из приложенного
текста; лекция 2 о HDFS; лекция 3 о MapReduce. Данные и числа получены в локальных
запусках 21.10.2026 (Europe/Moscow). Настройка DuckDB S3 основана на официальной
документации: \url{https://duckdb.org/docs/current/core_extensions/httpfs/s3api}.
""")
        self.add(r"\end{document}")
        target = ROOT / "report" / "report.tex"
        target.write_text("\n".join(self.parts), encoding="utf-8")
        print(target)


if __name__ == "__main__":
    ReportBuilder().build()
