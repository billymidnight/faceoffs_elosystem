#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable


# Hardcoded, expected schema for player files.
REQUIRED_KEYS: tuple[str, ...] = (
    "player_id",
    "player_name",
    "player_team",
    "elo",
    "faceoffs_taken",
    "offensive_faceoffs",
    "defensive_faceoffs",
    "neutral_faceoffs",
    "time_on_ice_seconds",
)

STARTING_ELO = 1500


def _reset_player_payload(payload: Any, *, preserve_extra_keys: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object at top level")

    if preserve_extra_keys:
        cleaned: dict[str, Any] = dict(payload)
    else:
        cleaned = {k: payload.get(k) for k in REQUIRED_KEYS if k in payload}

    # Clear / reset computed fields.
    cleaned["elo"] = STARTING_ELO
    cleaned["faceoffs_taken"] = 0
    cleaned["offensive_faceoffs"] = 0
    cleaned["defensive_faceoffs"] = 0
    cleaned["neutral_faceoffs"] = 0

    return cleaned


def _iter_json_files(directory: Path) -> Iterable[Path]:
    # Only top-level *.json, to match the current player_elos layout.
    yield from sorted(p for p in directory.iterdir() if p.is_file() and p.suffix == ".json")


def _write_json_atomic(path: Path, data: Any, *, indent: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.write("\n")
        tmp_path.replace(path)
    finally:
        # If anything failed before replace(), best-effort cleanup.
        try:
            if tmp_path.exists() and tmp_path != path:
                tmp_path.unlink()
        except OSError:
            pass


def clear_elos(
    player_elo_dir: Path,
    *,
    dry_run: bool,
    preserve_extra_keys: bool,
    backup_suffix: str | None,
) -> tuple[int, int]:
    """Return (files_changed, files_failed)."""
    changed = 0
    failed = 0

    for json_path in _iter_json_files(player_elo_dir):
        try:
            original_text = json_path.read_text(encoding="utf-8")
            payload = json.loads(original_text)
            cleaned = _reset_player_payload(
                payload,
                preserve_extra_keys=preserve_extra_keys,
            )

            # Normalize output formatting so diffs are stable.
            cleaned_text = json.dumps(cleaned, indent=4, ensure_ascii=False) + "\n"
            if cleaned_text == original_text:
                continue

            changed += 1
            if dry_run:
                continue

            if backup_suffix:
                backup_path = json_path.with_name(json_path.name + backup_suffix)
                if not backup_path.exists():
                    backup_path.write_text(original_text, encoding="utf-8")

            _write_json_atomic(json_path, cleaned, indent=4)
        except Exception:
            failed += 1

    return changed, failed


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="clear_elos",
        description=(
            "Reset Elo and faceoff-count fields in player JSON files under player_elos, "
            "while keeping time-on-ice fields."
        ),
    )
    parser.add_argument(
        "--dir",
        default="player_elos",
        help="Directory containing per-player JSON files (default: player_elos)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report changes but do not modify any files",
    )
    parser.add_argument(
        "--no-preserve-extra-keys",
        action="store_true",
        help="Drop any keys not in the hardcoded schema",
    )
    parser.add_argument(
        "--backup-suffix",
        default=None,
        help="If set, write a one-time backup copy with this suffix (e.g. .bak)",
    )
    args = parser.parse_args()

    player_elo_dir = Path(args.dir)
    if not player_elo_dir.exists() or not player_elo_dir.is_dir():
        raise SystemExit(f"Directory not found: {player_elo_dir}")

    changed, failed = clear_elos(
        player_elo_dir,
        dry_run=bool(args.dry_run),
        preserve_extra_keys=not bool(args.no_preserve_extra_keys),
        backup_suffix=args.backup_suffix,
    )

    print(f"Changed files: {changed}")
    if failed:
        print(f"Failed files: {failed}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
