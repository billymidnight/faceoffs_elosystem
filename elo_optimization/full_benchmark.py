"""
Full Dataset Benchmark - K=32
Train on ALL games, evaluate log loss on ALL games.
This is an overfitting benchmark (not a real validation).
"""

import json
import math
from pathlib import Path


def calculate_expected_score(rating_a: float, rating_b: float) -> float:
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def update_elo(old_rating: float, expected: float, actual: float, k: float) -> float:
    return old_rating + k * (actual - expected)


def log_loss_single(predicted_prob: float, actual: int) -> float:
    eps = 1e-15
    predicted_prob = max(eps, min(1 - eps, predicted_prob))
    if actual == 1:
        return -math.log(predicted_prob)
    else:
        return -math.log(1 - predicted_prob)


def run_full_benchmark(k_value: int = 32, faceoff_dir: str = "faceoff_data"):
    print("=" * 60)
    print(f"FULL DATASET BENCHMARK - K={k_value}")
    print("Train on ALL, Test on ALL (overfit benchmark)")
    print("=" * 60)
    
    faceoff_path = Path(faceoff_dir)
    all_games = sorted(faceoff_path.glob("*_faceoff_data.json"))
    
    print(f"\nTotal games: {len(all_games)}")
    
    # ==================== PHASE 1: TRAIN ON EVERYTHING ====================
    print(f"\nPhase 1: Training on ALL games with K={k_value}...")
    
    players = {}
    
    def get_or_create_player(player_id):
        if player_id not in players:
            players[player_id] = {
                "player_id": player_id,
                "elo": 1500,
                "faceoffs_taken": 0,
                "offensive_faceoffs": 0,
                "defensive_faceoffs": 0,
                "neutral_faceoffs": 0
            }
        return players[player_id]
    
    train_faceoffs = 0
    for i, game_file in enumerate(all_games):
        with open(game_file, 'r') as f:
            faceoffs = json.load(f)
        
        for fo in faceoffs:
            details = fo.get("details", {})
            winner_id = details.get("winningPlayerId")
            loser_id = details.get("losingPlayerId")
            zone_code = details.get("zoneCode", "N")
            
            if not (winner_id and loser_id):
                continue
            
            winner = get_or_create_player(winner_id)
            loser = get_or_create_player(loser_id)
            
            winner_expected = calculate_expected_score(winner['elo'], loser['elo'])
            loser_expected = calculate_expected_score(loser['elo'], winner['elo'])
            
            winner['elo'] = update_elo(winner['elo'], winner_expected, 1, k_value)
            loser['elo'] = update_elo(loser['elo'], loser_expected, 0, k_value)
            
            winner['faceoffs_taken'] += 1
            loser['faceoffs_taken'] += 1
            
            if zone_code == "N":
                winner['neutral_faceoffs'] += 1
                loser['neutral_faceoffs'] += 1
            elif zone_code == "O":
                winner['offensive_faceoffs'] += 1
                loser['defensive_faceoffs'] += 1
            elif zone_code == "D":
                winner['defensive_faceoffs'] += 1
                loser['offensive_faceoffs'] += 1
            
            train_faceoffs += 1
        
        if (i + 1) % 500 == 0:
            print(f"  Trained on {i + 1}/{len(all_games)} games...")
    
    print(f"Training complete: {train_faceoffs} faceoffs, {len(players)} players")
    
    # Save ELOs
    output_dir = Path(f"full_k={k_value}_elos")
    output_dir.mkdir(exist_ok=True)
    for pid, pdata in players.items():
        with open(output_dir / f"{pid}.json", 'w') as f:
            json.dump(pdata, f, indent=4)
    print(f"Saved to '{output_dir}/'")
    
    # ==================== PHASE 2: LOG LOSS ON EVERYTHING ====================
    print(f"\nPhase 2: Evaluating log loss on ALL games using final ELOs...")
    
    total_log_loss = 0
    valid_predictions = 0
    
    for game_file in all_games:
        with open(game_file, 'r') as f:
            faceoffs = json.load(f)
        
        for fo in faceoffs:
            details = fo.get("details", {})
            winner_id = details.get("winningPlayerId")
            loser_id = details.get("losingPlayerId")
            
            if not (winner_id and loser_id):
                continue
            if winner_id not in players or loser_id not in players:
                continue
            
            winner_elo = players[winner_id]['elo']
            loser_elo = players[loser_id]['elo']
            
            predicted_prob = calculate_expected_score(winner_elo, loser_elo)
            loss = log_loss_single(predicted_prob, 1)
            total_log_loss += loss
            valid_predictions += 1
    
    avg_log_loss = total_log_loss / valid_predictions if valid_predictions > 0 else float('inf')
    
    # ==================== RESULTS ====================
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"K-Value: {k_value}")
    print(f"Total faceoffs trained: {train_faceoffs}")
    print(f"Total faceoffs evaluated: {valid_predictions}")
    print(f"Log Loss: {avg_log_loss:.6f}")
    print(f"Random baseline: 0.693147")
    print(f"Beat random: {'YES' if avg_log_loss < 0.693 else 'NO'}")
    
    # Top/Bottom 5
    sorted_p = sorted(players.values(), key=lambda x: x['elo'], reverse=True)
    print(f"\nTop 5 ELOs:")
    for i, p in enumerate(sorted_p[:5], 1):
        print(f"  {i}. Player {p['player_id']} | ELO: {p['elo']:.1f} | Faceoffs: {p['faceoffs_taken']}")
    
    print(f"\nBottom 5 ELOs:")
    for i, p in enumerate(sorted_p[-5:], 1):
        print(f"  {i}. Player {p['player_id']} | ELO: {p['elo']:.1f} | Faceoffs: {p['faceoffs_taken']}")
    
    # Save findings
    findings_file = Path("full_benchmark_findings.txt")
    with open(findings_file, 'w') as f:
        f.write("FULL DATASET BENCHMARK\n")
        f.write("Train on ALL, Test on ALL (overfit benchmark)\n")
        f.write(f"{'='*50}\n\n")
        f.write(f"K-Value: {k_value}\n")
        f.write(f"Total games: {len(all_games)}\n")
        f.write(f"Total faceoffs trained: {train_faceoffs}\n")
        f.write(f"Total faceoffs evaluated: {valid_predictions}\n")
        f.write(f"Total players: {len(players)}\n\n")
        f.write(f"LOG LOSS: {avg_log_loss:.6f}\n")
        f.write(f"Random baseline: 0.693147\n")
        f.write(f"Beat random: {'YES' if avg_log_loss < 0.693 else 'NO'}\n\n")
        f.write(f"NOTE: This is an overfit benchmark. The model saw all the\n")
        f.write(f"data it's being tested on, so log loss SHOULD be lower\n")
        f.write(f"than the 80/20 split. If it's not much lower, that means\n")
        f.write(f"faceoffs are inherently very noisy/random events.\n")
    
    print(f"\nFindings saved to '{findings_file}'")


if __name__ == "__main__":
    run_full_benchmark(k_value=32)
