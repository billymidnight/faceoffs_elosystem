"""Utilities to fetch players currently on ice for a game using Sportradar PBP.

Provides `get_players_on_ice(game_id, api_key=None)` which returns a dict
with `home` and `away` lists of player dicts as returned in the `on_ice`
section of events.

This file also exposes a small CLI when run as `python -m live_runs.on_ice`.
"""

from __future__ import annotations

import os
import requests
from typing import Dict, List, Any, Optional

API_URL_TEMPLATE = (
	"https://api.sportradar.com/nhl/trial/v7/en/games/{game_id}/pbp.json"
)


def _resolve_home_away_teams(pbp: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
	"""Return normalized home/away team dicts from supported PBP response shapes."""
	# Common SportsRadar PBP shape: top-level `home` / `away`.
	home = pbp.get("home") or {}
	away = pbp.get("away") or {}

	# Some feeds may nest teams under `sport_event` or `game`.
	if not home or not away:
		container = pbp.get("sport_event") or pbp.get("game") or {}
		home = home or container.get("home") or container.get("home_team") or {}
		away = away or container.get("away") or container.get("away_team") or {}

	# Another variant: competitors with `qualifier` in container.
	if not home or not away:
		container = pbp.get("sport_event") or pbp.get("game") or {}
		for comp in container.get("competitors") or []:
			if not isinstance(comp, dict):
				continue
			qualifier = str(comp.get("qualifier") or "").lower()
			if qualifier == "home" and not home:
				home = comp
			elif qualifier == "away" and not away:
				away = comp

	return home, away


def _team_matches(candidate: Dict[str, Any], target: Dict[str, Any]) -> bool:
	"""Return True when two team dicts appear to refer to the same team."""
	if not candidate or not target:
		return False

	for key in ("id", "sr_id", "reference"):
		c = candidate.get(key)
		t = target.get(key)
		if c is not None and t is not None and str(c) == str(t):
			return True

	# Name fallback for feeds that omit ids.
	cn = str(candidate.get("name") or "").strip().lower()
	tn = str(target.get("name") or "").strip().lower()
	if cn and tn and cn == tn:
		return True

	return False


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
	home_team, away_team = _resolve_home_away_teams(pbp)
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
				players = team.get("players", [])
				side: Optional[str] = None
				if _team_matches(team, home_team):
					side = "home"
				elif _team_matches(team, away_team):
					side = "away"

				if side is None:
					# Deterministic fallback when feed omits all comparable team fields.
					side = "home" if not result["home"] else "away"

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

