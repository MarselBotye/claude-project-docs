#!/usr/bin/env python3
"""Копия файлов в ARCHIVE/<сегодня>/ перед сжатием, со сверкой sha256.

Запуск:  python3 archive_copy.py <корень проекта> <файл относительно корня> [...]

Копия ложится в ARCHIVE/<ГГГГ-ММ-ДД>/<путь с подчёркиваниями вместо разделителей>:
docs/CHANGELOG.md -> ARCHIVE/2026-10-13/docs_CHANGELOG.md. Если копия уже есть - отказ: она
могла быть снята до правки, и повторная копия затёрла бы оригинал. После копирования сверка
sha256 и заготовка строк описи для ARCHIVE/README.md. Код выхода 1 при любой ошибке.
Только стандартная библиотека.
"""

import datetime as dt
import hashlib
import shutil
import sys
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = Path(argv[0]).resolve()
    day = dt.date.today().isoformat()
    target_dir = root / "ARCHIVE" / day
    bad = 0
    rows = []
    for rel in argv[1:]:
        src = (root / rel).resolve()
        if not src.is_file():
            print(f"НЕТ ФАЙЛА  {rel}")
            bad += 1
            continue
        try:
            rel_posix = src.relative_to(root).as_posix()
        except ValueError:
            print(f"ВНЕ КОРНЯ  {rel}")
            bad += 1
            continue
        dst = target_dir / rel_posix.replace("/", "_")
        if dst.exists():
            print(f"УЖЕ ЕСТЬ   {dst.relative_to(root)} - не перезаписываю, разбираться")
            bad += 1
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        a, b = digest(src), digest(dst)
        if a != b:
            print(f"DIFF       {rel_posix} ({a[:12]}) != {dst.relative_to(root)} ({b[:12]})")
            bad += 1
            continue
        lines = sum(1 for _ in open(src, encoding="utf-8", errors="replace"))
        print(f"OK  {a[:12]}  {rel_posix} -> {dst.relative_to(root)}")
        rows.append(f"| `{dst.name}` | {lines} | <о чём> |")
    if rows:
        print("\nСтроки описи для ARCHIVE/README.md:")
        print(f"## {dt.date.today().strftime('%d.%m.%Y')} - <повод>\n")
        print("| Файл в архиве | Строк | О чём |\n|---|---|---|")
        print("\n".join(rows))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
