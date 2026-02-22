"""
Head-to-Head Analysis for NHL Faceoffs
Calculates player rivalries and team matchup records.
Outputs to head_to_head_stats/ folder.
"""

import json
from pathlib import Path
from collections import defaultdict


def run_head_to_head_analysis(faceoff_dir: str = "faceoff_data", output_dir: str = "head_to_head_stats"):
    """
    Analyze all faceoffs to build head-to-head records.
    """
    print("=" * 60)
    print("HEAD-TO-HEAD ANALYSIS")
    print("=" * 60)
    print()
    
    faceoff_path = Path(faceoff_dir)
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Track player vs player matchups: {(player_a, player_b): {"a_wins": x, "b_wins": y}}
    # Always store with smaller ID first for consistency
    player_matchups = defaultdict(lambda: {"player_a_wins": 0, "player_b_wins": 0})
    
    # Track team vs team: {(team_a, team_b): {"a_wins": x, "b_wins": y}}
    team_matchups = defaultdict(lambda: {"team_a_wins": 0, "team_b_wins": 0})
    
    # We need to track which team each player is on per faceoff
    # eventOwnerTeamId is the winner's team
    
    print("Scanning all faceoff data...")
    game_files = sorted(faceoff_path.glob("*_faceoff_data.json"))
    
    for i, game_file in enumerate(game_files):
        with open(game_file, 'r') as f:
            faceoffs = json.load(f)
        
        for fo in faceoffs:
            details = fo.get("details", {})
            winner_id = details.get("winningPlayerId")
            loser_id = details.get("losingPlayerId")
            winner_team = details.get("eventOwnerTeamId")
            
            if not (winner_id and loser_id and winner_team):
                continue
            
            # Player matchup - always use sorted order for key consistency
            if winner_id < loser_id:
                key = (winner_id, loser_id)
                player_matchups[key]["player_a_wins"] += 1
            else:
                key = (loser_id, winner_id)
                player_matchups[key]["player_b_wins"] += 1
        
        if (i + 1) % 300 == 0:
            print(f"  Processed {i + 1}/{len(game_files)} games...")
    
    # For team matchups, we need to re-scan and figure out loser's team
    # We'll build a player->team mapping first from winner data
    print("\nBuilding team matchups...")
    
    player_teams = {}
    for game_file in game_files:
        with open(game_file, 'r') as f:
            faceoffs = json.load(f)
        for fo in faceoffs:
            details = fo.get("details", {})
            winner_id = details.get("winningPlayerId")
            winner_team = details.get("eventOwnerTeamId")
            if winner_id and winner_team:
                player_teams[winner_id] = winner_team
    
    # Now re-scan for team matchups
    for game_file in game_files:
        with open(game_file, 'r') as f:
            faceoffs = json.load(f)
        
        for fo in faceoffs:
            details = fo.get("details", {})
            winner_id = details.get("winningPlayerId")
            loser_id = details.get("losingPlayerId")
            winner_team = details.get("eventOwnerTeamId")
            
            if not (winner_id and loser_id and winner_team):
                continue
            
            # Get loser's team from our mapping
            loser_team = player_teams.get(loser_id)
            if not loser_team or loser_team == winner_team:
                continue
            
            # Team matchup - sorted order for key
            if winner_team < loser_team:
                key = (winner_team, loser_team)
                team_matchups[key]["team_a_wins"] += 1
            else:
                key = (loser_team, winner_team)
                team_matchups[key]["team_b_wins"] += 1
    
    # ==================== SAVE PLAYER RIVALRIES ====================
    print("\nProcessing player rivalries...")
    
    # Convert to list and add total + metadata
    rivalries = []
    for (player_a, player_b), record in player_matchups.items():
        total = record["player_a_wins"] + record["player_b_wins"]
        rivalries.append({
            "player_a": player_a,
            "player_b": player_b,
            "player_a_wins": record["player_a_wins"],
            "player_b_wins": record["player_b_wins"],
            "total_faceoffs": total
        })
    
    # Sort by total faceoffs (most common matchups)
    rivalries.sort(key=lambda x: x["total_faceoffs"], reverse=True)
    
    # Save all rivalries
    with open(output_path / "player_rivalries.json", 'w') as f:
        json.dump(rivalries, f, indent=2)
    
    # Save top 50 rivalries separately
    with open(output_path / "top_50_rivalries.json", 'w') as f:
        json.dump(rivalries[:50], f, indent=2)
    
    # ==================== SAVE TEAM MATCHUPS ====================
    print("Processing team matchups...")
    
    team_records = []
    for (team_a, team_b), record in team_matchups.items():
        total = record["team_a_wins"] + record["team_b_wins"]
        team_records.append({
            "team_a": team_a,
            "team_b": team_b,
            "team_a_wins": record["team_a_wins"],
            "team_b_wins": record["team_b_wins"],
            "total_faceoffs": total,
            "team_a_win_pct": round(record["team_a_wins"] / total * 100, 1) if total > 0 else 0
        })
    
    # Sort by total faceoffs
    team_records.sort(key=lambda x: x["total_faceoffs"], reverse=True)
    
    with open(output_path / "team_head_to_head.json", 'w') as f:
        json.dump(team_records, f, indent=2)
    
    # ==================== PRINT SUMMARY ====================
    print()
    print("-" * 60)
    print("TOP 5 PLAYER RIVALRIES (Most Faceoffs Against Each Other)")
    print("-" * 60)
    
    for i, r in enumerate(rivalries[:5], 1):
        print(f"  {i}. Player {r['player_a']} vs {r['player_b']}")
        print(f"     Record: {r['player_a_wins']}-{r['player_b_wins']} ({r['total_faceoffs']} total)")
        print()
    
    print("-" * 60)
    print("TOP 10 TEAM MATCHUPS BY FACEOFF COUNT")
    print("-" * 60)
    
    for i, t in enumerate(team_records[:10], 1):
        print(f"  {i}. Team {t['team_a']} vs Team {t['team_b']}")
        print(f"     Record: {t['team_a_wins']}-{t['team_b_wins']} (Team {t['team_a']} win%: {t['team_a_win_pct']}%)")
    
    print()
    print("=" * 60)
    print(f"FILES SAVED TO '{output_dir}/':")
    print(f"  - player_rivalries.json ({len(rivalries)} matchups)")
    print(f"  - top_50_rivalries.json")
    print(f"  - team_head_to_head.json ({len(team_records)} team pairs)")
    print("=" * 60)


if __name__ == "__main__":
    run_head_to_head_analysis()
