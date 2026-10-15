#!/usr/bin/env python3
"""Копия файлов в архив перед сжатием, со сверкой sha256.

Запуск:  python3 archive_copy.py <корень проекта> <файл относительно корня> [...]
                                 [--archive-root <папка>] [--suffix <имя этапа>]

Копия ложится в <архив>/<ГГГГ-ММ-ДД>/<путь с подчёркиваниями вместо разделителей>:
docs/CHANGELOG.md -> ARCHIVE/2026-10-13/docs_CHANGELOG.md.

Где архив: <корень>/ARCHIVE/; если в docs/CONVENTIONS.md в таблице «Внешние корни» есть строка
`ARCHIVE/` с колонкой «Где на диске» (например `../PROJECT_ARCHIVE/`) - там; --archive-root
перекрывает и то и другое.

Копия никогда не перезаписывается. Если за этот день копия того же файла уже есть:
содержимое совпадает - «ТОТ ЖЕ», ничего не делается; отличается (второй этап за день) - новая
копия рядом с суффиксом: --suffix stage2 -> docs_CONTEXT.stage2.md, без --suffix - время
docs_CONTEXT.1432.md. После копирования сверка sha256 и заготовка строк описи для README.md
архива. Код выхода 1 при любой ошибке. Только стандартная библиотека.
"""

import argparse
import datetime as dt
import hashlib
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from doc_lint import conventions_tables
except ImportError:  # скрипт скопирован без doc_lint.py - работаем без таблицы
    conventions_tables = None


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_root(root, override):
    """--archive-root, иначе строка `ARCHIVE/` из «Внешних корней», иначе <корень>/ARCHIVE."""
    if override:
        p = Path(override).expanduser()
        return (p if p.is_absolute() else root / p).resolve()
    if conventions_tables is not None:
        _, _, roots, _ = conventions_tables(root / "docs")
        for prefix, disk in roots:
            if prefix.strip("/") == "ARCHIVE" and disk:
                p = Path(disk).expanduser()
                return (p if p.is_absolute() else root / p).resolve()
    return root / "ARCHIVE"


def main(argv):
    ap = argparse.ArgumentParser(description="Копия файлов в архив перед правкой", add_help=True)
    ap.add_argument("root", help="корень проекта")
    ap.add_argument("files", nargs="+", help="файлы относительно корня")
    ap.add_argument("--archive-root", help="папка архива вместо <корень>/ARCHIVE или таблицы")
    ap.add_argument("--suffix", help="имя этапа для повторной копии за день: stage2 -> docs_X.stage2.md")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    root = Path(args.root).resolve()
    archive = archive_root(root, args.archive_root)
    day = dt.date.today().isoformat()
    target_dir = archive / day
    disp = lambda p: os.path.relpath(p, root)  # noqa: E731 - вне проекта печатается ../...
    bad = 0
    rows = []
    print(f"архив: {disp(archive)}")
    for rel in args.files:
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
        base = rel_posix.replace("/", "_")
        stem, ext = os.path.splitext(base)
        a = digest(src)
        dst = target_dir / (f"{stem}.{args.suffix}{ext}" if args.suffix else base)
        if dst.exists():
            if digest(dst) == a:
                print(f"ТОТ ЖЕ  {a[:12]}  {rel_posix} = {disp(dst)} - копия уже снята, не трогаю")
                continue
            if args.suffix:
                print(f"УЖЕ ЕСТЬ   {disp(dst)} с другим содержимым - не перезаписываю, дайте другой --suffix")
                bad += 1
                continue
            dst = target_dir / f"{stem}.{dt.datetime.now():%H%M}{ext}"
            if dst.exists():
                print(f"УЖЕ ЕСТЬ   {disp(dst)} - не перезаписываю, повторите через минуту или с --suffix")
                bad += 1
                continue
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        b = digest(dst)
        if a != b:
            print(f"DIFF       {rel_posix} ({a[:12]}) != {disp(dst)} ({b[:12]})")
            bad += 1
            continue
        lines = sum(1 for _ in open(src, encoding="utf-8", errors="replace"))
        print(f"OK  {a[:12]}  {rel_posix} -> {disp(dst)}")
        rows.append(f"| `{dst.name}` | {lines} | <о чём> |")
    if rows:
        print(f"\nСтроки описи для {disp(archive / 'README.md')}:")
        print(f"## {dt.date.today().strftime('%d.%m.%Y')} - <повод>\n")
        print("| Файл в архиве | Строк | О чём |\n|---|---|---|")
        print("\n".join(rows))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
