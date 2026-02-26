"""Visualizations for faceoffs per minute and cutoff elimination."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def load_players(player_elos_dir: Path) -> list[dict]:
    players = []
    for path in sorted(player_elos_dir.glob("*.json")):
        try:
            with path.open("r") as f:
                players.append(json.load(f))
        except Exception:
            continue
    return players


def compute_faceoffs_per_minute(player: dict) -> float | None:
    toi_seconds = player.get("time_on_ice_seconds")
    faceoffs = player.get("faceoffs_taken")
    if toi_seconds is None or faceoffs is None:
        return None
    if toi_seconds <= 0:
        return None
    return faceoffs / (toi_seconds / 60)


def load_faceoff_files(faceoff_dir: Path) -> list[Path]:
    return sorted(faceoff_dir.glob("*_faceoff_data.json"))


def count_faceoffs_by_player(faceoff_files: list[Path]) -> dict[int, int]:
    totals: dict[int, int] = {}
    for game_file in faceoff_files:
        with game_file.open("r") as f:
            faceoffs = json.load(f)
        for fo in faceoffs:
            details = fo.get("details", {})
            winner_id = details.get("winningPlayerId")
            loser_id = details.get("losingPlayerId")
            if not (winner_id and loser_id):
                continue
            totals[winner_id] = totals.get(winner_id, 0) + 1
            totals[loser_id] = totals.get(loser_id, 0) + 1
    return totals


def count_eliminated_faceoffs(
    faceoff_files: list[Path],
    player_totals: dict[int, int],
    cutoff: int,
) -> tuple[int, int]:
    total_faceoffs = 0
    eliminated = 0
    for game_file in faceoff_files:
        with game_file.open("r") as f:
            faceoffs = json.load(f)
        for fo in faceoffs:
            details = fo.get("details", {})
            winner_id = details.get("winningPlayerId")
            loser_id = details.get("losingPlayerId")
            if not (winner_id and loser_id):
                continue
            total_faceoffs += 1
            winner_total = player_totals.get(winner_id, 0)
            loser_total = player_totals.get(loser_id, 0)
            if winner_total < cutoff or loser_total < cutoff:
                eliminated += 1
    return eliminated, total_faceoffs


def parse_cutoffs(value: str) -> list[int]:
    cutoffs = [int(x.strip()) for x in value.split(",") if x.strip()]
    if not cutoffs:
        raise ValueError("No cutoffs provided")
    return cutoffs


def plot_faceoffs_per_minute(
    player_elos_dir: Path,
    *,
    top_n: int,
    min_faceoffs: int,
    output_prefix: str,
) -> None:
    players = load_players(player_elos_dir)
    rows = []
    for p in players:
        fpm = compute_faceoffs_per_minute(p)
        if fpm is None:
            continue
        if p.get("faceoffs_taken", 0) < min_faceoffs:
            continue
        rows.append(
            {
                "player_id": p.get("player_id"),
                "player_name": p.get("player_name", "Unknown"),
                "faceoffs_taken": p.get("faceoffs_taken", 0),
                "time_on_ice_seconds": p.get("time_on_ice_seconds", 0),
                "faceoffs_per_minute": fpm,
            }
        )

    if not rows:
        raise SystemExit("No players found with time_on_ice_seconds and faceoffs_taken.")

    rows.sort(key=lambda r: r["faceoffs_per_minute"], reverse=True)

    # Histogram
    values = [r["faceoffs_per_minute"] for r in rows]
    plt.figure(figsize=(10, 6))
    plt.hist(values, bins=30, color="#4C78A8", edgecolor="white")
    plt.title("Faceoffs per Minute Distribution")
    plt.xlabel("Faceoffs per Minute")
    plt.ylabel("Player Count")
    plt.tight_layout()
    hist_path = f"{output_prefix}_hist.png"
    plt.savefig(hist_path, dpi=200)
    plt.close()

    # Top-N bar chart
    top_rows = rows[: top_n]
    names = [r["player_name"] for r in top_rows][::-1]
    fpm_vals = [r["faceoffs_per_minute"] for r in top_rows][::-1]

    plt.figure(figsize=(12, 8))
    plt.barh(names, fpm_vals, color="#F58518")
    plt.title(f"Top {len(top_rows)} Faceoffs per Minute")
    plt.xlabel("Faceoffs per Minute")
    plt.tight_layout()
    bar_path = f"{output_prefix}_top{len(top_rows)}.png"
    plt.savefig(bar_path, dpi=200)
    plt.close()

    print(f"Saved: {hist_path}")
    print(f"Saved: {bar_path}")


def plot_cutoff_elimination(
    faceoff_dir: Path,
    *,
    cutoffs: list[int],
    output: str,
) -> None:
    faceoff_files = load_faceoff_files(faceoff_dir)
    if not faceoff_files:
        raise SystemExit(f"No faceoff files found in: {faceoff_dir}")

    player_totals = count_faceoffs_by_player(faceoff_files)

    eliminated_counts = []
    total_faceoffs = 0
    for cutoff in cutoffs:
        eliminated, total_faceoffs = count_eliminated_faceoffs(
            faceoff_files,
            player_totals,
            cutoff,
        )
        eliminated_counts.append(eliminated)

    plt.figure(figsize=(10, 6))
    labels = [str(c) for c in cutoffs]
    plt.bar(labels, eliminated_counts, color="#4C78A8")
    plt.title("Eliminated Faceoffs by Minimum Faceoffs Cutoff")
    plt.xlabel("Minimum Faceoffs per Player")
    plt.ylabel("Eliminated Faceoffs (count)")
    plt.tight_layout()
    plt.savefig(output, dpi=200)
    plt.close()

    print(f"Total faceoffs considered: {total_faceoffs}")
    for cutoff, eliminated in zip(cutoffs, eliminated_counts, strict=True):
        print(f"Cutoff {cutoff:>3}: eliminated {eliminated}")
    print(f"Saved: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate faceoffs-per-minute plots and/or eliminated-faceoffs-by-cutoff plot."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["fpm", "cutoff", "both"],
        default="both",
        help="Which plot(s) to generate",
    )
    parser.add_argument(
        "--player-elos-dir",
        default="player_elos",
        help="Directory containing per-player JSON files",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=30,
        help="Number of top players (by faceoffs/min) to show in bar chart",
    )
    parser.add_argument(
        "--min-faceoffs",
        type=int,
        default=50,
        help="Minimum faceoffs taken to include a player",
    )
    parser.add_argument(
        "--output-prefix",
        default="faceoffs_per_minute",
        help="Output file prefix for faceoffs-per-minute plots",
    )
    parser.add_argument(
        "--faceoff-dir",
        default="faceoff_data",
        help="Directory containing *_faceoff_data.json files",
    )
    parser.add_argument(
        "--cutoffs",
        default="30,50,100,150,200",
        help="Comma-separated list of minimum faceoffs cutoffs",
    )
    parser.add_argument(
        "--output",
        default="faceoffs_eliminated_by_cutoff.png",
        help="Output image file name",
    )
    args = parser.parse_args()

    if args.mode in {"fpm", "both"}:
        player_elos_dir = Path(args.player_elos_dir)
        if not player_elos_dir.exists():
            raise SystemExit(f"Directory not found: {player_elos_dir}")
        plot_faceoffs_per_minute(
            player_elos_dir,
            top_n=args.top_n,
            min_faceoffs=args.min_faceoffs,
            output_prefix=args.output_prefix,
        )

    if args.mode in {"cutoff", "both"}:
        faceoff_dir = Path(args.faceoff_dir)
        if not faceoff_dir.exists():
            raise SystemExit(f"Directory not found: {faceoff_dir}")
        cutoffs = parse_cutoffs(args.cutoffs)
        plot_cutoff_elimination(
            faceoff_dir,
            cutoffs=cutoffs,
            output=args.output,
        )


if __name__ == "__main__":
    main()
