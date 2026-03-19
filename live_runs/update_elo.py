#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
	from data_scraping.player_info import get_player_info
except ModuleNotFoundError:
	import sys
	sys.path.append(str(Path(__file__).resolve().parent.parent))
	from data_scraping.player_info import get_player_info


STARTING_ELO = 1500.0


def calculate_expected_score(rating_a: float, rating_b: float) -> float:
	"""Probability that player A wins against player B."""
	return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def update_elo(old_rating: float, expected: float, actual: float, k: float) -> float:
	"""Standard Elo update formula."""
	return old_rating + k * (actual - expected)


def load_player_elos(player_elo_dir: Path) -> dict[int, dict[str, Any]]:
	"""Load existing player Elo JSON files into memory."""
	players: dict[int, dict[str, Any]] = {}

	for elo_file in sorted(player_elo_dir.glob("*.json")):
		try:
			with open(elo_file, "r", encoding="utf-8") as f:
				player = json.load(f)
		except Exception as exc:
			print(f"Skipping unreadable file {elo_file.name}: {exc}")
			continue

		player_id = player.get("player_id")
		if player_id is None:
			print(f"Skipping file without player_id: {elo_file.name}")
			continue

		player.setdefault("elo", STARTING_ELO)
		player.setdefault("faceoffs_taken", 0)
		player.setdefault("offensive_faceoffs", 0)
		player.setdefault("defensive_faceoffs", 0)
		player.setdefault("neutral_faceoffs", 0)

		players[player_id] = player

	return players


def default_player(player_id: int) -> dict[str, Any]:
	"""Build payload for players not present in the existing Elo set."""
	player_info = {}
	try:
		player_info = get_player_info(player_id) or {}
	except Exception:
		player_info = {}

	return {
		"player_id": player_id,
		"player_name": player_info.get("name", "Unknown Player"),
		"player_team": player_info.get("team", "Unknown Team"),
		"elo": STARTING_ELO,
		"faceoffs_taken": 0,
		"offensive_faceoffs": 0,
		"defensive_faceoffs": 0,
		"neutral_faceoffs": 0,
		"position": player_info.get("position", "Unknown"),
	}


def iter_faceoff_events(game_file: Path):
	"""Yield normalized faceoff events from either known game JSON layout."""
	with open(game_file, "r", encoding="utf-8") as f:
		payload = json.load(f)

	if isinstance(payload, list):
		events = payload
	elif isinstance(payload, dict):
		events = payload.get("faceoffs", [])
	else:
		events = []

	for event in events:
		if not isinstance(event, dict):
			continue
		details = event.get("details", {})
		if not isinstance(details, dict):
			continue

		winner_id = details.get("winningPlayerId")
		loser_id = details.get("losingPlayerId")
		zone_code = details.get("zoneCode", "N")

		if winner_id is None or loser_id is None:
			continue

		yield winner_id, loser_id, zone_code


def apply_faceoff_updates(
	*,
	players: dict[int, dict[str, Any]],
	game_files: list[Path],
	k: float,
) -> tuple[int, int]:
	"""Apply Elo updates from faceoff game files and return (processed, skipped)."""
	processed = 0
	skipped = 0

	for game_file in game_files:
		for winner_id, loser_id, zone_code in iter_faceoff_events(game_file):
			winner = players.setdefault(winner_id, default_player(winner_id))
			loser = players.setdefault(loser_id, default_player(loser_id))

			winner_expected = calculate_expected_score(winner["elo"], loser["elo"])
			loser_expected = calculate_expected_score(loser["elo"], winner["elo"])

			winner["elo"] = update_elo(winner["elo"], winner_expected, 1, k)
			loser["elo"] = update_elo(loser["elo"], loser_expected, 0, k)

			winner["faceoffs_taken"] += 1
			loser["faceoffs_taken"] += 1

			if zone_code == "N":
				winner["neutral_faceoffs"] += 1
				loser["neutral_faceoffs"] += 1
			elif zone_code == "O":
				winner["offensive_faceoffs"] += 1
				loser["defensive_faceoffs"] += 1
			elif zone_code == "D":
				winner["defensive_faceoffs"] += 1
				loser["offensive_faceoffs"] += 1
			else:
				# Keep processing and default unknown zones to neutral tracking.
				winner["neutral_faceoffs"] += 1
				loser["neutral_faceoffs"] += 1
				skipped += 1

			processed += 1

	return processed, skipped


def apply_time_on_ice_updates(
	*,
	players: dict[int, dict[str, Any]],
	game_files: list[Path],
) -> tuple[int, int]:
	"""Add toi_seconds from each game file to players that already have Elo entries."""
	updated_players = 0
	total_seconds_added = 0

	for game_file in game_files:
		with open(game_file, "r", encoding="utf-8") as f:
			payload = json.load(f)

		if not isinstance(payload, dict):
			continue

		players_toi = payload.get("players", {})
		if not isinstance(players_toi, dict):
			continue

		for raw_player_id, player_blob in players_toi.items():
			try:
				player_id = int(raw_player_id)
			except (TypeError, ValueError):
				continue

			if player_id not in players:
				continue
			if not isinstance(player_blob, dict):
				continue

			toi_seconds = player_blob.get("toi_seconds", 0)
			if not isinstance(toi_seconds, int) or toi_seconds <= 0:
				continue

			if "time_on_ice_seconds" not in players[player_id]:
				players[player_id]["time_on_ice_seconds"] = 0

			players[player_id]["time_on_ice_seconds"] += toi_seconds
			updated_players += 1
			total_seconds_added += toi_seconds

	return updated_players, total_seconds_added


def save_player_elos(players: dict[int, dict[str, Any]], player_elo_dir: Path) -> None:
	"""Persist all players back to individual JSON files."""
	player_elo_dir.mkdir(parents=True, exist_ok=True)

	for player_id, payload in players.items():
		output_file = player_elo_dir / f"{player_id}.json"
		with open(output_file, "w", encoding="utf-8") as f:
			json.dump(payload, f, indent=4)
			f.write("\n")


def resolve_game_files(game_ids: list[str], faceoff_data_dir: Path) -> tuple[list[Path], list[str]]:
	"""Resolve game IDs to files in the faceoff_data directory.

	Returns (found_files, missing_game_ids).
	"""
	found_files: list[Path] = []
	missing_ids: list[str] = []

	for game_id in game_ids:
		candidate = faceoff_data_dir / f"{game_id}_faceoff_data.json"
		if candidate.is_file():
			found_files.append(candidate)
		else:
			missing_ids.append(game_id)

	return found_files, missing_ids


def main() -> int:
	parser = argparse.ArgumentParser(
		prog="automatic_update_elo",
		description="Apply additional faceoff games to an existing set of player Elo JSON files.",
	)
	parser.add_argument(
		"--player-elo-dir",
		default="player_elos",
		help="Directory containing current per-player Elo JSON files.",
	)
	parser.add_argument(
		"--game-ids",
		nargs="+",
		required=True,
		help="One or more game IDs to process (example: 2024010001 2024010002)",
	)
	parser.add_argument(
		"--faceoff-data-dir",
		default="faceoff_data",
		help="Directory containing <game_id>_faceoff_data.json files.",
	)
	args = parser.parse_args()

	player_elo_dir = Path(args.player_elo_dir)
	if not player_elo_dir.exists() or not player_elo_dir.is_dir():
		raise SystemExit(f"Elo directory not found: {player_elo_dir}")

	faceoff_data_dir = Path(args.faceoff_data_dir)
	if not faceoff_data_dir.exists() or not faceoff_data_dir.is_dir():
		raise SystemExit(f"Faceoff data directory not found: {faceoff_data_dir}")

	game_files, missing_game_ids = resolve_game_files(args.game_ids, faceoff_data_dir)
	if not game_files:
		raise SystemExit("No matching faceoff game files found for provided game IDs")
	if missing_game_ids:
		print(f"Warning: missing game IDs (skipped): {', '.join(missing_game_ids)}")

	players = load_player_elos(player_elo_dir)
	if not players:
		raise SystemExit(f"No valid player Elo files found in {player_elo_dir}")

	print(f"Loaded {len(players)} existing players from {player_elo_dir}")
	processed, unknown_zone_count = apply_faceoff_updates(
		players=players,
		game_files=game_files,
		k=3,
	)
	toi_players_updated, toi_seconds_added = apply_time_on_ice_updates(
		players=players,
		game_files=game_files,
	)
	save_player_elos(players, player_elo_dir)

	print(f"Processed faceoffs: {processed}")
	print(f"TOI updates applied: {toi_players_updated} player-game entries")
	print(f"TOI seconds added: {toi_seconds_added}")
	if unknown_zone_count:
		print(f"Unknown zoneCode count (tracked as neutral): {unknown_zone_count}")
	print(f"Updated player files written to {player_elo_dir}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
