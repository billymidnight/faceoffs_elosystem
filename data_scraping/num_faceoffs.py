import json

#pull in one of the faceoff data files to get the number of faceoffs in each game
with open('faceoff_data/2024010003_faceoff_data.json', 'r') as f:
    faceoff_data = json.load(f)
    num_faceoffs = len(faceoff_data)
    print(f"Number of faceoffs in game 2024010003: {num_faceoffs}")