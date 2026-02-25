"""
K-Value Optimizer for NHL Faceoff ELO System
Tests different K values and evaluates with Log Loss.
"""

import argparse
import json
import math
from pathlib import Path
from functools import lru_cache
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


@lru_cache(maxsize=None)
def _get_games_and_total_faceoffs(faceoff_dir: str) -> tuple[tuple[Path, ...], int]:
    """Return chronological game files and total faceoff-row count (cached)."""
    faceoff_path = Path(faceoff_dir)
    all_games = tuple(sorted(faceoff_path.glob("*_faceoff_data.json")))
    total_faceoffs_all = 0
    for game_file in all_games:
        with open(game_file, 'r') as f:
            faceoffs = json.load(f)
        total_faceoffs_all += len(faceoffs)
    return all_games, total_faceoffs_all


@lru_cache(maxsize=None)
def _load_initial_players(initial_elo_dir: str) -> dict[int, dict]:
    """Load initial player JSONs from a directory (cached)."""
    elo_path = Path(initial_elo_dir)
    if not elo_path.exists() or not elo_path.is_dir():
        return {}

    players: dict[int, dict] = {}
    for elo_file in elo_path.glob("*.json"):
        try:
            with open(elo_file, 'r') as f:
                player = json.load(f)
        except Exception:
            # Skip unreadable/bad JSON files
            continue

        player_id = player.get("player_id")
        if player_id is None:
            continue

        # Ensure required keys exist (keep any extra metadata like name/team)
        player.setdefault("elo", 1500)
        player.setdefault("faceoffs_taken", 0)
        player.setdefault("offensive_faceoffs", 0)
        player.setdefault("defensive_faceoffs", 0)
        player.setdefault("neutral_faceoffs", 0)

        players[player_id] = player

    return players


def run_k_optimization(
    k_value: int,
    faceoff_dir: str = "faceoff_data",
    findings_file: str | Path = "k_val_findings.txt",
    initial_elo_dir: str | Path = "player_elos",
    min_faceoffs_per_minute: float | None = None,
):
    """
    Run ELO training and validation for a specific K value.
    """
    print(f"\n{'='*60}")
    print(f"RUNNING K = {k_value}")
    print(f"{'='*60}")
    
    # Get all games (chronological) and total faceoff rows (cached per directory)
    all_games, total_faceoffs_all = _get_games_and_total_faceoffs(faceoff_dir)
    total_games = len(all_games)

    # 80/20 split by NUMBER OF FACEOFFS (chronological), not by games.
    # This can split within a single game file.
    print(f"Total games: {total_games}")

    train_faceoffs_target = int(total_faceoffs_all * 0.8)
    val_faceoffs_target = total_faceoffs_all - train_faceoffs_target

    print(f"Total faceoffs (all games): {total_faceoffs_all}")
    print(f"Training faceoffs target (80%): {train_faceoffs_target}")
    print(f"Validation faceoffs target (20%): {val_faceoffs_target}")
    
    # Initialize players from disk (starting state)
    # Note: deep-copied per run so each K starts from the same baseline.
    players = deepcopy(_load_initial_players(str(initial_elo_dir)))
    
    def get_or_create_player(player_id):
        if player_id not in players:
            players[player_id] = {
                "player_id": player_id,
                "player_name": "Unknown Player",
                "player_team": "Unknown Team",
                "elo": 1500,
                "faceoffs_taken": 0,
                "offensive_faceoffs": 0,
                "defensive_faceoffs": 0,
                "neutral_faceoffs": 0,
                "time_on_ice_seconds": 0,
            }
        return players[player_id]

    def faceoffs_per_minute(player: dict) -> float:
        toi_seconds = player.get("time_on_ice_seconds", 0) or 0
        if toi_seconds <= 0:
            return 0.0
        return player.get("faceoffs_taken", 0) / (toi_seconds / 60)
    
    # ==================== TRAINING + VALIDATION (FACEOFF-BASED SPLIT) ====================
    print(f"\nTraining with K={k_value}...")

    train_games_set: set[Path] = set()
    val_games_set: set[Path] = set()

    train_faceoffs_assigned = 0  # raw faceoff rows assigned to training (includes any skipped rows)
    val_faceoffs_assigned = 0    # raw faceoff rows assigned to validation
    train_faceoffs_processed = 0  # valid rows processed into ELO
    val_faceoffs_processed = 0    # valid validation rows processed into ELO (online training)

    # Validation metrics
    total_log_loss = 0.0
    valid_predictions = 0
    skipped_faceoffs = 0
    skipped_low_faceoffs = 0
    skipped_low_faceoffs_per_minute = 0
    new_players_in_validation = 0

    training_complete = False

    output_dir = Path(f"k={k_value}_elos")
    output_dir.mkdir(exist_ok=True)

    for i, game_file in enumerate(all_games):
        with open(game_file, 'r') as f:
            faceoffs = json.load(f)

        for fo in faceoffs:
            # Decide whether this faceoff row goes to training or validation.
            if train_faceoffs_assigned < train_faceoffs_target:
                train_games_set.add(game_file)
                train_faceoffs_assigned += 1

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

                train_faceoffs_processed += 1
            else:
                # Transition: training is complete the first time we see a validation row.
                if not training_complete:
                    training_complete = True
                    print(
                        f"Training complete: {train_faceoffs_assigned} faceoff rows assigned "
                        f"({train_faceoffs_processed} processed into ELO)"
                    )
                    print(f"Players with ELO ratings: {len(players)}")
                    print(f"\nValidating on remaining faceoffs (target: {val_faceoffs_target})...")

                val_games_set.add(game_file)
                val_faceoffs_assigned += 1

                details = fo.get("details", {})
                winner_id = details.get("winningPlayerId")
                loser_id = details.get("losingPlayerId")
                zone_code = details.get("zoneCode", "N")

                if not (winner_id and loser_id):
                    continue

                # Online evaluation: predict with CURRENT ELOs, then update ELOs using the result.
                # Create players if they didn't appear in training (they'll start at the default ELO).
                if winner_id not in players:
                    get_or_create_player(winner_id)
                    new_players_in_validation += 1
                if loser_id not in players:
                    get_or_create_player(loser_id)
                    new_players_in_validation += 1

                winner = players[winner_id]
                loser = players[loser_id]

                # Apply the log-loss filter based on total faceoffs taken SO FAR (before this faceoff).
                winner_taken = winner.get('faceoffs_taken', 0)
                loser_taken = loser.get('faceoffs_taken', 0)

                # Predict probability (pre-update)
                predicted_prob = calculate_expected_score(winner['elo'], loser['elo'])

                if winner_taken > 50 and loser_taken > 50:
                    if min_faceoffs_per_minute is not None:
                        winner_fpm = faceoffs_per_minute(winner)
                        loser_fpm = faceoffs_per_minute(loser)
                        if winner_fpm < min_faceoffs_per_minute or loser_fpm < min_faceoffs_per_minute:
                            skipped_low_faceoffs_per_minute += 1
                        else:
                            loss = log_loss_single(predicted_prob, 1)
                            total_log_loss += loss
                            valid_predictions += 1
                    else:
                        loss = log_loss_single(predicted_prob, 1)
                        total_log_loss += loss
                        valid_predictions += 1
                else:
                    skipped_low_faceoffs += 1

                # Update ELOs (post-eval) and counts (continue training during validation)
                winner_expected = predicted_prob
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

                val_faceoffs_processed += 1

        if (i + 1) % 500 == 0 and train_faceoffs_assigned < train_faceoffs_target:
            print(f"  Scanned {i + 1}/{len(all_games)} games... (training faceoffs assigned: {train_faceoffs_assigned}/{train_faceoffs_target})")

    # If we never hit validation (e.g., no faceoffs), still report training completion.
    if not training_complete:
        print(
            f"Training complete: {train_faceoffs_assigned} faceoff rows assigned "
            f"({train_faceoffs_processed} processed into ELO)"
        )
        print(f"Players with ELO ratings: {len(players)}")

    # Save FINAL ELOs after training + online validation updates
    for player_id, player_data in players.items():
        filepath = output_dir / f"{player_id}.json"
        with open(filepath, 'w') as f:
            json.dump(player_data, f, indent=4)
    print(f"Saved {len(players)} player ELOs to '{output_dir}/'")
    
    avg_log_loss = total_log_loss / valid_predictions if valid_predictions > 0 else float('inf')
    
    print(f"\nValidation Results:")
    print(f"  Valid faceoffs evaluated: {valid_predictions}")
    print(f"  New players introduced during validation: {new_players_in_validation}")
    print(f"  Skipped (unknown players): {skipped_faceoffs}")
    print(f"  Skipped (<= 50 total faceoffs for either player): {skipped_low_faceoffs}")
    if min_faceoffs_per_minute is not None:
        print(
            f"  Skipped (faceoffs/min < {min_faceoffs_per_minute} for either player): "
            f"{skipped_low_faceoffs_per_minute}"
        )
    print(f"  Average Log Loss: {avg_log_loss:.6f}")
    print(f"  (Random baseline = 0.693)")
    
    # ==================== SAVE RESULTS ====================
    results = {
        "k_value": k_value,
        "total_games": total_games,
        "total_faceoffs": total_faceoffs_all,
        "train_games": len(train_games_set),
        "val_games": len(val_games_set),
        # Faceoff-based split bookkeeping
        "train_faceoffs_target": train_faceoffs_target,
        "val_faceoffs_target": val_faceoffs_target,
        "train_faceoffs_assigned": train_faceoffs_assigned,
        "val_faceoffs_assigned": val_faceoffs_assigned,
        # ELO training uses only valid rows with winner/loser ids
        "train_faceoffs": train_faceoffs_processed,
        "train_faceoffs_processed": train_faceoffs_processed,
        "val_faceoffs_processed": val_faceoffs_processed,
        "val_faceoffs_evaluated": valid_predictions,
        "val_faceoffs_skipped": skipped_faceoffs,
        "val_faceoffs_skipped_low_faceoffs": skipped_low_faceoffs,
        "val_faceoffs_skipped_low_faceoffs_per_minute": skipped_low_faceoffs_per_minute,
        "val_new_players": new_players_in_validation,
        "log_loss": avg_log_loss,
        "better_than_random": avg_log_loss < 0.693
    }
    
    # Append to findings file
    findings_path = Path(findings_file)
    with open(findings_path, 'a') as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"K = {k_value}\n")
        f.write(f"{'='*50}\n")
        f.write("Split method: 80/20 by FACEOFF COUNT (chronological)\n")
        f.write(f"Total games: {total_games}\n")
        f.write(f"Total faceoffs (rows): {total_faceoffs_all}\n")
        f.write(f"Training faceoffs target (rows): {train_faceoffs_target}\n")
        f.write(f"Validation faceoffs target (rows): {val_faceoffs_target}\n")
        f.write(f"Training games (contributed rows): {len(train_games_set)}\n")
        f.write(f"Validation games (contributed rows): {len(val_games_set)}\n")
        f.write(f"Training faceoffs assigned (rows): {train_faceoffs_assigned}\n")
        f.write(f"Validation faceoffs assigned (rows): {val_faceoffs_assigned}\n")
        f.write(f"Training faceoffs processed (valid): {train_faceoffs_processed}\n")
        f.write(f"Validation faceoffs processed (valid, online updates): {val_faceoffs_processed}\n")
        f.write(f"New players introduced during validation: {new_players_in_validation}\n")
        f.write(f"Validation faceoffs evaluated: {valid_predictions}\n")
        f.write(f"Validation faceoffs skipped (unknown players): {skipped_faceoffs}\n")
        f.write(f"Validation faceoffs skipped (<= 50 total faceoffs): {skipped_low_faceoffs}\n")
        if min_faceoffs_per_minute is not None:
            f.write(
                "Validation faceoffs skipped (faceoffs/min < "
                f"{min_faceoffs_per_minute}): {skipped_low_faceoffs_per_minute}\n"
            )
        f.write(f"LOG LOSS: {avg_log_loss:.6f}\n")
        f.write(f"Better than random (0.693): {'YES' if avg_log_loss < 0.693 else 'NO'}\n")
    
    print(f"\nResults appended to '{findings_path}'")
    
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optimize K for NHL faceoff ELO via validation log loss")
    parser.add_argument("--k-min", type=int, default=5, help="Minimum K (inclusive) when using a range")
    parser.add_argument("--k-max", type=int, default=50, help="Maximum K (inclusive) when using a range")
    parser.add_argument("--k-step", type=int, default=5, help="Step size when using a range")
    parser.add_argument(
        "--k-list",
        type=str,
        default="",
        help="Comma-separated list of K values (overrides --k-min/--k-max/--k-step). Example: 1,2,3,5,8",
    )
    parser.add_argument(
        "--findings-file",
        type=str,
        default="k_val_findings.txt",
        help="Path to findings output file",
    )
    parser.add_argument(
        "--faceoff-dir",
        type=str,
        default="faceoff_data",
        help="Directory containing *_faceoff_data.json files",
    )
    parser.add_argument(
        "--initial-elo-dir",
        type=str,
        default="player_elos",
        help="Directory containing initial per-player ELO JSONs (starting state)",
    )
    parser.add_argument(
        "--min-faceoffs-per-minute",
        type=float,
        default=None,
        help="If set, only evaluate validation rows where both players meet this faceoffs/min threshold",
    )
    args = parser.parse_args()

    # Determine K values to run
    if args.k_list.strip():
        k_values = [int(x.strip()) for x in args.k_list.split(",") if x.strip()]
    else:
        if args.k_step <= 0:
            raise ValueError("--k-step must be a positive integer")
        if args.k_max < args.k_min:
            raise ValueError("--k-max must be >= --k-min")
        k_values = list(range(args.k_min, args.k_max + 1, args.k_step))
    if not k_values:
        raise ValueError("No K values specified")

    # Clear findings file if starting fresh
    findings_file = Path(args.findings_file)
    with open(findings_file, 'w') as f:
        f.write("K-VALUE OPTIMIZATION RESULTS\n")
        f.write("NHL Faceoff ELO System\n")
        f.write("80/20 Train/Validation Split (by faceoff count, chronological)\n")
        f.write(f"K values: {k_values}\n")
        f.write(f"Initial ELO dir: {args.initial_elo_dir}\n")
    
    # Run optimization for selected K values
    all_results = []
    for k in k_values:
        result = run_k_optimization(
            k_value=k,
            faceoff_dir=args.faceoff_dir,
            findings_file=findings_file,
            initial_elo_dir=args.initial_elo_dir,
            min_faceoffs_per_minute=args.min_faceoffs_per_minute,
        )
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
