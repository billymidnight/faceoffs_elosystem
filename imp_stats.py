"""
Important Stats Calculator for NHL Faceoff ELO System
Analyzes faceoff_data folder to extract key statistics for 2024-25 season
"""

import json
import os
from collections import defaultdict
from pathlib import Path


def load_faceoff_data(faceoff_dir: str) -> tuple[list, int]:
    """
    Load all faceoff data from JSON files in the faceoff_data directory.
    
    Returns:
        Tuple of (all_faceoffs list, total_games count)
    """
    all_faceoffs = []
    game_count = 0
    
    faceoff_path = Path(faceoff_dir)
    json_files = sorted(faceoff_path.glob("*_faceoff_data.json"))
    
    for json_file in json_files:
        game_count += 1
        with open(json_file, 'r') as f:
            game_faceoffs = json.load(f)
            # Add game_id to each faceoff for tracking
            game_id = json_file.stem.replace("_faceoff_data", "")
            for fo in game_faceoffs:
                fo['game_id'] = game_id
            all_faceoffs.extend(game_faceoffs)
    
    return all_faceoffs, game_count


def calculate_stats(faceoff_dir: str = "faceoff_data"):
    """
    Calculate and print all important statistics.
    """
    print("=" * 60)
    print("NHL FACEOFF ELO SYSTEM - IMPORTANT STATISTICS")
    print("Season: 2024-2025")
    print("=" * 60)
    print()
    
    # Load all data
    print("Loading faceoff data...")
    all_faceoffs, total_games = load_faceoff_data(faceoff_dir)
    print(f"Data loaded successfully!\n")
    
    # ==================== BASIC COUNTS ====================
    total_faceoffs = len(all_faceoffs)
    
    # Track unique players (both winners and losers)
    all_players = set()
    player_faceoff_counts = defaultdict(int)  # total faceoffs per player
    player_games = defaultdict(set)  # games each player appeared in
    
    # Zone counts
    zone_counts = {"N": 0, "O": 0, "D": 0}
    player_zone_counts = defaultdict(lambda: {"N": 0, "O": 0, "D": 0})
    
    for fo in all_faceoffs:
        details = fo.get("details", {})
        winner_id = details.get("winningPlayerId")
        loser_id = details.get("losingPlayerId")
        zone = details.get("zoneCode", "N")
        game_id = fo.get("game_id")
        
        # Track players
        if winner_id:
            all_players.add(winner_id)
            player_faceoff_counts[winner_id] += 1
            player_games[winner_id].add(game_id)
            player_zone_counts[winner_id][zone] += 1
            
        if loser_id:
            all_players.add(loser_id)
            player_faceoff_counts[loser_id] += 1
            player_games[loser_id].add(game_id)
            # For loser, zone is inverted (O becomes D, D becomes O, N stays N)
            inverted_zone = {"O": "D", "D": "O", "N": "N"}.get(zone, "N")
            player_zone_counts[loser_id][inverted_zone] += 1
        
        # Zone totals
        if zone in zone_counts:
            zone_counts[zone] += 1
    
    total_unique_players = len(all_players)
    
    # ==================== AVERAGES ====================
    # Avg faceoffs per player (entire season)
    avg_faceoffs_per_player_season = sum(player_faceoff_counts.values()) / total_unique_players if total_unique_players > 0 else 0
    
    # Avg faceoffs per player per game
    # Sum of (player_faceoffs / games_played) for each player, then average
    player_avg_per_game = []
    for player_id in all_players:
        games_played = len(player_games[player_id])
        if games_played > 0:
            avg = player_faceoff_counts[player_id] / games_played
            player_avg_per_game.append(avg)
    
    avg_faceoffs_per_player_per_game = sum(player_avg_per_game) / len(player_avg_per_game) if player_avg_per_game else 0
    
    # ==================== TOP 5 PLAYERS ====================
    sorted_players = sorted(player_faceoff_counts.items(), key=lambda x: x[1], reverse=True)
    top_5_players = sorted_players[:5]
    
    # ==================== ZONE AVERAGES ====================
    # Average zone distribution per player
    total_n = sum(player_zone_counts[p]["N"] for p in all_players)
    total_o = sum(player_zone_counts[p]["O"] for p in all_players)
    total_d = sum(player_zone_counts[p]["D"] for p in all_players)
    
    avg_n_per_player = total_n / total_unique_players if total_unique_players > 0 else 0
    avg_o_per_player = total_o / total_unique_players if total_unique_players > 0 else 0
    avg_d_per_player = total_d / total_unique_players if total_unique_players > 0 else 0
    
    # ==================== PRINT RESULTS ====================
    print("-" * 60)
    print("BASIC COUNTS")
    print("-" * 60)
    print(f"Total Games Available (2024-25 season):     {total_games:,}")
    print(f"Total Unique Players:                       {total_unique_players:,}")
    print(f"Total Faceoffs (entire season):             {total_faceoffs:,}")
    print()
    
    print("-" * 60)
    print("AVERAGES")
    print("-" * 60)
    print(f"Avg Faceoffs per Player per Game:           {avg_faceoffs_per_player_per_game:.2f}")
    print(f"Avg Faceoffs per Player (entire season):    {avg_faceoffs_per_player_season:.2f}")
    print()
    
    print("-" * 60)
    print("TOP 5 PLAYERS BY FACEOFF COUNT")
    print("-" * 60)
    for i, (player_id, count) in enumerate(top_5_players, 1):
        games_played = len(player_games[player_id])
        print(f"  {i}. Player ID: {player_id:>10}  |  Faceoffs: {count:>5}  |  Games: {games_played}")
    print()
    
    print("-" * 60)
    print("ZONE BREAKDOWN (Total Faceoffs)")
    print("-" * 60)
    print(f"  Neutral Zone (N):    {zone_counts['N']:>6,} faceoffs")
    print(f"  Offensive Zone (O):  {zone_counts['O']:>6,} faceoffs")
    print(f"  Defensive Zone (D):  {zone_counts['D']:>6,} faceoffs")
    print()
    
    print("-" * 60)
    print("AVERAGE ZONE FACEOFFS PER PLAYER")
    print("-" * 60)
    print(f"  Avg Neutral (N) per player:    {avg_n_per_player:.2f}")
    print(f"  Avg Offensive (O) per player:  {avg_o_per_player:.2f}")
    print(f"  Avg Defensive (D) per player:  {avg_d_per_player:.2f}")
    print()
    
    print("=" * 60)
    print("Stats calculation complete!")
    print("=" * 60)


if __name__ == "__main__":
    calculate_stats()
