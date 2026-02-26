from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import urllib.error
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional


def _safe_get_team_name(game: dict, side: str) -> Optional[str]:
	"""Return the team's common name (preferred) or fallbacks.

	Handles multiple response shapes returned by different NHL endpoints.
	"""
	# shape: `awayTeam` / `homeTeam` with `commonName.default`
	key = side + "Team"
	if key in game and isinstance(game[key], dict):
		team = game[key]
		# commonName may be a dict with `default` key
		common = team.get("commonName")
		if isinstance(common, dict):
			val = common.get("default")
			if val:
				return val
		if isinstance(common, str):
			return common
		# fallback to placeName or abbrev
		for alt in ("placeName", "abbrev", "name", "teamName"):
			v = team.get(alt)
			if isinstance(v, dict):
				maybe = v.get("default")
				if maybe:
					return maybe
			if isinstance(v, str) and v:
				return v

	# older shape: `teams` -> `away`/`home` -> `team` -> fields
	teams = game.get("teams")
	if teams and side in teams and isinstance(teams[side], dict):
		t = teams[side].get("team") or teams[side]
		if isinstance(t, dict):
			common = t.get("commonName") or t.get("name")
			if isinstance(common, dict):
				val = common.get("default")
				if val:
					return val
			if isinstance(common, str) and common:
				return common
			for alt in ("placeName", "abbrev", "teamName"):
				v = t.get(alt)
				if isinstance(v, dict):
					maybe = v.get("default")
					if maybe:
						return maybe
				if isinstance(v, str) and v:
					return v

	return None


def _safe_get_team_id(game: dict, side: str) -> Optional[int]:
	"""Return team id for side ('away' or 'home') handling different shapes."""
	key = side + "Team"
	if key in game and isinstance(game[key], dict):
		tid = game[key].get("id")
		if isinstance(tid, int):
			return tid
		# sometimes id is string
		if isinstance(tid, str) and tid.isdigit():
			return int(tid)

	teams = game.get("teams")
	if teams and side in teams and isinstance(teams[side], dict):
		t = teams[side].get("team") or teams[side]
		if isinstance(t, dict):
			tid = t.get("id") or t.get("teamId")
			if isinstance(tid, int):
				return tid
			if isinstance(tid, str) and tid.isdigit():
				return int(tid)

	return None


def _get_games_array(root: dict) -> List[dict]:
	# new format uses `gameWeek` with dates containing `games`
	if "gameWeek" in root and isinstance(root["gameWeek"], list):
		games = []
		for d in root["gameWeek"]:
			if isinstance(d, dict) and "games" in d:
				games.extend(d.get("games", []))
		return games
	# older format uses `dates` with `games`
	if "dates" in root and isinstance(root["dates"], list):
		games = []
		for d in root["dates"]:
			if isinstance(d, dict) and "games" in d:
				games.extend(d.get("games", []))
		return games
	# fallback: maybe the root itself contains `games`
	if "games" in root and isinstance(root["games"], list):
		return root["games"]
	return []


def get_games_for_date(date_str: Optional[str] = None, inspect: bool = False) -> List[Dict]:
	"""Return a list of games for the given date (YYYY-MM-DD).

	If `inspect` is True the raw JSON response will be printed to stdout
	to help enforce parsing rules.
	"""
	if date_str is None:
		date_str = date.today().isoformat()

	url = f"https://api-web.nhle.com/v1/schedule/{date_str}"

	req = urllib.request.Request(url, headers={"User-Agent": "python-urllib/3"})
	try:
		with urllib.request.urlopen(req, timeout=20) as resp:
			raw = resp.read().decode("utf-8")
	except urllib.error.HTTPError as e:
		raise RuntimeError(f"HTTP error {e.code} when fetching schedule: {e.reason}")
	except urllib.error.URLError as e:
		raise RuntimeError(f"URL error when fetching schedule: {e}")

	if inspect:
		# print raw JSON so caller can inspect shape
		print(raw)

	data = json.loads(raw)
	games = _get_games_array(data)

	out = []
	for g in games:
		# game id variations: `id` or `gamePk`
		game_id = g.get("id") or g.get("gamePk") or g.get("gameId")

		# start time: `startTimeUTC` or `gameDate`
		start_time = g.get("startTimeUTC") or g.get("gameDate")
		start_time_est = None
		if start_time:
			try:
				# canonicalize Z
				if start_time.endswith("Z"):
					dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
				else:
					dt = datetime.fromisoformat(start_time)
				est = dt.astimezone(ZoneInfo("America/New_York"))
				start_time_est = est.isoformat()

				# human-friendly common time like '7pm' or '7:30pm'
				h = est.hour
				m = est.minute
				ampm = "pm" if h >= 12 else "am"
				display_hour = h % 12 or 12
				if m == 0:
					start_time_common = f"{display_hour}{ampm}"
				else:
					start_time_common = f"{display_hour}:{m:02d}{ampm}"
			except Exception:
				start_time_est = start_time
				start_time_common = None

		away_name = _safe_get_team_name(g, "away")
		home_name = _safe_get_team_name(g, "home")
		away_id = _safe_get_team_id(g, "away")
		home_id = _safe_get_team_id(g, "home")

		out.append({
			"game_id": game_id,
			"home_team": {"id": home_id, "name": home_name},
			"away_team": {"id": away_id, "name": away_name},
			"start_time_est": start_time_est,
			"start_time_common": start_time_common,
		})

	return out


def _cli() -> int:
	p = argparse.ArgumentParser(description="Fetch NHL game ids for a date (default: today)")
	p.add_argument("--date", "-d", help="Date YYYY-MM-DD (default: today)")
	p.add_argument("--inspect", action="store_true", help="Print raw JSON response before parsing")
	args = p.parse_args()

	try:
		games = get_games_for_date(args.date, inspect=args.inspect)
	except Exception as e:
		print("Error:", e, file=sys.stderr)
		return 2

	print(json.dumps(games, indent=2))
	return 0


if __name__ == "__main__":
	raise SystemExit(_cli())

