"""Live Faceoff Matchup Monitor

Fetches today's NHL games, lets the user pick one, then polls the
Sportradar PBP feed every 5 seconds to display on-ice players and
their Elo-based faceoff win probabilities.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

# ── sibling module imports ──────────────────────────────────────────
from get_game_ids import get_games_from_sportsradar
from on_ice import get_players_on_ice
from matchup_elo import (
    load_player,
    faceoffs_per_minute,
    win_probability,
    get_player_weights,
)

# ── resolve player_elos directory relative to this file ─────────────
PLAYER_ELOS_DIR = os.path.join(os.path.dirname(__file__), "..", "player_elos")


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _extract_player_id(player: dict) -> Optional[int]:
    """Try to pull an NHL player-id integer from a Sportradar player dict.

    Sportradar PBP player objects may carry:
      • ``reference``  – the NHL player id (string or int)
      • ``id``         – the SR UUID (not useful here)
      • ``sr_id``      – SR id string
    """
    for key in ("reference", "player_id", "id"):
        val = player.get(key)
        if val is None:
            continue
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    return None


def _player_display_name(player: dict) -> str:
    """Best-effort display name from a Sportradar player dict."""
    return (
        player.get("full_name")
        or player.get("name")
        or f"ID {player.get('reference') or player.get('id', '?')}"
    )


def _now_est() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%I:%M:%S %p ET")


def _probability_to_american_odds(prob: float) -> str:
    """Convert win probability (0..1) to an American odds string."""
    if prob <= 0.0:
        return "N/A"
    if prob >= 1.0:
        return "-INF"

    if prob >= 0.5:
        odds = -100.0 * prob / (1.0 - prob)
    else:
        odds = 100.0 * (1.0 - prob) / prob

    rounded = int(round(odds))
    if rounded > 0:
        return f"+{rounded}"
    return str(rounded)


def _format_game_state(period: Optional[int], clock: Optional[str],
                       status: Optional[str] = None) -> str:
    """Create a compact game-state label for headers/status lines."""
    period_txt = f"P{period}" if period is not None else "P?"
    clock_txt = clock if clock else "--:--"
    if status:
        return f"{period_txt} {clock_txt} ({status})"
    return f"{period_txt} {clock_txt}"


def _is_game_complete(clock: Optional[str], status: Optional[str]) -> bool:
    """Return True when the live feed indicates the game has ended."""
    if clock != "00:00":
        return False
    return True


# ─────────────────────────────────────────────────────────────────────
# Game selection
# ─────────────────────────────────────────────────────────────────────

def select_game(api_key: str) -> dict:
    """Fetch today's SportsRadar games and let the user pick one."""
    print("\n⏳  Fetching today's NHL schedule from SportsRadar …")
    games = get_games_from_sportsradar(api_key=api_key)

    if not games:
        print("No games found for today.")
        sys.exit(0)

    print(f"\n{'='*55}")
    print(f"{'TODAYS NHL GAMES':^55}")
    print(f"{'='*55}")
    for i, g in enumerate(games, start=1):
        away = g["away_team"]["name"] or "???"
        home = g["home_team"]["name"] or "???"
        t = g.get("start_time_common") or g.get("start_time_est") or "TBD"
        print(f"  {i}. {away:<22} @ {home:<22} {t}")
    print(f"{'='*55}")

    while True:
        try:
            choice = int(input(f"\nSelect a game (1-{len(games)}): "))
            if 1 <= choice <= len(games):
                return games[choice - 1]
        except (ValueError, EOFError):
            pass
        print("Invalid choice – try again.")


# ─────────────────────────────────────────────────────────────────────
# Matchup display
# ─────────────────────────────────────────────────────────────────────

def _load_elo_players(player_ids: List[int]) -> List[Dict]:
    """Load Elo records for a list of NHL player ids."""
    loaded = []
    for pid in player_ids:
        p = load_player(pid, player_elos_dir=PLAYER_ELOS_DIR)
        if p is not None:
            loaded.append(p)
    return loaded


def display_matchup(home_raw: list, away_raw: list,
                    home_name: str, away_name: str) -> None:
    """Print player names and Elo matchup analysis for the two teams."""

    # -- extract NHL ids -------------------------------------------------
    home_ids = [_extract_player_id(p) for p in home_raw]
    away_ids = [_extract_player_id(p) for p in away_raw]
    home_ids = [i for i in home_ids if i is not None]
    away_ids = [i for i in away_ids if i is not None]

    # -- print raw player lists -----------------------------------------
    print(f"\n{'─'*60}")
    print(f"  🏠  {home_name} – on ice")
    print(f"{'─'*60}")
    for p in home_raw:
        name = _player_display_name(p)
        pid = _extract_player_id(p)
        tag = f"  (#{pid})" if pid else ""
        print(f"    • {name}{tag}")

    print(f"\n{'─'*60}")
    print(f"  🚌  {away_name} – on ice")
    print(f"{'─'*60}")
    for p in away_raw:
        name = _player_display_name(p)
        pid = _extract_player_id(p)
        tag = f"  (#{pid})" if pid else ""
        print(f"    • {name}{tag}")

    # -- load Elo data ---------------------------------------------------
    home_elo_players = _load_elo_players(home_ids)
    away_elo_players = _load_elo_players(away_ids)

    if not home_elo_players or not away_elo_players:
        print("\n  ⚠  Not enough Elo data for a matchup analysis.")
        if not home_elo_players:
            print(f"     No Elo records found for {home_name} players on ice.")
        if not away_elo_players:
            print(f"     No Elo records found for {away_name} players on ice.")
        return

    # -- weights (suppress inner prints by temporarily redirecting) ------
    # We recalculate quietly, then print our own summary.
    _orig_stdout = sys.stdout
    sys.stdout = open(os.devnull, "w")
    try:
        home_weights = get_player_weights(home_elo_players, label=home_name)
        away_weights = get_player_weights(away_elo_players, label=away_name)
    finally:
        sys.stdout.close()
        sys.stdout = _orig_stdout

    # -- matchup table ---------------------------------------------------
    print(f"\n{'='*60}")
    print(f"{'FACEOFF ELO MATCHUP':^60}")
    print(f"{'='*60}")

    print(f"\n  {home_name} (Home)")
    for p, w in zip(home_elo_players, home_weights):
        fpm = faceoffs_per_minute(p)
        print(f"    {p['player_name']:<24} Elo {p['elo']:7.1f}  "
              f"FPM {fpm:5.2f}  Wt {w:5.1%}")

    print(f"\n  {away_name} (Away)")
    for p, w in zip(away_elo_players, away_weights):
        fpm = faceoffs_per_minute(p)
        print(f"    {p['player_name']:<24} Elo {p['elo']:7.1f}  "
              f"FPM {fpm:5.2f}  Wt {w:5.1%}")

    # -- overall probability ---------------------------------------------
    overall_home = 0.0
    print(f"\n{'─'*60}")
    print(f"  {'Home Player':>22}  vs  {'Away Player':<22}  P(Home)   Odds")
    print(f"{'─'*60}")
    for i, hp in enumerate(home_elo_players):
        for j, ap in enumerate(away_elo_players):
            p_win = win_probability(hp["elo"], ap["elo"])
            mw = home_weights[i] * away_weights[j]
            overall_home += p_win * mw
            p_odds = _probability_to_american_odds(p_win)
            print(f"  {hp['player_name']:>22}  vs  {ap['player_name']:<22}  "
                  f"{p_win:6.2%}  {p_odds:>5}  (wt {mw:5.2%})")

    home_odds = _probability_to_american_odds(overall_home)
    away_odds = _probability_to_american_odds(1 - overall_home)
    print(f"\n{'='*60}")
    print(f"  OVERALL  {home_name}: {overall_home:.2%}   "
          f"{away_name}: {1 - overall_home:.2%}")
    print(f"           Odds  {home_name}: {home_odds}   {away_name}: {away_odds}")
    print(f"{'='*60}")


# ─────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────

def monitor_loop(game: dict, api_key: str, interval: int = 5) -> None:
    """Poll on-ice data every *interval* seconds and show matchup."""
    sr_game_id = game.get("sr_game_id") or game.get("game_id")
    home_name = game["home_team"]["name"] or "Home"
    away_name = game["away_team"]["name"] or "Away"
    start_time = game.get("start_time_common") or game.get("start_time_est") or ""

    print(f"\n🏒  Monitoring: {away_name} @ {home_name}  ({start_time})")
    print(f"    SR Game ID: {sr_game_id}")
    print(f"    Polling every {interval}s – press Ctrl+C to stop.\n")

    prev_home_ids: set = set()
    prev_away_ids: set = set()

    while True:
        try:
            on_ice = get_players_on_ice(sr_game_id, api_key=api_key)
        except Exception as e:
            print(f"\n⚠  Error fetching on-ice data: {e}")
            print(f"   Will retry in {interval}s …")
            time.sleep(interval)
            continue

        home_players = on_ice.get("home", [])
        away_players = on_ice.get("away", [])
        game_clock = on_ice.get("clock")
        game_period = on_ice.get("period")
        game_status = on_ice.get("status")
        game_state = _format_game_state(game_period, game_clock, game_status)

        if _is_game_complete(game_clock, game_status):
            os.system("clear" if os.name != "nt" else "cls")
            print(f"🏁  {away_name} @ {home_name}  |  {game_state}")
            print("\nGame clock reached 00:00 and game is complete. Stopping monitor.")
            break

        # Detect if lineup changed so we don't spam identical output
        cur_home_ids = {_extract_player_id(p) for p in home_players} - {None}
        cur_away_ids = {_extract_player_id(p) for p in away_players} - {None}

        if cur_home_ids != prev_home_ids or cur_away_ids != prev_away_ids or not prev_home_ids:
            # Clear terminal for a fresh view
            os.system("clear" if os.name != "nt" else "cls")
            print(f"🏒  {away_name} @ {home_name}  |  {game_state}  |  Last updated: {_now_est()}")
            display_matchup(home_players, away_players, home_name, away_name)
            prev_home_ids = cur_home_ids
            prev_away_ids = cur_away_ids
        else:
            # Lineup unchanged – just update the timestamp line
            print(
                f"\r  ⏱  Last checked: {_now_est()}  |  {game_state}  (lineup unchanged)",
                end="",
                flush=True,
            )

        time.sleep(interval)

    print("👋  Live monitor exited.")


# ─────────────────────────────────────────────────────────────────────
# CLI entry-point
# ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live faceoff Elo matchup monitor for today's NHL games"
    )
    parser.add_argument(
        "--sportsradar-key",
        required=True,
        help="SportsRadar API key (trial v7)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Polling interval in seconds (default: 5)",
    )
    args = parser.parse_args()

    game = select_game(args.sportsradar_key)

    try:
        monitor_loop(game, args.sportsradar_key, interval=args.interval)
    except KeyboardInterrupt:
        print("\n\n👋  Monitoring stopped.")


if __name__ == "__main__":
    main()
