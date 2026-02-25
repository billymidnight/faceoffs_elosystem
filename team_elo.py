import json
import logging
import os
import sys
from typing import List, Dict, Tuple


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


def compute_team_elo(player_ids: List[int], player_elos_dir: str = "player_elos", alpha: float = 0.8, beta: float = 0.2) -> Tuple[float, Dict[int, float], Dict[int, Dict]]:
    if len(player_ids) != 5:
        raise ValueError("Exactly 5 player ids must be provided")

    players = []
    for pid in player_ids:
        players.append(load_player(pid, player_elos_dir))

    elos = [p.get("elo", 0.0) for p in players]
    faceoffs = [p.get("faceoffs_taken", 0) or 0 for p in players]
    fpm = [faceoffs_per_minute(p) for p in players]

    sum_fpm = sum(fpm)
    sum_faceoffs = sum(faceoffs)

    if sum_fpm > 0:
        fpm_norm = [x / sum_fpm for x in fpm]
    else:
        fpm_norm = [1.0 / len(player_ids)] * len(player_ids)

    if sum_faceoffs > 0:
        faceoffs_norm = [x / sum_faceoffs for x in faceoffs]
    else:
        faceoffs_norm = [1.0 / len(player_ids)] * len(player_ids)

    # Ensure alpha+beta == 1.0 for clear weighting; normalize if not
    s = alpha + beta
    if s == 0:
        alpha, beta = 0.8, 0.2
    else:
        alpha, beta = alpha / s, beta / s

    weights = [alpha * f + beta * g for f, g in zip(fpm_norm, faceoffs_norm)]

    # Normalize weights to sum to 1 exactly
    w_sum = sum(weights)
    if w_sum <= 0:
        weights = [1.0 / len(weights)] * len(weights)
    else:
        weights = [w / w_sum for w in weights]

    team_elo = sum(e * w for e, w in zip(elos, weights))

    # Map player_id -> weight for debugging/inspection
    weight_map = {pid: w for pid, w in zip(player_ids, weights)}

    # Create a player info map for downstream logging/printing
    player_info = {}
    for pid, p, e, fo, fm, w in zip(player_ids, players, elos, faceoffs, fpm, weights):
        player_info[pid] = {
            "player_name": p.get("player_name"),
            "elo": float(e),
            "faceoffs_taken": int(fo),
            "faceoffs_per_minute": float(fm),
            "weight": float(w),
        }

    return float(team_elo), weight_map, player_info


def main(argv: List[str]):
    if len(argv) < 6:
        print("Usage: python team_elo.py <id1> <id2> <id3> <id4> <id5>")
        sys.exit(2)

    try:
        ids = [int(x) for x in argv[1:6]]
    except ValueError:
        print("Player ids must be integers")
        sys.exit(2)

    # configure logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("team_elo")

    try:
        elo, weights, player_info = compute_team_elo(ids)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Human-readable output + logging
    print(f"Team ELO: {elo:.4f}")
    print("Players:")
    for pid in ids:
        info = player_info.get(pid, {})
        name = info.get("player_name", "<unknown>")
        elo_p = info.get("elo", 0.0)
        fo = info.get("faceoffs_taken", 0)
        fpm_val = info.get("faceoffs_per_minute", 0.0)
        w = info.get("weight", 0.0)
        line = f"  {pid} - {name}: ELO={elo_p:.2f}, FO={fo}, FPM={fpm_val:.3f}, weight={w:.4f}"
        print(line)
        log.debug(line)

    log.info(f"Computed team ELO: {elo:.4f}")


if __name__ == "__main__":
    main(sys.argv)
