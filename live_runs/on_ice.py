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


def get_players_on_ice(game_id: str, api_key: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
	"""Return players currently on the ice for `game_id`.

	Looks at the latest event that contains `on_ice` and returns the `home`
	and `away` player lists (empty lists if not found).
	"""
	pbp = fetch_pbp(game_id, api_key=api_key)
	# events may be at top-level or nested inside `periods` -> `events`
	events = pbp.get("events") or []
	for period in pbp.get("periods", []):
		events.extend(period.get("events") or [])
	# Search events in reverse chronological order for an `on_ice` field
	for ev in reversed(events):
		if "on_ice" in ev and ev["on_ice"]:
			teams = ev["on_ice"]
			result: Dict[str, List[Dict[str, Any]]] = {"home": [], "away": []}
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
	return {"home": [], "away": []}


if __name__ == "__main__":
	import argparse
	import json

	parser = argparse.ArgumentParser(description="Get players on ice for game_id")
	parser.add_argument("game_id", help="Sportradar game id (uuid)")
	parser.add_argument("--api-key", help="Sportradar API key (or set SPORTRADAR_API_KEY)")
	args = parser.parse_args()
	players = get_players_on_ice(args.game_id, api_key=args.api_key)
	print(json.dumps(players, indent=2))

