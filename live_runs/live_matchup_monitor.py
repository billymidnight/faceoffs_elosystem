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
FACEOFF_LOG_PATH = os.path.join(os.path.dirname(__file__), "faceoff_event_log.txt")


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


def _append_faceoff_log(
    log_path: str,
    event_description: str,
    game_state: str,
    away_name: str,
    home_name: str,
    monitor_lines: List[str],
    faceoff_number: Optional[int] = None,
) -> None:
    """Append a faceoff event snapshot to the log file."""
    timestamp = _now_est()
    faceoff_str = f" #{faceoff_number}" if faceoff_number else ""
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] FACEOFF EVENT{faceoff_str}\n")
        f.write(f"Game: {away_name} @ {home_name} | {game_state}\n")
        f.write(f"Description: {event_description}\n")
        f.write("Monitor snapshot:\n")
        for line in monitor_lines:
            f.write(f"{line}\n")
        f.write("\n" + "=" * 80 + "\n\n")


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


def _build_matchup_lines(home_raw: list, away_raw: list,
                         home_name: str, away_name: str) -> List[str]:
    """Build monitor lines for player lists and Elo matchup analysis."""
    lines: List[str] = []

    # -- extract NHL ids -------------------------------------------------
    home_ids = [_extract_player_id(p) for p in home_raw]
    away_ids = [_extract_player_id(p) for p in away_raw]
    home_ids = [i for i in home_ids if i is not None]
    away_ids = [i for i in away_ids if i is not None]

    # -- print raw player lists -----------------------------------------
    lines.append(f"\n{'─'*60}")
    lines.append(f"  🏠  {home_name} – on ice")
    lines.append(f"{'─'*60}")
    for p in home_raw:
        name = _player_display_name(p)
        pid = _extract_player_id(p)
        tag = f"  (#{pid})" if pid else ""
        lines.append(f"    • {name}{tag}")

    lines.append(f"\n{'─'*60}")
    lines.append(f"  🚌  {away_name} – on ice")
    lines.append(f"{'─'*60}")
    for p in away_raw:
        name = _player_display_name(p)
        pid = _extract_player_id(p)
        tag = f"  (#{pid})" if pid else ""
        lines.append(f"    • {name}{tag}")

    # -- load Elo data ---------------------------------------------------
    home_elo_players = _load_elo_players(home_ids)
    away_elo_players = _load_elo_players(away_ids)

    if not home_elo_players or not away_elo_players:
        lines.append("\n  ⚠  Not enough Elo data for a matchup analysis.")
        if not home_elo_players:
            lines.append(f"     No Elo records found for {home_name} players on ice.")
        if not away_elo_players:
            lines.append(f"     No Elo records found for {away_name} players on ice.")
        return lines

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
    lines.append(f"\n{'='*60}")
    lines.append(f"{'FACEOFF ELO MATCHUP':^60}")
    lines.append(f"{'='*60}")

    lines.append(f"\n  {home_name} (Home)")
    for p, w in zip(home_elo_players, home_weights):
        fpm = faceoffs_per_minute(p)
        lines.append(
            f"    {p['player_name']:<24} Elo {p['elo']:7.1f}  "
            f"FPM {fpm:5.2f}  Wt {w:5.1%}"
        )

    lines.append(f"\n  {away_name} (Away)")
    for p, w in zip(away_elo_players, away_weights):
        fpm = faceoffs_per_minute(p)
        lines.append(
            f"    {p['player_name']:<24} Elo {p['elo']:7.1f}  "
            f"FPM {fpm:5.2f}  Wt {w:5.1%}"
        )

    # -- overall probability ---------------------------------------------
    overall_home = 0.0
    lines.append(f"\n{'─'*60}")
    lines.append(f"  {'Home Player':>22}  vs  {'Away Player':<22}  P(Home)   Odds")
    lines.append(f"{'─'*60}")
    for i, hp in enumerate(home_elo_players):
        for j, ap in enumerate(away_elo_players):
            p_win = win_probability(hp["elo"], ap["elo"])
            mw = home_weights[i] * away_weights[j]
            overall_home += p_win * mw
            p_odds = _probability_to_american_odds(p_win)
            lines.append(
                f"  {hp['player_name']:>22}  vs  {ap['player_name']:<22}  "
                f"{p_win:6.2%}  {p_odds:>5}  (wt {mw:5.2%})"
            )

    home_odds = _probability_to_american_odds(overall_home)
    away_odds = _probability_to_american_odds(1 - overall_home)
    lines.append(f"\n{'='*60}")
    lines.append(
        f"  OVERALL  {home_name}: {overall_home:.2%}   "
        f"{away_name}: {1 - overall_home:.2%}"
    )
    lines.append(f"           Odds  {home_name}: {home_odds}   {away_name}: {away_odds}")
    lines.append(f"{'='*60}")

    return lines


def display_matchup(home_raw: list, away_raw: list,
                    home_name: str, away_name: str) -> List[str]:
    """Print and return monitor lines for player names and Elo matchup analysis."""
    lines = _build_matchup_lines(home_raw, away_raw, home_name, away_name)
    for line in lines:
        print(line)
    return lines


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
    logged_faceoff_keys: set = set()
    current_period = None
    period_faceoff_count = 0

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

        if game_period != current_period:
            current_period = game_period
            period_faceoff_count = 0

        game_status = on_ice.get("status")
        game_state = _format_game_state(game_period, game_clock, game_status)
        event_type = (on_ice.get("event_type") or "").lower()
        event_description = on_ice.get("event_description") or "(no description)"
        event_id = on_ice.get("event_id")

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
            monitor_lines = display_matchup(home_players, away_players, home_name, away_name)
            prev_home_ids = cur_home_ids
            prev_away_ids = cur_away_ids
        else:
            # Lineup unchanged – just update the timestamp line
            print(
                f"\r  ⏱  Last checked: {_now_est()}  |  {game_state}  (lineup unchanged)",
                end="",
                flush=True,
            )
            monitor_lines = _build_matchup_lines(home_players, away_players, home_name, away_name)

        if event_type == "faceoff":
            # Only count as new if the event ID is unique
            faceoff_key = str(event_id)
            if faceoff_key not in logged_faceoff_keys:
                period_faceoff_count += 1
                
                _append_faceoff_log(
                    FACEOFF_LOG_PATH,
                    event_description,
                    game_state,
                    away_name,
                    home_name,
                    monitor_lines,
                    faceoff_number=period_faceoff_count,
                )
                
                # Send the event to the local endpoint
                try:
                    import requests
                    payload = {
                        "event_id": event_id,
                        "description": event_description,
                        "on_ice": on_ice,
                        "faceoff_number": period_faceoff_count,
                        "game_period": game_period
                    }
                    requests.post("http://localhost:3000/faceoff", json=payload, timeout=3)
                except Exception as req_err:
                    print(f"  [Error sending faceoff to localhost:3000 -> {req_err}]")
                    
                logged_faceoff_keys.add(faceoff_key)

        # -- send state to web server --
        try:
            import requests
            state_payload = {
                "game_period": game_period,
                "game_clock": game_clock,
                "home_name": home_name,
                "away_name": away_name,
                "home_players": home_players,
                "away_players": away_players,
                "next_faceoff": period_faceoff_count + 1
            }
            requests.post("http://localhost:3000/state", json=state_payload, timeout=2)
        except Exception:
            pass

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
    parser.add_argument(
        "--sr-game-id",
        help="Skip selection and use this game ID",
    )
    parser.add_argument(
        "--home-name",
        help="Home team name for non-interactive",
    )
    parser.add_argument(
        "--away-name",
        help="Away team name for non-interactive",
    )
    args = parser.parse_args()

    if args.sr_game_id:
        game = {
            "sr_game_id": args.sr_game_id,
            "home_team": {"name": args.home_name or "Home"},
            "away_team": {"name": args.away_name or "Away"},
            "start_time_common": "Live Server"
        }
    else:
        game = select_game(args.sportsradar_key)

    try:
        monitor_loop(game, args.sportsradar_key, interval=args.interval)
    except KeyboardInterrupt:
        print("\n\n👋  Monitoring stopped.")


if __name__ == "__main__":
    main()
