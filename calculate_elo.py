"""
ELO Calculator for NHL Faceoffs
Processes all games chronologically and updates player ELO ratings.
Keeps all data in memory for speed, writes to files only at the end.
"""

import json
from pathlib import Path


# ELO Configuration
K_FACTOR = 32  # How much ratings change per faceoff
STARTING_ELO = 1500


def calculate_expected_score(rating_a: float, rating_b: float) -> float:
    """
    Calculate expected score for player A against player B.
    E = 1 / (1 + 10^((R_opp - R_self) / 400))
    """
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def update_elo(old_rating: float, expected: float, actual: float, k: float = K_FACTOR) -> float:
    """
    Update ELO rating based on result.
    R_new = R_old + K * (S - E)
    """
    return old_rating + k * (actual - expected)


def load_all_players(elo_dir: Path) -> dict:
    """Load all player data into memory."""
    players = {}
    for elo_file in elo_dir.glob("*.json"):
        with open(elo_file, 'r') as f:
            player = json.load(f)
            players[player['player_id']] = player
    return players


def save_all_players(players: dict, elo_dir: Path):
    """Save all player data to files."""
    for player_id, player_data in players.items():
        filepath = elo_dir / f"{player_id}.json"
        with open(filepath, 'w') as f:
            json.dump(player_data, f, indent=4)


def process_faceoff(winner_id: int, loser_id: int, zone_code: str, players: dict):
    """
    Process a single faceoff and update both players' ELOs in memory.
    """
    winner_data = players[winner_id]
    loser_data = players[loser_id]
    
    # Get current ELOs
    winner_elo = winner_data['elo']
    loser_elo = loser_data['elo']
    
    # Calculate expected scores
    winner_expected = calculate_expected_score(winner_elo, loser_elo)
    loser_expected = calculate_expected_score(loser_elo, winner_elo)
    
    # Update ELOs (winner got S=1, loser got S=0)
    winner_data['elo'] = update_elo(winner_elo, winner_expected, 1)
    loser_data['elo'] = update_elo(loser_elo, loser_expected, 0)
    
    # Update faceoff counts
    winner_data['faceoffs_taken'] += 1
    loser_data['faceoffs_taken'] += 1
    
    # Update zone counts (zone is from winner's perspective)
    if zone_code == "N":
        winner_data['neutral_faceoffs'] += 1
        loser_data['neutral_faceoffs'] += 1
    elif zone_code == "O":
        winner_data['offensive_faceoffs'] += 1
        loser_data['defensive_faceoffs'] += 1
    elif zone_code == "D":
        winner_data['defensive_faceoffs'] += 1
        loser_data['offensive_faceoffs'] += 1


def run_elo_calculation(faceoff_dir: str = "faceoff_data", elo_dir: str = "player_elos"):
    """
    Process all games chronologically and update all player ELOs.
    """
    faceoff_path = Path(faceoff_dir)
    elo_path = Path(elo_dir)
    
    print("=" * 60)
    print("NHL FACEOFF ELO CALCULATOR")
    print(f"K-Factor: {K_FACTOR}")
    print(f"Starting ELO: {STARTING_ELO}")
    print("=" * 60)
    print()
    
    # Load all players into memory
    print("Loading all player data into memory...")
    players = load_all_players(elo_path)
    print(f"Loaded {len(players)} players")
    print()
    
    # Get all game files sorted chronologically
    game_files = sorted(faceoff_path.glob("*_faceoff_data.json"))
    total_games = len(game_files)
    total_faceoffs = 0
    
    for i, game_file in enumerate(game_files):
        # Load game faceoffs
        with open(game_file, 'r') as f:
            faceoffs = json.load(f)
        
        # Process each faceoff in the game
        for fo in faceoffs:
            details = fo.get("details", {})
            winner_id = details.get("winningPlayerId")
            loser_id = details.get("losingPlayerId")
            zone_code = details.get("zoneCode", "N")
            
            if winner_id and loser_id:
                process_faceoff(winner_id, loser_id, zone_code, players)
                total_faceoffs += 1
        
        # Progress update every 200 games
        if (i + 1) % 200 == 0 or (i + 1) == total_games:
            print(f"Processed {i + 1}/{total_games} games ({total_faceoffs:,} faceoffs)")
    
    print()
    print("Saving all player data to files...")
    save_all_players(players, elo_path)
    print("Saved!")
    
    print()
    print("=" * 60)
    print("ELO CALCULATION COMPLETE!")
    print(f"Total games processed: {total_games:,}")
    print(f"Total faceoffs processed: {total_faceoffs:,}")
    print("=" * 60)
    
    # Show top 10 players by final ELO
    print()
    print("TOP 10 PLAYERS BY FINAL ELO:")
    print("-" * 40)
    
    sorted_players = sorted(players.values(), key=lambda x: x['elo'], reverse=True)
    
    for i, player in enumerate(sorted_players[:10], 1):
        print(f"  {i:2}. Player {player['player_id']} | ELO: {player['elo']:.1f} | Faceoffs: {player['faceoffs_taken']}")
    
    print()
    print("BOTTOM 10 PLAYERS BY FINAL ELO:")
    print("-" * 40)
    
    for i, player in enumerate(sorted_players[-10:], 1):
        print(f"  {i:2}. Player {player['player_id']} | ELO: {player['elo']:.1f} | Faceoffs: {player['faceoffs_taken']}")


if __name__ == "__main__":
    run_elo_calculation()
