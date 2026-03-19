"""Utilities to fetch players currently on ice for a game using Sportradar PBP.

Provides `get_players_on_ice(game_id, api_key=None)` which returns a dict
with `home` and `away` lists of player dicts as returned in the `on_ice`
section of events.

This file also exposes a small CLI when run as `python -m live_runs.on_ice`.
"""

from __future__ import annotations

import json
import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Any, Optional

API_URL_TEMPLATE = (
	"https://api.sportradar.com/nhl/trial/v7/en/games/{game_id}/pbp.json"
)


def _now_est() -> str:
	return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S %Z")


def extract_player_id(player: Dict[str, Any]) -> Optional[int]:
	"""Extract NHL player id from a Sportradar player payload when possible."""
	for key in ("reference", "player_id", "id"):
		val = player.get(key)
		if val is None:
			continue
		if isinstance(val, int):
			return val
		if isinstance(val, str) and val.isdigit():
			return int(val)
	return None


def probability_to_american_odds(prob: float) -> str:
	"""Convert probability in [0,1] to American odds string."""
	if prob <= 0.0:
		return "N/A"
	if prob >= 1.0:
		return "-INF"

	if prob >= 0.5:
		odds = -100.0 * prob / (1.0 - prob)
	else:
		odds = 100.0 * (1.0 - prob) / prob

	rounded = int(round(odds))
	if rounded > 0:
		return f"+{rounded}"
	return str(rounded)


def build_lineup_key(home_players: List[Dict[str, Any]], away_players: List[Dict[str, Any]]) -> str:
	"""Create a stable lineup key from on-ice player ids for home and away teams."""
	home_ids = sorted({pid for pid in (extract_player_id(p) for p in home_players) if pid is not None})
	away_ids = sorted({pid for pid in (extract_player_id(p) for p in away_players) if pid is not None})
	home_blob = ",".join(str(pid) for pid in home_ids)
	away_blob = ",".join(str(pid) for pid in away_ids)
	return f"H:{home_blob}|A:{away_blob}"


def _append_jsonl(log_path: str, payload: Dict[str, Any]) -> None:
	os.makedirs(os.path.dirname(log_path), exist_ok=True)
	with open(log_path, "a", encoding="utf-8") as f:
		f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def log_manual_odds_snapshot(
	log_path: str,
	game_id: str,
	home_name: str,
	away_name: str,
	game_state: str,
	lineup_key: str,
	home_probability: float,
	away_probability: float,
	home_odds: str,
	away_odds: str,
) -> Dict[str, Any]:
	"""Write a manual odds snapshot event and return the stored payload."""
	payload: Dict[str, Any] = {
		"event_type": "manual_snapshot",
		"timestamp_est": _now_est(),
		"game_id": game_id,
		"home_name": home_name,
		"away_name": away_name,
		"game_state": game_state,
		"lineup_key": lineup_key,
		"home_probability": home_probability,
		"away_probability": away_probability,
		"home_odds": home_odds,
		"away_odds": away_odds,
		"matched_to_faceoff": False,
	}
	_append_jsonl(log_path, payload)
	return payload


def pick_manual_snapshot_for_faceoff(
	manual_snapshots: List[Dict[str, Any]],
	lineup_key: str,
) -> Optional[Dict[str, Any]]:
	"""Pick the latest unmatched manual snapshot, preferring identical lineups."""
	for snap in reversed(manual_snapshots):
		if snap.get("matched_to_faceoff"):
			continue
		if snap.get("lineup_key") == lineup_key:
			snap["matched_to_faceoff"] = True
			return snap

	for snap in reversed(manual_snapshots):
		if snap.get("matched_to_faceoff"):
			continue
		snap["matched_to_faceoff"] = True
		return snap

	return None


def log_faceoff_odds_comparison(
	log_path: str,
	game_id: str,
	home_name: str,
	away_name: str,
	game_state: str,
	event_id: Any,
	event_description: str,
	faceoff_lineup_key: str,
	faceoff_home_probability: float,
	faceoff_away_probability: float,
	faceoff_home_odds: str,
	faceoff_away_odds: str,
	manual_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
	"""Write a faceoff comparison record versus the most recent manual snapshot."""
	payload: Dict[str, Any] = {
		"event_type": "faceoff_comparison",
		"timestamp_est": _now_est(),
		"game_id": game_id,
		"home_name": home_name,
		"away_name": away_name,
		"game_state": game_state,
		"event_id": event_id,
		"event_description": event_description,
		"faceoff_lineup_key": faceoff_lineup_key,
		"faceoff_home_probability": faceoff_home_probability,
		"faceoff_away_probability": faceoff_away_probability,
		"faceoff_home_odds": faceoff_home_odds,
		"faceoff_away_odds": faceoff_away_odds,
	}

	if manual_snapshot is not None:
		manual_home_prob = float(manual_snapshot.get("home_probability", 0.0))
		manual_away_prob = float(manual_snapshot.get("away_probability", 0.0))
		payload["manual_snapshot"] = manual_snapshot
		payload["lineup_match"] = manual_snapshot.get("lineup_key") == faceoff_lineup_key
		payload["delta_home_probability"] = faceoff_home_probability - manual_home_prob
		payload["delta_away_probability"] = faceoff_away_probability - manual_away_prob
	else:
		payload["manual_snapshot"] = None
		payload["lineup_match"] = False

	_append_jsonl(log_path, payload)
	return payload


def fetch_pbp(game_id: str, api_key: Optional[str] = None) -> Dict[str, Any]:
	if api_key is None:
		api_key = os.getenv("SPORTRADAR_API_KEY")
	if not api_key:
		raise RuntimeError("Sportradar API key required via api_key arg or SPORTRADAR_API_KEY")
	url = API_URL_TEMPLATE.format(game_id=game_id)
	headers = {"accept": "application/json", "x-api-key": api_key}
	r = requests.get(url, headers=headers, timeout=10)
	r.raise_for_status()
	return r.json()


def _extract_game_state(pbp: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
	"""Extract game-state fields useful for live display."""
	clock = pbp.get("clock")
	period = pbp.get("period")
	status = pbp.get("status")

	if clock is None or period is None:
		for ev in reversed(events):
			if clock is None:
				clock = ev.get("clock")
			if period is None:
				period = ev.get("period")
			if clock is not None and period is not None:
				break

	return {"clock": clock, "period": period, "status": status}


def get_players_on_ice(game_id: str, api_key: Optional[str] = None) -> Dict[str, Any]:
	"""Return players currently on the ice for `game_id`.

	Looks at the latest event that contains `on_ice` and returns the `home`
	and `away` player lists along with top-level game state like clock/period.
	"""
	pbp = fetch_pbp(game_id, api_key=api_key)
	# events may be at top-level or nested inside `periods` -> `events`
	events = pbp.get("events") or []
	for period in pbp.get("periods", []):
		events.extend(period.get("events") or [])
	game_state = _extract_game_state(pbp, events)
	# Search events in reverse chronological order for an `on_ice` field
	for ev in reversed(events):
		if "on_ice" in ev and ev["on_ice"]:
			teams = ev["on_ice"]
			result: Dict[str, Any] = {
				"home": [],
				"away": [],
				"clock": game_state["clock"],
				"period": game_state["period"],
				"status": game_state["status"],
				"event_id": ev.get("id") or ev.get("sequence") or ev.get("number"),
				"event_type": ev.get("event_type"),
				"event_description": ev.get("description"),
			}
			for t in teams:
				team = t.get("team", {})
				name = team.get("name", "")
				players = team.get("players", [])
				# Determine if this is home or away by matching ids from pbp header
				# Fallback: use first character of team reference vs attributes in pbp
				# Simpler approach: look at attribution on event if present
				side = None
				# If event has an attribution and matches this team id, use home/away
				att = ev.get("attribution")
				if att and att.get("id") == team.get("id"):
					# compare to pbp boxscore teams if available
					game = pbp.get("game") or {}
					# fallback to event-level home_points/away_points ordering
				# Heuristic: determine side by comparing team id to pbp header
				# pbp includes `home` and `away` within `sport_event` or `game` sometimes
				se = pbp.get("sport_event") or pbp.get("game") or {}
				home_team = se.get("home") or se.get("home_team") or {}
				away_team = se.get("away") or se.get("away_team") or {}
				if team.get("id") == home_team.get("id") or team.get("sr_id") == home_team.get("sr_id"):
					side = "home"
				elif team.get("id") == away_team.get("id") or team.get("sr_id") == away_team.get("sr_id"):
					side = "away"
				else:
					# As a last resort try matching by `reference` vs home/away reference
					if str(team.get("reference")) == str(home_team.get("reference")):
						side = "home"
					elif str(team.get("reference")) == str(away_team.get("reference")):
						side = "away"
				if side is None:
					# If still unknown, attempt to infer from the event's home/away points
					# Use presence of `home_points` and `away_points` and attribution
					if ev.get("attribution") and ev["attribution"].get("name") == home_team.get("name"):
						side = "home"
					else:
						# default: if result currently empty, assign to away then home
						side = "away" if not result["away"] else "home"

				result[side].extend(players)
			return result
	return {
		"home": [],
		"away": [],
		"clock": game_state["clock"],
		"period": game_state["period"],
		"status": game_state["status"],
		"event_id": None,
		"event_type": None,
		"event_description": None,
	}


if __name__ == "__main__":
	import argparse
	import json

	parser = argparse.ArgumentParser(description="Get players on ice for game_id")
	parser.add_argument("game_id", help="Sportradar game id (uuid)")
	parser.add_argument("--api-key", help="Sportradar API key (or set SPORTRADAR_API_KEY)")
	args = parser.parse_args()
	players = get_players_on_ice(args.game_id, api_key=args.api_key)
	print(json.dumps(players, indent=2))

