import requests
import json
import os

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


player_toi_seconds = {}
player_names = {}

os.makedirs('faceoff_data', exist_ok=True)

with open('game_nums.txt', 'r') as f:
    game_nums = f.read().splitlines()
    for game in game_nums:
        if not game:
            continue

        # 1) Play-by-play -> faceoffs
        # game_data_url = f"https://api-web.nhle.com/v1/gamecenter/{game}/play-by-play"
        # response = requests.get(game_data_url)
        # if response.status_code == 200:
        #     game_data = response.json()
        #     plays = game_data.get('plays', [])
        #     faceoffs = [play for play in plays if play.get('typeCode') == 502]  # faceoff
        #     with open(f'faceoff_data/{game}_faceoff_data.json', 'w') as out_f:
        #         json.dump(faceoffs, out_f, indent=4)

        # 2) Boxscore -> time on ice aggregation
        boxscore_url = f"https://api-web.nhle.com/v1/gamecenter/{game}/boxscore"
        bs_response = requests.get(boxscore_url)
        if bs_response.status_code == 200:
            bs_data = bs_response.json()
            pbg = bs_data.get('playerByGameStats', {})

            def collect_team(team_obj):
                for group_key in ("forwards", "defense", "goalies"):
                    for p in team_obj.get(group_key, []) or []:
                        player_id = p.get("playerId")
                        if player_id is None:
                            continue
                        player_id = str(player_id)
                        name = (p.get("name") or {}).get("default")
                        if name:
                            player_names[player_id] = name
                        player_toi_seconds[player_id] = player_toi_seconds.get(player_id, 0) + toi_to_seconds(p.get("toi"))

            away = pbg.get("awayTeam", {})
            home = pbg.get("homeTeam", {})
            collect_team(away)
            collect_team(home)


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