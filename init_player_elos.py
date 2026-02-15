"""
Initialize player ELO files for all unique players in the faceoff data.
Creates a JSON file per player with starting ELO of 1500 and zeroed stats.
"""

import json
import os
from pathlib import Path


def get_all_unique_players(faceoff_dir: str = "faceoff_data") -> set:
    """Extract all unique player IDs from faceoff data."""
    all_players = set()
    
    faceoff_path = Path(faceoff_dir)
    json_files = sorted(faceoff_path.glob("*_faceoff_data.json"))
    
    print(f"Scanning {len(json_files)} game files...")
    
    for json_file in json_files:
        with open(json_file, 'r') as f:
            game_faceoffs = json.load(f)
            for fo in game_faceoffs:
                details = fo.get("details", {})
                winner_id = details.get("winningPlayerId")
                loser_id = details.get("losingPlayerId")
                
                if winner_id:
                    all_players.add(winner_id)
                if loser_id:
                    all_players.add(loser_id)
    
    return all_players


def create_player_elo_files(output_dir: str = "player_elos"):
    """Create individual JSON files for each player with initial values."""
    
    # Get all unique players
    all_players = get_all_unique_players()
    print(f"\nFound {len(all_players)} unique players")
    
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Create a JSON file for each player
    for player_id in sorted(all_players):
        player_data = {
            "player_id": player_id,
            "elo": 1500,
            "faceoffs_taken": 0,
            "offensive_faceoffs": 0,
            "defensive_faceoffs": 0,
            "neutral_faceoffs": 0
        }
        
        filepath = output_path / f"{player_id}.json"
        with open(filepath, 'w') as f:
            json.dump(player_data, f, indent=4)
    
    print(f"Created {len(all_players)} player ELO files in '{output_dir}/'")
    print("\nAll players initialized with:")
    print("  - ELO: 1500")
    print("  - faceoffs_taken: 0")
    print("  - offensive_faceoffs: 0")
    print("  - defensive_faceoffs: 0")
    print("  - neutral_faceoffs: 0")


if __name__ == "__main__":
    create_player_elo_files()
