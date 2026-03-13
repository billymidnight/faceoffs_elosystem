import requests
import json

SEASON_START_DATE = "2024-10-01"
SEASON_END_DATE = "2025-06-17"

PREV_SEASON = 20242025
SEASON_NAME = 20252026

game_info_url = "https://api.nhle.com/stats/rest/en/game"
response = requests.get(game_info_url)
if response.status_code == 200:
    games = response.json().get("data", [])
    games = [
        game
        for game in games
        if SEASON_NAME == game["season"] or PREV_SEASON == game["season"]
    ]
    with open('game_nums.txt', 'w') as f:
        f.write("\n".join(str(game["id"]) for game in games))