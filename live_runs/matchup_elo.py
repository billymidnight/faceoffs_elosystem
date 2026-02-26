import json
import os
import sys
from typing import List, Dict

def load_player(player_id: int, player_elos_dir: str = "player_elos") -> Dict:
    path = os.path.join(player_elos_dir, f"{player_id}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Player file not found: {path}")
    with open(path, "r") as fh:
        return json.load(fh)

def faceoffs_per_minute(player: Dict) -> float:
    seconds = player.get("time_on_ice_seconds", 0) or 0
    taken = player.get("faceoffs_taken", 0) or 0
    if seconds <= 0:
        return 0.0
    minutes = seconds / 60.0
    return taken / minutes

def win_probability(elo1: float, elo2: float) -> float:
    """Calculates the probability of player 1 winning against player 2."""
    return 1.0 / (1.0 + 10 ** ((elo2 - elo1) / 400.0))

def get_player_weights(players: List[Dict], alpha: float = 0.8, beta: float = 0.2, label: str = "Team") -> List[float]:
    """Calculates relative weights for players based on FPM and total faceoffs."""
    if not players:
        return []
    
    print(f"\n--- Weight Calculation Breakdown for {label} ---")
    if len(players) == 1:
        print(f"  Only one player ({players[0]['player_name']}). Weight = 1.0 (100%)")
        return [1.0]
        
    fpm = [faceoffs_per_minute(p) for p in players]
    faceoffs = [p.get("faceoffs_taken", 0) or 0 for p in players]
    
    sum_fpm = sum(fpm)
    sum_faceoffs = sum(faceoffs)
    
    # Normalize FPM
    if sum_fpm > 0:
        fpm_norm = [x / sum_fpm for x in fpm]
    else:
        fpm_norm = [1.0 / len(players)] * len(players)
        
    # Normalize Total Faceoffs
    if sum_faceoffs > 0:
        faceoffs_norm = [x / sum_faceoffs for x in faceoffs]
    else:
        faceoffs_norm = [1.0 / len(players)] * len(players)
        
    # Combine according to user requested weighting (0.8 / 0.2)
    weights = [alpha * f + beta * g for f, g in zip(fpm_norm, faceoffs_norm)]
    
    # Logging intermediate steps
    for i, p in enumerate(players):
        print(f"  Player: {p['player_name']}")
        print(f"    - Raw FPM: {fpm[i]:.4f} -> Norm FPM: {fpm_norm[i]:.2%}")
        print(f"    - Raw Faceoffs: {faceoffs[i]} -> Norm Faceoffs: {faceoffs_norm[i]:.2%}")
        print(f"    - Combined ({alpha}*FPM + {beta}*FO): {weights[i]:.4f}")

    # Final normalization to ensure they sum to 1.0
    w_sum = sum(weights)
    if w_sum <= 0:
        return [1.0 / len(players)] * len(players)
    
    final_weights = [w / w_sum for w in weights]
    if abs(w_sum - 1.0) > 1e-6:
        print(f"  Final Normalization (Sum was {w_sum:.4f}):")
        for i, p in enumerate(players):
            print(f"    - {p['player_name']}: {final_weights[i]:.2%}")

    return final_weights

def main():
    # Expected usage: python matchup_elo.py <id1> [id2 ...] vs <id3> [id4 ...]
    if "vs" not in sys.argv:
        print("Usage: python matchup_elo.py <id1> [id2 ...] vs <id3> [id4 ...]")
        print("Example: python matchup_elo.py 8470621 8471214 8478440 vs 8471675 8471685")
        return
    
    try:
        vs_idx = sys.argv.index("vs")
        team1_ids = [int(i) for i in sys.argv[1:vs_idx]]
        team2_ids = [int(i) for i in sys.argv[vs_idx+1:]]
    except ValueError:
        print("Error: Player IDs must be integers.")
        return
    
    if not team1_ids or not team2_ids:
        print("Error: Both sides must have at least one player.")
        return

    try:
        players1 = [load_player(pid) for pid in team1_ids]
        players2 = [load_player(pid) for pid in team2_ids]
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return

    # Calculate weights for each set of players
    weights1 = get_player_weights(players1, label="Team 1")
    weights2 = get_player_weights(players2, label="Team 2")
    
    print("\n" + "="*70)
    print(f"{'PLAYER MATCHUP ANALYSIS':^70}")
    print("="*70)
    
    print("\nTeam 1 Weights:")
    for p, w in zip(players1, weights1):
        print(f"  - {p['player_name']} ({p['player_id']}): {w:.1%} (Elo: {p['elo']:.1f}, FPM: {faceoffs_per_minute(p):.2f})")
        
    print("\nTeam 2 Weights:")
    for p, w in zip(players2, weights2):
        print(f"  - {p['player_name']} ({p['player_id']}): {w:.1%} (Elo: {p['elo']:.1f}, FPM: {faceoffs_per_minute(p):.2f})")

    print("\n" + "-"*70)
    print(f"{'Individual Matchups':^70}")
    print("-"*70)
    
    overall_p1_win = 0.0
    for i, p1 in enumerate(players1):
        for j, p2 in enumerate(players2):
            p1_win_prob = win_probability(p1['elo'], p2['elo'])
            
            # The joint probability of this specific pair meeting
            matchup_weight = weights1[i] * weights2[j]
            overall_p1_win += p1_win_prob * matchup_weight
            
            print(f"{p1['player_name']:>20} vs {p2['player_name']:<20} | P(Win): {p1_win_prob:6.2%} | Weight: {matchup_weight:6.2%}")
            
    print("="*70)
    print(f"OVERALL WIN PROBABILITY (Team 1): {overall_p1_win:.2%}")
    print(f"OVERALL WIN PROBABILITY (Team 2): {1.0 - overall_p1_win:.2%}")
    print("="*70)

if __name__ == "__main__":
    main()
