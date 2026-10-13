#!/usr/bin/env python3
"""Линтер документации проекта по правилам скилла project-docs.

Запуск:  python3 doc_lint.py <корень проекта или папка docs> [--days N] [--only CODE,CODE]
                              [--summary] [--quiet]

Проверяет форму, не смысл. Ошибки (E) дают код выхода 1, предупреждения (W) - нет.

  E DASH      длинное или среднее тире вместо дефиса
  E LABEL     метка вне общего набора и вне таблицы «Местные метки» в CONVENTIONS.md
  E LABELDATE метка, которой нужна дата, без даты ([ОТВЕТ], [РЕШЕНИЕ], [СЛОВА] ...)
  E LINK      ссылка на файл .md, которого нет (в журнале, changelog/ и notes/ - W)
  E SECTION   ссылка `FILE.md §3.2` на раздел, которого в файле нет (без файла - W)
  E BUDGET    превышен бюджет строк файла раскладки или записи журнала (прочие файлы - W)
  E STATE     раздел «Состояние на <дату>» вне журнала - состояние ведётся не там
  E MISSING   нет обязательного файла раскладки
  W RELDATE   относительная дата («вчера», «на прошлой неделе»); цитаты и [СЛОВА] не считаются
  W HEADING   заголовок записи журнала не по формату «## ДД.ММ.ГГГГ - ...»
  W ORDER     записи журнала не по убыванию дат
  W WHERE     запись журнала без блока «Где мы»
  W STALE     у потока нет абзаца «Где мы» свежее N дней (по умолчанию 7)
  W ROTATE    в журнале есть записи прошлых месяцев - пора ротировать в changelog/
  W SECRET    похоже на почту, токен или ключ
  W DUPSEC    повтор номера раздела
  W NONUM     раздел без номера в файле раскладки

Внутри блоков кода (```) ничего не проверяется. В docs/changelog/ и docs/notes/ - только LINK
и SECRET. Каталоги из таблицы «Вне раскладки» в CONVENTIONS.md пропускаются целиком. Ссылки
вне docs/ пишутся с префиксом из таблицы «Внешние корни» там же; корня нет на машине - пропуск.

Только стандартная библиотека, работает на macOS, Linux и Windows.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

LABELS = {
    "ФАКТ", "ВЫВОД", "СЛОВА", "ДООПРОС", "ОТВЕТ", "РЕШЕНИЕ", "ОТВЕРГНУТО", "ОТЛОЖЕНО",
    "ИСПРАВЛЕНО", "ВАЖНО", "ПРАВИЛО", "СОСТОЯНИЕ",
}
DATED = {"СЛОВА", "ОТВЕТ", "РЕШЕНИЕ", "ОТВЕРГНУТО", "ОТЛОЖЕНО", "ИСПРАВЛЕНО", "СОСТОЯНИЕ"}

# Бюджеты непустых строк. Ключ - путь относительно docs/ или шаблон с *.
BUDGETS = {
    "CONTEXT.md": 800, "TASKS.md": 500, "CHANGELOG.md": 2000, "CONVENTIONS.md": 400,
    "projects/*/CONTEXT.md": 600, "projects/*/TASKS.md": 400,
}
CLAUDE_MD_BUDGET = 80
DEFAULT_BUDGET = 500
ENTRY_BUDGET = 40
REQUIRED = ["CONTEXT.md", "CHANGELOG.md", "TASKS.md", "CONVENTIONS.md"]
IMMUTABLE_DIRS = {"changelog", "notes"}

RE_DASH = re.compile("[" + chr(0x2014) + chr(0x2013) + "]")
RE_RELDATE = re.compile(
    r"(?<![\w-])(вчера|позавчера|сегодня|завтра|послезавтра|на прошлой неделе|на этой неделе|"
    r"на следующей неделе|в прошлом месяце|в этом месяце|на днях)(?![\w-])", re.IGNORECASE)
RE_QUOTE = re.compile("[" + chr(0xAB) + "][^" + chr(0xBB) + "]*[" + chr(0xBB) + "]|\"[^\"]*\"")
RE_LABEL = re.compile(r"\[([А-ЯЁ]+(?: [А-ЯЁ]+)*)(?:[ ,]+([^\]]*))?\](?!\()")
RE_DATE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
RE_LINK_TICK = re.compile(r"`([^`\s]+?\.md)(?: §[^`]*)?`")
RE_LINK_MD = re.compile(r"\]\(([^)\s]+?\.md)(?:#[^)]*)?\)")
RE_SECTION_FILE = re.compile(r"([\w./~-]+\.md)`? §(\d+(?:\.\d+)*)")
RE_SECTION_BARE = re.compile(r"(?<![\w./-])§(\d+(?:\.\d+)*)")
RE_HEADING_NUM = re.compile(r"^#{1,6}\s+(\d+(?:\.\d+)*)\.?(?:\s|$)")
RE_STATE_HEADING = re.compile(r"^#{2,4} .*Состояние на \d{2}\.\d{2}\.\d{4}", re.IGNORECASE)
RE_ENTRY = re.compile(r"^## (\d{2})\.(\d{2})\.(\d{4})(?: \([^)]*\))? - \S")
RE_WHERE = re.compile(r"^\*\*Где мы\*\*")
RE_SECRET = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+|glpat-[\w-]{10,}|sk-[A-Za-z0-9_-]{16,}|xox[abp]-[\w-]+|"
    r"AKIA[0-9A-Z]{16}|\b[0-9a-f]{40,}\b|Bearer \S{10,}")
RE_TABLE_ROW = re.compile(r"^\|[^|`]*`([^`]+)`[^|]*\|")  # первая ячейка содержит хотя бы один `...`


class Report:
    def __init__(self, root, only):
        self.root, self.only, self.items = root, only, []

    def add(self, level, code, path, line, msg):
        if self.only and code not in self.only:
            return
        rel = path.relative_to(self.root).as_posix() if path is not None else "-"
        self.items.append((level, code, rel, line, msg))

    def errors(self):
        return sum(1 for i in self.items if i[0] == "E")

    def dump(self, quiet):
        counts = {}
        for level, code, rel, line, msg in self.items:
            counts[(level, code)] = counts.get((level, code), 0) + 1
            if not quiet:
                where = f"{rel}:{line}" if line else rel
                print(f"{where}: {level} [{code}] {msg}")
        if self.items:
            parts = ", ".join(f"{c} {n}{'' if l == 'E' else ' (W)'}" for (l, c), n in sorted(counts.items()))
            print(f"\nошибок: {self.errors()}, предупреждений: {len(self.items) - self.errors()} ({parts})")
        else:
            print("находок нет")


def read_lines(path):
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def strip_code(lines):
    out, inside = [], False
    for line in lines:
        if line.strip().startswith("```"):
            inside = not inside
            out.append("")
            continue
        out.append("" if inside else line)
    return out


def conventions_tables(docs):
    """Три таблицы из CONVENTIONS.md: местные метки, каталоги вне раскладки, внешние корни."""
    labels, skip_dirs, ext_roots = set(), [], []
    conv = docs / "CONVENTIONS.md"
    if not conv.exists():
        return labels, skip_dirs, ext_roots
    current = None
    for line in read_lines(conv):
        low = line.lower()
        if "местные метки" in low:
            current = "labels"
        elif "вне раскладки" in low:
            current = "skip"
        elif "внешние корни" in low:
            current = "roots"
        elif line.startswith("#"):
            current = None
        m = RE_TABLE_ROW.match(line)
        if not m or current is None:
            continue
        first_cell = line.split("|")[1]
        cell = m.group(1).strip()
        if current == "labels":
            for lm in re.finditer(r"\[([А-ЯЁ]+(?: [А-ЯЁ]+)*)", first_cell):
                labels.add(lm.group(1))
        elif current == "skip":
            skip_dirs.append(cell.strip("/"))
        elif current == "roots":
            ext_roots.append(cell)
    return labels, skip_dirs, ext_roots


def budget_for(rel):
    if rel in BUDGETS:
        return BUDGETS[rel], "E"
    for pattern, limit in BUDGETS.items():
        if "*" in pattern:
            head, tail = pattern.split("*")
            if rel.startswith(head) and rel.endswith(tail) and rel.count("/") == pattern.count("/"):
                return limit, "E"
    return DEFAULT_BUDGET, "W"


class Linter:
    def __init__(self, root, docs, rep, max_days):
        self.root, self.docs, self.rep, self.max_days = root, docs, rep, max_days
        self.local_labels, skip, roots = conventions_tables(docs)
        self.allowed = LABELS | self.local_labels
        # пути в таблице - от корня проекта (docs/confluence/) или от docs/ (confluence/)
        self.skip_dirs = [(root / s) if (root / s).exists() else (docs / s) for s in skip]
        self.ext_roots = []  # (как записан в таблице, куда ведёт на диске)
        for r in roots:
            p = Path(r).expanduser()
            if not p.is_absolute():
                p = root / p
            self.ext_roots.append((r, p))
        self.headings = {}  # path -> set of section numbers
        self.streams = sorted(p.name for p in (docs / "projects").iterdir() if p.is_dir()) \
            if (docs / "projects").is_dir() else []
        self.streams.append("общее")

    # -- файлы --------------------------------------------------------------

    def skipped(self, path):
        return any(d == path or d in path.parents for d in self.skip_dirs)

    def immutable(self, path):
        rel = path.relative_to(self.docs).parts if self.docs in path.parents else ()
        return bool(rel) and rel[0] in IMMUTABLE_DIRS

    def section_numbers(self, path):
        if path not in self.headings:
            nums = set()
            for line in strip_code(read_lines(path)):
                m = RE_HEADING_NUM.match(line)
                if m:
                    nums.add(m.group(1))
            self.headings[path] = nums
        return self.headings[path]

    def resolve(self, path, target):
        """Файл по ссылке: от текущего файла, от docs/, от корня. Ссылка, начинающаяся с
        внешнего корня из CONVENTIONS.md, проверяется на диске; корня на машине нет -
        возвращается False (пропуск). None - файла нет."""
        for raw, root in self.ext_roots:
            if target.startswith(raw.rstrip("/") + "/") or target == raw.rstrip("/"):
                if not root.exists():
                    return False
                full = root / target[len(raw.rstrip("/")) + 1:] if target != raw.rstrip("/") else root
                return full if full.exists() else None
        if target.startswith("~"):
            full = Path(target).expanduser()
            return full if full.exists() else None
        for c in (path.parent / target, self.docs / target, self.root / target):
            if c.exists():
                return c
        return None

    def check_file(self, path):
        raw = read_lines(path)
        lines = strip_code(raw)
        is_claude = path.name == "CLAUDE.md" and path.parent == self.root
        rel = path.relative_to(self.docs).as_posix() if self.docs in path.parents else path.name
        immutable = self.immutable(path)
        in_layout = is_claude or rel in BUDGETS or budget_for(rel)[1] == "E"
        rep = self.rep

        if not immutable:
            nonblank = sum(1 for l in raw if l.strip())
            limit, level = (CLAUDE_MD_BUDGET, "E") if is_claude else budget_for(rel)
            if nonblank > limit:
                rep.add(level, "BUDGET", path, 0, f"{nonblank} непустых строк при бюджете {limit}")

        seen_nums = {}
        for i, line in enumerate(lines, 1):
            for m in RE_SECRET.finditer(line):
                rep.add("W", "SECRET", path, i, f"похоже на почту или ключ: «{m.group(0)[:30]}»")
            self.check_links(path, i, line)
            if immutable:
                continue
            if RE_DASH.search(line):
                rep.add("E", "DASH", path, i, "длинное тире, нужен дефис «-»")
            if "[СЛОВА" not in line:
                m = RE_RELDATE.search(RE_QUOTE.sub("", line))
                if m:
                    rep.add("W", "RELDATE", path, i, f"относительная дата «{m.group(1)}»")
            if RE_STATE_HEADING.match(line) and path.name != "CHANGELOG.md":
                rep.add("E", "STATE", path, i, "раздел «Состояние на дату» - место этому в блоке «Где мы» журнала")
            labels = list(RE_LABEL.finditer(line))
            legend = len(labels) >= 4  # перечень меток в правилах, дата там не нужна
            for m in labels:
                name, tail = m.group(1), m.group(2) or ""
                if name not in self.allowed:
                    rep.add("E", "LABEL", path, i, f"метка [{name}] вне набора и вне CONVENTIONS.md")
                elif name in DATED and not legend and not RE_DATE.search(tail) and "<" not in tail:
                    rep.add("E", "LABELDATE", path, i, f"метке [{name}] нужна дата ДД.ММ.ГГГГ")
            if in_layout and path.name != "CHANGELOG.md" and not is_claude and line.startswith("#"):
                m = RE_HEADING_NUM.match(line)
                if m:
                    if m.group(1) in seen_nums:
                        rep.add("W", "DUPSEC", path, i, f"раздел §{m.group(1)} уже был в строке {seen_nums[m.group(1)]}")
                    seen_nums[m.group(1)] = i
                elif line.startswith("## ") or line.startswith("### "):
                    rep.add("W", "NONUM", path, i, "раздел без номера")

        if path.name == "CHANGELOG.md" and path.parent == self.docs:
            self.check_changelog(path, raw)

    def check_links(self, path, i, line):
        rep = self.rep
        # журнал не правится: битая ссылка в старой записи - предупреждение, не ошибка
        lvl = "W" if self.immutable(path) or path.name == "CHANGELOG.md" else "E"
        targets = [m.group(1) for m in RE_LINK_TICK.finditer(line)]
        targets += [m.group(1) for m in RE_LINK_MD.finditer(line)]
        for target in targets:
            if "://" in target or "<" in target or "*" in target or "{" in target:
                continue
            found = self.resolve(path, target)
            if found is None:
                rep.add(lvl, "LINK", path, i, f"нет файла `{target}`")
        for m in RE_SECTION_FILE.finditer(line):
            target, num = m.group(1), m.group(2)
            if "<" in target or "*" in target:
                continue
            found = self.resolve(path, target)
            if not found:
                continue  # LINK уже сказал, или внешний корень вне машины
            if num not in self.section_numbers(found):
                rep.add(lvl, "SECTION", path, i, f"в `{target}` нет раздела §{num}")
        bare_line = RE_SECTION_FILE.sub("", line)
        if path.name != "CHANGELOG.md" and not self.immutable(path):
            for m in RE_SECTION_BARE.finditer(bare_line):
                if m.group(1) not in self.section_numbers(path):
                    rep.add("W", "SECTION", path, i, f"§{m.group(1)} - в этом файле такого раздела нет; если это другой файл, назвать его")

    # -- журнал --------------------------------------------------------------

    def check_changelog(self, path, raw):
        rep = self.rep
        starts = [i for i, line in enumerate(raw) if line.startswith("## ")]
        today = dt.date.today()
        prev_date, old_entries, oldest = None, 0, None
        latest = {s: None for s in self.streams}
        for n, start in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(raw)
            body = raw[start:end]
            m = RE_ENTRY.match(raw[start])
            date = None
            if not m:
                rep.add("W", "HEADING", path, start + 1, "заголовок не по формату «## ДД.ММ.ГГГГ - что»")
                dm = RE_DATE.search(raw[start])
                if dm:
                    m = dm
            if m:
                try:
                    date = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                except ValueError:
                    rep.add("W", "HEADING", path, start + 1, "дата в заголовке не разбирается")
            if date:
                if prev_date and date > prev_date:
                    rep.add("W", "ORDER", path, start + 1, f"запись {date:%d.%m.%Y} стоит ниже записи {prev_date:%d.%m.%Y}")
                prev_date = date
                if (date.year, date.month) < (today.year, today.month):
                    old_entries += 1
                    oldest = date if oldest is None or date < oldest else oldest
            nonblank = [l for l in body if l.strip()]
            if len(nonblank) > ENTRY_BUDGET:
                rep.add("E", "BUDGET", path, start + 1, f"запись {len(nonblank)} строк при бюджете {ENTRY_BUDGET}")
            if len(nonblank) > 1 and not any(RE_WHERE.match(l) for l in body):
                rep.add("W", "WHERE", path, start + 1, "запись без блока «Где мы»")
            for l in body:
                for s in self.streams:
                    if latest[s] is None and l.startswith(f"- **{s}.**"):
                        latest[s] = date
        if old_entries:
            rep.add("W", "ROTATE", path, 0, f"{old_entries} записей прошлых месяцев (старейшая {oldest:%d.%m.%Y}) - ротировать в changelog/")
        for s, d in latest.items():
            if d is None:
                rep.add("W", "STALE", path, 0, f"поток «{s}»: нет ни одного абзаца «Где мы»")
            elif (today - d).days > self.max_days:
                rep.add("W", "STALE", path, 0, f"поток «{s}»: последнее «Где мы» {d:%d.%m.%Y}, {(today - d).days} дн. назад")

    # -- обход ---------------------------------------------------------------

    def run(self):
        rep = self.rep
        for name in REQUIRED:
            if not (self.docs / name).exists():
                rep.add("E", "MISSING", self.docs / name, 0, "обязательного файла раскладки нет")
        if not (self.root / "CLAUDE.md").exists():
            rep.add("E", "MISSING", self.root / "CLAUDE.md", 0, "нет точки входа")
        files = sorted(p for p in self.docs.rglob("*.md") if "ARCHIVE" not in p.parts and not self.skipped(p))
        if (self.root / "CLAUDE.md").exists():
            files.insert(0, self.root / "CLAUDE.md")
        for path in files:
            self.check_file(path)
        return files

    def summary(self, files):
        print("\nфайл | непустых строк | бюджет | E | W")
        for path in files:
            rel = path.relative_to(self.root).as_posix()
            nonblank = sum(1 for l in read_lines(path) if l.strip())
            drel = path.relative_to(self.docs).as_posix() if self.docs in path.parents else path.name
            if self.immutable(path):
                budget = "-"
            elif path.name == "CLAUDE.md" and path.parent == self.root:
                budget = CLAUDE_MD_BUDGET
            else:
                budget = budget_for(drel)[0]
            e = sum(1 for i in self.rep.items if i[2] == rel and i[0] == "E")
            w = sum(1 for i in self.rep.items if i[2] == rel and i[0] == "W")
            flag = " !" if budget != "-" and nonblank > budget else ""
            print(f"{rel} | {nonblank} | {budget}{flag} | {e} | {w}")


def main():
    ap = argparse.ArgumentParser(description="Линтер документации проекта")
    ap.add_argument("path", help="корень проекта или папка docs")
    ap.add_argument("--days", type=int, default=7, help="допустимый возраст «Где мы» потока в днях")
    ap.add_argument("--only", help="показывать только эти коды, через запятую")
    ap.add_argument("--summary", action="store_true", help="таблица по файлам в конце")
    ap.add_argument("--quiet", action="store_true", help="только сводка")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    given = Path(args.path).expanduser().resolve()
    if given.name == "docs" and given.is_dir():
        docs, root = given, given.parent
    elif (given / "docs").is_dir():
        docs, root = given / "docs", given
    else:
        print(f"не нашёл папку docs в {given}")
        return 2

    only = set(args.only.split(",")) if args.only else None
    rep = Report(root, only)
    linter = Linter(root, docs, rep, args.days)
    files = linter.run()
    rep.dump(args.quiet)
    if args.summary:
        linter.summary(files)
    return 1 if rep.errors() else 0


if __name__ == "__main__":
    sys.exit(main())
