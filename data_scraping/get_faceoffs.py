import requests
import json

with open('game_nums.txt', 'r') as f:
    game_nums = f.read().splitlines()
    # game_nums = game_nums[0:10] # for testing, remove this line to get all games
    for game in game_nums:
        game_data_url = f"https://api-web.nhle.com/v1/gamecenter/{game}/play-by-play"
        response = requests.get(game_data_url)
        if response.status_code == 200:
            game_data = response.json()
            plays = game_data['plays']
            faceoffs = [play for play in plays if play['typeCode'] == 502] # play['typeDescKey'] == 'faceoff'
            with open(f'faceoff_data/{game}_faceoff_data.json', 'w') as f:
                json.dump(faceoffs, f, indent=4)