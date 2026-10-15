#!/usr/bin/env python3
"""Сверка переноса при сжатии: ничего не потеряно, перенесено дословно, правки - где заявлено.

Запуск:  python3 verify_moves.py <копия из архива> <живой файл> [--to <файл> ...]
                                 [--sections 7.6 9.1 ...] [--show N]

Сравниваются непустые строки без хвостовых пробелов; линии-разделители (---) не считаются.

  1. ПОТЕРЯНО. Каждая строка копии, которой в живом файле больше нет (с учётом повторов), должна
     дословно быть в одном из файлов --to (notes/, howto/, changelog/, журнал). Нет нигде -
     ошибка, с номером строки копии.
  2. Файлы --to. Сколько строк файла - дословные куски копии (с границами строк копии) и сколько
     своих. Шапка до первого совпадения (заголовок, «перенесено из …») - своя, это нормально.
     Свои строки внутри тела печатаются: это пересказ вместо переноса, разобраться.
  3. --sections. Изменения в копии и вставки в живом файле вне перечисленных разделов - ошибка
     (§7.6 покрывает §7.6.1). Без --sections проверка не делается.

В конце - sha256 живого файла для строки «файлы свободны» в отчёте этапа.
Код выхода 1 при потерянных строках или правках вне заявленных разделов. Только стандартная
библиотека.
"""

import argparse
import difflib
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

RE_HEADING_NUM = re.compile(r"^#{1,6}\s+(\d+(?:\.\d+)*)\.?(?:\s|$)")
RE_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def read(path):
    return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()


def nonblank(lines):
    """[(номер строки в файле, текст без хвостовых пробелов)] без пустых и линий-разделителей."""
    return [(i, l.rstrip()) for i, l in enumerate(lines, 1) if l.strip() and not RE_HR.match(l)]


def sections(lines):
    """Номер раздела для каждой строки файла (по последнему нумерованному заголовку)."""
    cur, out = None, []
    for l in lines:
        m = RE_HEADING_NUM.match(l)
        if m:
            cur = m.group(1)
        out.append(cur)
    return out


def covered(sec, declared):
    return sec is not None and any(sec == d or sec.startswith(d + ".") for d in declared)


def chunks(target, copy):
    """Жадно: строки target как куски подряд идущих строк копии и свои строки.
    Возвращает список (вид, начало_в_target, конец_в_target, начало_в_copy, конец_в_copy)."""
    index = {}
    for j, (_, t) in enumerate(copy):
        index.setdefault(t, []).append(j)
    out, i, n = [], 0, len(target)
    while i < n:
        best = None
        for j in index.get(target[i][1], []):
            k = 0
            while i + k < n and j + k < len(copy) and target[i + k][1] == copy[j + k][1]:
                k += 1
            if best is None or k > best[1]:
                best = (j, k)
        if best:
            j, k = best
            out.append(("copy", i, i + k, j, j + k))
            i += k
        else:
            if out and out[-1][0] == "own":
                out[-1] = ("own", out[-1][1], i + 1, None, None)
            else:
                out.append(("own", i, i + 1, None, None))
            i += 1
    return out


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv):
    ap = argparse.ArgumentParser(description="Сверка переноса текста при сжатии документации")
    ap.add_argument("copy", help="копия из архива (до правки)")
    ap.add_argument("live", help="живой файл (после правки)")
    ap.add_argument("--to", nargs="*", default=[], help="файлы, куда переехал текст")
    ap.add_argument("--sections", nargs="*", default=None, help="разделы, которые правили: 7.6 9.1")
    ap.add_argument("--show", type=int, default=30, help="сколько строк печатать в каждом списке")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    bad = 0
    copy_raw, live_raw = read(args.copy), read(args.live)
    copy_nb, live_nb = nonblank(copy_raw), nonblank(live_raw)
    targets = {f: nonblank(read(f)) for f in args.to}

    # 1. ушедшие из живого файла строки и где они теперь
    live_count = Counter(t for _, t in live_nb)
    seen, gone = Counter(), []
    for i, t in copy_nb:
        seen[t] += 1
        if seen[t] > live_count[t]:
            gone.append((i, t))
    to_count = Counter(t for nb in targets.values() for _, t in nb)
    seen, lost = Counter(), []
    for i, t in gone:
        seen[t] += 1
        if seen[t] > to_count[t]:
            lost.append((i, t))
    print(f"копия {len(copy_nb)} строк, живой файл {len(live_nb)}; ушло {len(gone)}, "
          f"найдено в --to {len(gone) - len(lost)}, ПОТЕРЯНО {len(lost)}")
    for i, t in lost[: args.show]:
        print(f"  ПОТЕРЯНО  копия:{i}  {t[:100]}")
    if len(lost) > args.show:
        print(f"  … ещё {len(lost) - args.show}")
    bad += bool(lost)

    # 2. файлы-приёмники: куски копии и свои строки
    for f, nb in targets.items():
        parts = chunks(nb, copy_nb)
        copied = [p for p in parts if p[0] == "copy"]
        first_copy = parts.index(copied[0]) if copied else len(parts)
        header = sum(p[2] - p[1] for p in parts[:first_copy])
        own = [p for p in parts[first_copy:] if p[0] == "own"]
        own_lines = sum(p[2] - p[1] for p in own)
        ranges = ", ".join(f"{copy_nb[p[3]][0]}-{copy_nb[p[4] - 1][0]}" for p in copied)
        print(f"{f}: из копии {sum(p[2] - p[1] for p in copied)} строк в {len(copied)} кусках "
              f"(строки копии {ranges or '-'}); шапка {header}; своих в теле {own_lines}")
        shown = 0
        for p in own:
            for k in range(p[1], p[2]):
                if shown >= args.show:
                    break
                print(f"  СВОЯ  {f}:{nb[k][0]}  {nb[k][1][:100]}")
                shown += 1

    # 3. правки вне заявленных разделов
    if args.sections is not None:
        declared = [s.strip("§ ") for s in args.sections]
        csec, lsec = sections(copy_raw), sections(live_raw)
        outside = []
        sm = difflib.SequenceMatcher(None, [t for _, t in copy_nb], [t for _, t in live_nb], autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op in ("delete", "replace"):
                for k in range(i1, i2):
                    ln = copy_nb[k][0]
                    if not covered(csec[ln - 1], declared):
                        outside.append((f"копия:{ln}", csec[ln - 1], copy_nb[k][1]))
            if op in ("insert", "replace"):
                for k in range(j1, j2):
                    ln = live_nb[k][0]
                    if not covered(lsec[ln - 1], declared):
                        outside.append((f"живой:{ln}", lsec[ln - 1], live_nb[k][1]))
        print(f"правок вне разделов {' '.join('§' + d for d in declared)}: {len(outside)}")
        for where, sec, t in outside[: args.show]:
            print(f"  ВНЕ  {where} (§{sec})  {t[:100]}")
        if len(outside) > args.show:
            print(f"  … ещё {len(outside) - args.show}")
        bad += bool(outside)

    print(f"sha256 {args.live}: {digest(args.live)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
