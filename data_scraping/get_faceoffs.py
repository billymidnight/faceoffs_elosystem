import requests
import json
import os
from typing import Dict, Tuple


def toi_to_seconds(toi_str: str) -> int:
    # Expected formats seen from the API: "MM:SS" (usually), sometimes could be "HH:MM:SS".
    if not toi_str:
        return 0
    parts = toi_str.split(":")
    try:
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + int(seconds)
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    except ValueError:
        return 0
    return 0


def seconds_to_hhmmss(total_seconds: int) -> str:
    if total_seconds < 0:
        total_seconds = 0
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours}:{minutes:02d}:{seconds:02d}"


# Ensure data directory exists
os.makedirs('faceoff_data', exist_ok=True)


def process_game(game: str) -> Tuple[Dict[str, int], Dict[str, str]]:
    """Fetch play-by-play and boxscore for a single game.

    Returns a tuple (player_toi_map, player_names_map) where player_toi_map maps
    player_id (string) -> toi_seconds (int) for that game, and player_names_map
    maps player_id -> player name (if available).
    """
    player_toi: Dict[str, int] = {}
    player_names: Dict[str, str] = {}

    # 1) Play-by-play -> faceoffs (save to file if available)
    game_data_url = f"https://api-web.nhle.com/v1/gamecenter/{game}/play-by-play"
    try:
        response = requests.get(game_data_url)
    except Exception:
        response = None

    if response and response.status_code == 200:
        game_data = response.json()
        plays = game_data.get('plays', [])
        faceoffs = [play for play in plays if play.get('typeCode') == 502]  # faceoff
        with open(f'faceoff_data/{game}_faceoff_data.json', 'w') as out_f:
            json.dump(faceoffs, out_f, indent=4)

    # 2) Boxscore -> time on ice aggregation
    boxscore_url = f"https://api-web.nhle.com/v1/gamecenter/{game}/boxscore"
    try:
        bs_response = requests.get(boxscore_url)
    except Exception:
        bs_response = None

    if bs_response and bs_response.status_code == 200:
        bs_data = bs_response.json()
        pbg = bs_data.get('playerByGameStats', {})

        def collect_team(team_obj):
            for group_key in ("forwards", "defense", "goalies"):
                for p in team_obj.get(group_key, []) or []:
                    player_id = p.get("playerId")
                    if player_id is None:
                        continue
                    pid = str(player_id)
                    name = (p.get("name") or {}).get("default")
                    if name:
                        player_names[pid] = name
                    player_toi[pid] = player_toi.get(pid, 0) + toi_to_seconds(p.get("toi"))

        away = pbg.get("awayTeam", {})
        home = pbg.get("homeTeam", {})
        collect_team(away)
        collect_team(home)

    return player_toi, player_names


def main():
    # Read game list and call process_game for each game, aggregating TOI
    player_toi_seconds: Dict[str, int] = {}
    player_names: Dict[str, str] = {}

    if not os.path.exists('game_nums.txt'):
        print('game_nums.txt not found')
        return

    with open('game_nums.txt', 'r') as f:
        game_nums = f.read().splitlines()

    for game in game_nums:
        if not game:
            continue
        per_game_toi, per_game_names = process_game(game)
        for pid, secs in per_game_toi.items():
            player_toi_seconds[pid] = player_toi_seconds.get(pid, 0) + secs
        for pid, name in per_game_names.items():
            if pid not in player_names:
                player_names[pid] = name

    # Output: mapping from player -> total time on ice (summed across all processed games)
    player_total_toi = {}
    for player_id, total_seconds in player_toi_seconds.items():
        player_total_toi[player_id] = {
            "name": player_names.get(player_id),
            "toi_seconds": total_seconds,
            "toi": seconds_to_hhmmss(total_seconds),
        }

    with open('player_total_time_on_ice.json', 'w') as f:
        json.dump(player_total_toi, f, indent=4)


if __name__ == '__main__':
    main()