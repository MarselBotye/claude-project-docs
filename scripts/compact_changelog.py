#!/usr/bin/env python3
"""Сжатие журнала: ротация прошлых месяцев и вынос длинных записей в notes/.

Запуск:  python3 compact_changelog.py <корень проекта> [--keep-months 1] [--budget 40] [--apply | --rules]

Без --apply только печатает план. С --apply:
  1. Записи месяцев старше текущего (при --keep-months 1) переезжают как есть в
     docs/changelog/<ГГГГ>-<ММ>.md, в том же порядке, с шапкой «перенесено, не правится».
  2. Оставшиеся записи длиннее бюджета непустых строк: тело целиком в
     docs/notes/<ГГГГ-ММ-ДД>-<тема>.md, в журнале остаётся выжимка - строки оригинала дословно:
     сначала блоки с [РЕШЕНИЕ] [ОТВЕРГНУТО] [ИСПРАВЛЕНО] [ПРАВИЛО], потом [ВАЖНО], потом факты с
     номерами МР, плюс «Повод», блок «Где мы» и ссылка на notes/. Новых формулировок нет.
  3. В шапку CHANGELOG.md добавляется строка «Записи старше ... - в changelog/».
Дата записи - из заголовка «## ДД.ММ.ГГГГ ...»; если не разбирается - дата записи выше.
Перед --apply сделать копию: archive_copy.py. Только стандартная библиотека.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

RE_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
PRIORITY = [("[РЕШЕНИЕ", 1), ("[ОТВЕРГНУТО", 1), ("[ИСПРАВЛЕНО", 1), ("[ПРАВИЛО", 1),
            ("[ВАЖНО", 2), ("МР ", 3), ("[ФАКТ]", 3)]
MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь",
          "октябрь", "ноябрь", "декабрь"]
TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
                     "r", "s", "t", "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def slug(text, words=4):
    out = []
    for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text):
        s = "".join(TRANSLIT.get(ch, ch) for ch in w.lower())
        if s:
            out.append(s)
        if len(out) == words:
            break
    return "-".join(out) or "zapis"


def parse(lines):
    starts = [i for i, l in enumerate(lines) if l.startswith("## ")]
    header = lines[:starts[0]] if starts else lines
    entries, prev = [], None
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else len(lines)
        m = RE_DATE.search(lines[s])
        date = None
        if m:
            try:
                date = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                date = None
        if date is None:
            date = prev
        prev = date
        entries.append({"heading": lines[s], "body": lines[s + 1:e], "date": date})
    return header, entries


def blocks(body):
    """Тело записи как список блоков: буллет с продолжениями, абзац, блок «Где мы»."""
    out, cur = [], []
    for line in body:
        if line.startswith("- ") or line.startswith("**") or line.startswith("#") or (not line.strip() and cur):
            if cur:
                out.append(cur)
            cur = [line] if line.strip() else []
        else:
            cur.append(line)
    if cur:
        out.append(cur)
    return out


def summarize(body, budget):
    bl = blocks(body)
    keep, rest = [], []
    where = None
    for b in bl:
        text = "\n".join(b)
        if b[0].startswith("**Где мы**"):
            where = b
            continue
        if b[0].startswith("**Повод"):
            keep.append((0, b))
            continue
        if b[0].startswith("#"):
            continue  # подзаголовок внутри записи без своих строк - сирота, в выжимку не идёт
        pr = min((p for key, p in PRIORITY if key in text), default=9)
        rest.append((pr, b))
    rest.sort(key=lambda x: x[0])
    chosen = keep[:]
    used = sum(len([l for l in b if l.strip()]) for _, b in chosen)
    reserve = 2 + (len([l for l in where if l.strip()]) if where else 0)
    for pr, b in rest:
        n = len([l for l in b if l.strip()])
        if pr == 9 and chosen:
            break
        if used + n + reserve > budget:
            continue
        chosen.append((pr, b))
        used += n
    if not any(pr != 0 for pr, _ in chosen) and rest:
        chosen.append(rest[0])
    return [b for _, b in chosen], where


def main():
    ap = argparse.ArgumentParser(description="Сжатие журнала")
    ap.add_argument("root")
    ap.add_argument("--keep-months", type=int, default=1, help="сколько последних месяцев оставить в CHANGELOG.md")
    ap.add_argument("--budget", type=int, default=40)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rules", action="store_true",
                    help="только напечатать строки с [ПРАВИЛО] [РЕШЕНИЕ] [ОТВЕРГНУТО] [ВАЖНО] из записей, которые уйдут в changelog/ - кандидаты в CONTEXT.md §«Чего не умеет и что не сработало»")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    root = Path(args.root).resolve()
    docs = root / "docs"
    path = docs / "CHANGELOG.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    header, entries = parse(lines)
    today = dt.date.today()
    ym = today.year * 12 + today.month - 1
    cutoff = ym - args.keep_months + 1  # месяцы < cutoff ротируются

    rotate, keep = {}, []
    for e in entries:
        d = e["date"]
        if d and d.year * 12 + d.month - 1 < cutoff:
            rotate.setdefault(f"{d.year}-{d.month:02d}", []).append(e)
        else:
            keep.append(e)

    if args.rules:
        for month, es in sorted(rotate.items()):
            for e in es:
                d = e["date"].strftime("%d.%m.%Y") if e["date"] else "?"
                for l in e["body"]:
                    if any(k in l for k in ("[ПРАВИЛО", "[РЕШЕНИЕ", "[ОТВЕРГНУТО", "[ВАЖНО")):
                        print(f"- {d}: {l.strip().lstrip('- ').strip()} (`changelog/{month}.md`)")
        return 0

    plan, notes_out, new_keep = [], [], []
    used_names = set()
    for e in keep:
        nonblank = [l for l in e["body"] if l.strip()]
        if len(nonblank) <= args.budget:
            new_keep.append(e)
            continue
        d = e["date"] or today
        title = e["heading"][3:].split(" - ", 1)[-1]
        name = f"{d.isoformat()}-{slug(title)}"
        k = 2
        while name in used_names or (docs / "notes" / f"{name}.md").exists():
            name = f"{d.isoformat()}-{slug(title)}-{k}"
            k += 1
        used_names.add(name)
        chosen, where = summarize(e["body"], args.budget)
        body = []
        for b in chosen:
            body += b + [""]
        body.append(f"- Запись целиком: `notes/{name}.md` (вынесена при сжатии {today:%d.%m.%Y}).")
        body.append("")
        if where:
            body += where + [""]
        new_keep.append({"heading": e["heading"], "body": body, "date": e["date"]})
        notes_out.append((name, e))
        plan.append((e["date"], e["heading"][3:63], len(nonblank), f"выжимка {len([l for l in body if l.strip()])} + notes/{name}.md"))

    print("| Дата | Запись | Строк | Действие |\n|---|---|---|---|")
    for month, es in sorted(rotate.items()):
        n = sum(len([l for l in e['body'] if l.strip()]) + 1 for e in es)
        print(f"| {month} | {len(es)} записей | {n} | ротация в changelog/{month}.md |")
    for d, h, n, act in plan:
        print(f"| {d:%d.%m.%Y} | {h} | {n} | {act} |")
    total_before = len([l for l in lines if l.strip()])
    total_after = len([l for l in header if l.strip()]) + sum(1 + len([l for l in e['body'] if l.strip()]) for e in new_keep)
    print(f"\nCHANGELOG.md: было {total_before} непустых строк, станет {total_after}; "
          f"ротировано записей {sum(len(v) for v in rotate.values())}, вынесено в notes/ {len(notes_out)}")
    if not args.apply:
        print("план; записать - --apply (сначала archive_copy.py)")
        return 0

    (docs / "changelog").mkdir(exist_ok=True)
    for month, es in sorted(rotate.items()):
        y, m = month.split("-")
        f = docs / "changelog" / f"{month}.md"
        chunk = []
        if not f.exists():
            chunk += [f"# Журнал за {MONTHS[int(m) - 1]} {y}", "",
                      f"Перенесено {today:%d.%m.%Y} из `CHANGELOG.md` при сжатии, записи в исходном порядке, не правится.", "", "---", ""]
        else:
            chunk += ["", "---", f"<!-- добавлено при сжатии {today:%d.%m.%Y} -->", ""]
        for e in es:
            chunk += [e["heading"]] + e["body"]
        with open(f, "a", encoding="utf-8") as fh:
            fh.write("\n".join(chunk).rstrip("\n") + "\n")
    if notes_out:
        (docs / "notes").mkdir(exist_ok=True)
        for name, e in notes_out:
            f = docs / "notes" / f"{name}.md"
            text = [f"# {e['heading'][3:]}", "",
                    f"Запись журнала целиком, вынесена из `CHANGELOG.md` при сжатии {today:%d.%m.%Y}. Выжимка - в журнале за эту дату. Не правится.", "", "---", ""] + e["body"]
            f.write_text("\n".join(text).rstrip("\n") + "\n", encoding="utf-8")
    note_line = f"Записи прошлых месяцев - в `changelog/` (по файлу на месяц). Длинные записи целиком - в `notes/`."
    if rotate and not any(note_line in l for l in header):
        sep = max((i for i, l in enumerate(header) if l.strip() == "---"), default=len(header) - 1)
        header = header[:sep] + [note_line, ""] + header[sep:]
    out = header[:]
    for e in new_keep:
        out += [e["heading"]] + e["body"]
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    print("записано")
    return 0


if __name__ == "__main__":
    sys.exit(main())
