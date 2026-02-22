"""
Post-ELO Statistics Calculator
Analyzes player ELOs and team averages after ELO calculation is complete.
"""

import json
from pathlib import Path
from collections import defaultdict


def load_all_player_elos(elo_dir: str = "player_elos") -> dict:
    """Load all player ELO data."""
    players = {}
    elo_path = Path(elo_dir)
    for elo_file in elo_path.glob("*.json"):
        with open(elo_file, 'r') as f:
            player = json.load(f)
            players[player['player_id']] = player
    return players


def build_player_team_mapping(faceoff_dir: str = "faceoff_data") -> dict:
    """
    Build a mapping of player_id -> team_id by scanning faceoff data.
    Uses the most recent team a player won a faceoff for.
    """
    player_teams = {}
    faceoff_path = Path(faceoff_dir)
    
    for game_file in sorted(faceoff_path.glob("*_faceoff_data.json")):
        with open(game_file, 'r') as f:
            faceoffs = json.load(f)
        
        for fo in faceoffs:
            details = fo.get("details", {})
            winner_id = details.get("winningPlayerId")
            team_id = details.get("eventOwnerTeamId")  # Winner's team
            
            if winner_id and team_id:
                player_teams[winner_id] = team_id
    
    return player_teams


def run_stats():
    """Calculate and display post-ELO statistics."""
    print("=" * 60)
    print("POST-ELO STATISTICS")
    print("=" * 60)
    print()
    
    # Load all player ELOs
    print("Loading player ELOs...")
    players = load_all_player_elos()
    print(f"Loaded {len(players)} players")
    
    # Build player -> team mapping
    print("Building player-team mapping from faceoff data...")
    player_teams = build_player_team_mapping()
    print(f"Mapped {len(player_teams)} players to teams")
    print()
    
    # ==================== TEAM AVERAGES ====================
    print("-" * 60)
    print("AVERAGE ELO BY TEAM")
    print("-" * 60)
    
    team_elos = defaultdict(list)
    for player_id, player_data in players.items():
        if player_id in player_teams:
            team_id = player_teams[player_id]
            team_elos[team_id].append(player_data['elo'])
    
    # Calculate averages and sort
    team_averages = []
    for team_id, elos in team_elos.items():
        avg_elo = sum(elos) / len(elos)
        team_averages.append((team_id, avg_elo, len(elos)))
    
    team_averages.sort(key=lambda x: x[1], reverse=True)
    
    for team_id, avg_elo, player_count in team_averages:
        print(f"  Team {team_id:>3} | Avg ELO: {avg_elo:>7.1f} | Players: {player_count}")
    
    print()
    
    # ==================== TOP 5 PLAYERS ====================
    print("-" * 60)
    print("TOP 5 PLAYERS (HIGHEST ELO)")
    print("-" * 60)
    
    sorted_players = sorted(players.values(), key=lambda x: x['elo'], reverse=True)
    
    for i, player in enumerate(sorted_players[:5], 1):
        team = player_teams.get(player['player_id'], "N/A")
        print(f"  {i}. Player {player['player_id']} | ELO: {player['elo']:>7.1f} | Faceoffs: {player['faceoffs_taken']:>4} | Team: {team}")
    
    print()
    
    # ==================== BOTTOM 5 PLAYERS ====================
    print("-" * 60)
    print("BOTTOM 5 PLAYERS (LOWEST ELO)")
    print("-" * 60)
    
    for i, player in enumerate(sorted_players[-5:], 1):
        team = player_teams.get(player['player_id'], "N/A")
        print(f"  {i}. Player {player['player_id']} | ELO: {player['elo']:>7.1f} | Faceoffs: {player['faceoffs_taken']:>4} | Team: {team}")
    
    print()
    
    # ==================== LOW FACEOFF COUNT ====================
    print("-" * 60)
    print("PLAYERS WITH < 10 FACEOFFS")
    print("-" * 60)
    
    low_faceoff_players = [p for p in players.values() if p['faceoffs_taken'] < 10]
    print(f"  Total players with < 10 faceoffs: {len(low_faceoff_players)}")
    print()
    print("  Breakdown:")
    for threshold in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
        count = len([p for p in players.values() if p['faceoffs_taken'] == threshold])
        if count > 0:
            print(f"    {threshold} faceoffs: {count} players")
    
    print()
    print("=" * 60)
    print("STATS COMPLETE!")
    print("=" * 60)


if __name__ == "__main__":
    run_stats()
