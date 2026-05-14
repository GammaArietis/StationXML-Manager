#!/usr/bin/env python3
"""
Trova ed elimina in modo controllato file di backup palesemente duplicati, ad esempio:
  - nomi che terminano con ' copia.py' (copia locale macOS / manuale)
  - nomi che terminano con ' copy.py'

Uso:
  python3 scripts/cleanup_backup_copies.py           # solo elenco (dry-run)
  python3 scripts/cleanup_backup_copies.py --delete
  python3 scripts/cleanup_backup_copies.py --delete --force   # anche se il contenuto ≠ file .py principale

Non tocca file senza suffisso riconosciuto. Con --delete, se esiste il canonico e SHA-256
differisce, l'eliminazione viene bloccata salvo --force (le «copia» sono spesso vecchie).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

# Suffissi da considerare solo su file .py (estendere qui se serve)
SUFFIX_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (" copia.py", re.compile(r" copia\.py$", re.IGNORECASE)),
    (" copy.py", re.compile(r" copy\.py$", re.IGNORECASE)),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _canonical_path(backup: Path) -> Path | None:
    name = backup.name
    for suffix, pat in SUFFIX_PATTERNS:
        if pat.search(name):
            stem = name[: -len(suffix)]
            return backup.with_name(f"{stem}.py")
    return None


def find_candidates(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*.py"):
        if any(part in (".git", ".venv", "venv", "node_modules", "__pycache__") for part in p.parts):
            continue
        if any(pat.search(p.name) for _, pat in SUFFIX_PATTERNS):
            out.append(p)
    return sorted(out, key=lambda x: str(x))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=_repo_root(),
        help="Radice del repository (default: genitore di scripts/)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Elimina i file elencati (default: solo stampa)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Con --delete, elimina anche se digest ≠ file canonico (backup obsoleto)",
    )
    args = parser.parse_args()
    root: Path = args.root.resolve()
    if not root.is_dir():
        print(f"Radice non valida: {root}", file=sys.stderr)
        return 1

    candidates = find_candidates(root)
    if not candidates:
        print("Nessun file corrispondente ai pattern di backup.")
        return 0

    print(f"Repository: {root}\n")
    warnings: list[str] = []
    for p in candidates:
        rel = p.relative_to(root)
        canon = _canonical_path(p)
        size = p.stat().st_size
        line = f"  {rel}  ({size} byte)"
        if canon and canon.is_file():
            same = _sha256(p) == _sha256(canon)
            line += f"  [canonico: {canon.relative_to(root)} — digest {'UGUALE' if same else 'DIVERSO'}]"
            if not same:
                warnings.append(
                    f"ATTENZIONE: {rel} e {canon.relative_to(root)} hanno contenuto diverso."
                )
        elif canon:
            line += f"  [nessun file canonico atteso: {canon.name}]"
        print(line)

    for w in warnings:
        print(f"\n{w}", file=sys.stderr)

    if not args.delete:
        print(
            "\nDry-run: nessun file eliminato. "
            "Per eliminare, rilancia con:  python3 scripts/cleanup_backup_copies.py --delete"
        )
        return 1 if warnings else 0

    if warnings and not args.force:
        print(
            "\nEliminazione annullata: digest diversi dal file principale. "
            "Se sono solo backup vecchi, rilancia con --delete --force",
            file=sys.stderr,
        )
        return 2
    if warnings and args.force:
        print("\n--force: eliminazione procede nonostante digest diversi.", file=sys.stderr)

    for p in candidates:
        p.unlink()
        print(f"Eliminato: {p.relative_to(root)}")
    print(f"\nCompletato: rimossi {len(candidates)} file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
