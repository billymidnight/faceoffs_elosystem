import requests

def get_player_info(player_num):
    response = requests.get(f"https://api-web.nhle.com/v1/player/{player_num}/landing")
    return response.json()['firstName']['default'] + " " + response.json()['lastName']['default']

print(get_player_info(8478402))