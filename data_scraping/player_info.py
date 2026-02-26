import requests
import json
from pathlib import Path


def print_progress(current, total, width=40):
    if total == 0:
        return
    filled = int(width * current / total)
    bar = "#" * filled + "-" * (width - filled)
    percent = (current / total) * 100
    print(f"\r[{bar}] {current}/{total} ({percent:5.1f}%)", end="", flush=True)

def get_player_info(player_num):
    response = requests.get(f"https://api-web.nhle.com/v1/player/{player_num}/landing")
    if response.status_code == 200:
        player_data = {}
        player_data["name"] = response.json()['firstName']['default'] + " " + response.json()['lastName']['default']
        player_data["team"] = response.json().get('fullTeamName', {}).get('default', 'No Team')
        player_data["position"] = response.json()['position']
        return player_data
    else:
        return {}

if __name__ == "__main__":
    player_elos_dir = Path(__file__).resolve().parent.parent / "player_elos"
    player_files = list(player_elos_dir.glob("*.json"))
    total_files = len(player_files)

    for idx, player_file in enumerate(player_files, start=1):
        try:
            with player_file.open("r", encoding="utf-8") as f:
                player_data = json.load(f)

            player_id = player_data.get("player_id")
            if player_id is None:
                continue
            
            player_info = get_player_info(player_id)
            player_data["player_name"] = player_info["name"]
            player_data["player_team"] = player_info["team"]
            player_data["position"] = player_info["position"]

            with player_file.open("w", encoding="utf-8") as f:
                json.dump(player_data, f, indent=4)

        except Exception as e:
            print(f"Failed to update {player_file.name}: {e}")

        print_progress(idx, total_files)

    if total_files > 0:
        print()
    print("Done updating player names, teams, and positions.")
