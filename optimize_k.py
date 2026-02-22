"""
K-Value Optimizer for NHL Faceoff ELO System
Tests different K values and evaluates with Log Loss.
"""

import json
import math
from pathlib import Path
from copy import deepcopy


def calculate_expected_score(rating_a: float, rating_b: float) -> float:
    """Calculate expected probability that player A wins."""
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def update_elo(old_rating: float, expected: float, actual: float, k: float) -> float:
    """Update ELO rating based on result."""
    return old_rating + k * (actual - expected)


def log_loss_single(predicted_prob: float, actual: int) -> float:
    """
    Calculate log loss for a single prediction.
    predicted_prob: probability that player A wins
    actual: 1 if player A won, 0 if player A lost
    """
    # Clip to avoid log(0)
    eps = 1e-15
    predicted_prob = max(eps, min(1 - eps, predicted_prob))
    
    if actual == 1:
        return -math.log(predicted_prob)
    else:
        return -math.log(1 - predicted_prob)


def run_k_optimization(k_value: int, faceoff_dir: str = "faceoff_data"):
    """
    Run ELO training and validation for a specific K value.
    """
    print(f"\n{'='*60}")
    print(f"RUNNING K = {k_value}")
    print(f"{'='*60}")
    
    faceoff_path = Path(faceoff_dir)
    
    # Get all games sorted chronologically
    all_games = sorted(faceoff_path.glob("*_faceoff_data.json"))
    total_games = len(all_games)
    
    # 80/20 split
    train_count = int(total_games * 0.8)
    train_games = all_games[:train_count]
    val_games = all_games[train_count:]
    
    print(f"Total games: {total_games}")
    print(f"Training games: {len(train_games)}")
    print(f"Validation games: {len(val_games)}")
    
    # Initialize all players with default ELO
    players = {}  # player_id -> {elo, faceoffs_taken, offensive, defensive, neutral}
    
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
    
    # ==================== TRAINING PHASE ====================
    print(f"\nTraining with K={k_value}...")
    
    train_faceoffs = 0
    for i, game_file in enumerate(train_games):
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
            
            # Calculate expected scores
            winner_expected = calculate_expected_score(winner['elo'], loser['elo'])
            loser_expected = calculate_expected_score(loser['elo'], winner['elo'])
            
            # Update ELOs
            winner['elo'] = update_elo(winner['elo'], winner_expected, 1, k_value)
            loser['elo'] = update_elo(loser['elo'], loser_expected, 0, k_value)
            
            # Update faceoff counts
            winner['faceoffs_taken'] += 1
            loser['faceoffs_taken'] += 1
            
            # Update zone counts
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
            print(f"  Trained on {i + 1}/{len(train_games)} games...")
    
    print(f"Training complete: {train_faceoffs} faceoffs processed")
    print(f"Players with ELO ratings: {len(players)}")
    
    # ==================== SAVE ELOs TO FOLDER ====================
    output_dir = Path(f"k={k_value}_elos")
    output_dir.mkdir(exist_ok=True)
    
    for player_id, player_data in players.items():
        filepath = output_dir / f"{player_id}.json"
        with open(filepath, 'w') as f:
            json.dump(player_data, f, indent=4)
    
    print(f"Saved {len(players)} player ELOs to '{output_dir}/'")
    
    # ==================== VALIDATION PHASE ====================
    print(f"\nValidating on {len(val_games)} games...")
    
    total_log_loss = 0
    valid_predictions = 0
    skipped_faceoffs = 0
    
    for game_file in val_games:
        with open(game_file, 'r') as f:
            faceoffs = json.load(f)
        
        for fo in faceoffs:
            details = fo.get("details", {})
            winner_id = details.get("winningPlayerId")
            loser_id = details.get("losingPlayerId")
            
            if not (winner_id and loser_id):
                continue
            
            # Skip if either player not in training data
            if winner_id not in players or loser_id not in players:
                skipped_faceoffs += 1
                continue
            
            # Get ELOs from training
            winner_elo = players[winner_id]['elo']
            loser_elo = players[loser_id]['elo']
            
            # Calculate predicted probability that winner wins
            # (We're predicting from winner's perspective since we know winner)
            predicted_prob = calculate_expected_score(winner_elo, loser_elo)
            
            # Actual outcome: winner won = 1
            loss = log_loss_single(predicted_prob, 1)
            total_log_loss += loss
            valid_predictions += 1
    
    avg_log_loss = total_log_loss / valid_predictions if valid_predictions > 0 else float('inf')
    
    print(f"\nValidation Results:")
    print(f"  Valid faceoffs evaluated: {valid_predictions}")
    print(f"  Skipped (unknown players): {skipped_faceoffs}")
    print(f"  Average Log Loss: {avg_log_loss:.6f}")
    print(f"  (Random baseline = 0.693)")
    
    # ==================== SAVE RESULTS ====================
    results = {
        "k_value": k_value,
        "train_games": len(train_games),
        "val_games": len(val_games),
        "train_faceoffs": train_faceoffs,
        "val_faceoffs_evaluated": valid_predictions,
        "val_faceoffs_skipped": skipped_faceoffs,
        "log_loss": avg_log_loss,
        "better_than_random": avg_log_loss < 0.693
    }
    
    # Append to findings file
    findings_file = Path("k_val_findings.txt")
    with open(findings_file, 'a') as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"K = {k_value}\n")
        f.write(f"{'='*50}\n")
        f.write(f"Training games: {len(train_games)}\n")
        f.write(f"Validation games: {len(val_games)}\n")
        f.write(f"Training faceoffs: {train_faceoffs}\n")
        f.write(f"Validation faceoffs evaluated: {valid_predictions}\n")
        f.write(f"Validation faceoffs skipped: {skipped_faceoffs}\n")
        f.write(f"LOG LOSS: {avg_log_loss:.6f}\n")
        f.write(f"Better than random (0.693): {'YES' if avg_log_loss < 0.693 else 'NO'}\n")
    
    print(f"\nResults appended to 'k_val_findings.txt'")
    
    return results


if __name__ == "__main__":
    # Clear findings file if starting fresh
    findings_file = Path("k_val_findings.txt")
    with open(findings_file, 'w') as f:
        f.write("K-VALUE OPTIMIZATION RESULTS\n")
        f.write("NHL Faceoff ELO System\n")
        f.write(f"80/20 Train/Validation Split\n")
    
    # Run for all K values: 5, 10, 15, 20, 25, 30, 35, 40, 45, 50
    all_results = []
    for k in range(5, 55, 5):
        result = run_k_optimization(k_value=k)
        all_results.append(result)
    
    # Print summary
    print(f"\n\n{'='*60}")
    print("FINAL SUMMARY - ALL K VALUES")
    print(f"{'='*60}")
    print(f"{'K':>4}  |  {'Log Loss':>10}  |  {'vs Random':>10}")
    print(f"{'-'*40}")
    
    best = min(all_results, key=lambda x: x['log_loss'])
    for r in all_results:
        marker = " <-- BEST" if r['k_value'] == best['k_value'] else ""
        print(f"  {r['k_value']:>2}  |  {r['log_loss']:.6f}  |  {'YES' if r['better_than_random'] else 'NO':>10}{marker}")
    
    print(f"\nBest K value: {best['k_value']} (Log Loss: {best['log_loss']:.6f})")
    
    # Append summary to findings file
    with open(findings_file, 'a') as f:
        f.write(f"\n\n{'='*50}\n")
        f.write("FINAL SUMMARY\n")
        f.write(f"{'='*50}\n")
        for r in all_results:
            marker = " <-- BEST" if r['k_value'] == best['k_value'] else ""
            f.write(f"K={r['k_value']:>2} | Log Loss: {r['log_loss']:.6f} | Beat Random: {'YES' if r['better_than_random'] else 'NO'}{marker}\n")
        f.write(f"\nBest K: {best['k_value']} (Log Loss: {best['log_loss']:.6f})\n")
