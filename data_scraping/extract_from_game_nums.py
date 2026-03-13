import json
from pathlib import Path
from typing import Dict, Any, List

import requests


BASE_DIR = Path(__file__).resolve().parents[1]
GAME_NUMS_FILE = Path(__file__).resolve().parent / "game_nums.txt"
OUTPUT_DIR = BASE_DIR / "faceoff_data"
FAILED_LOG_FILE = Path(__file__).resolve().parent / "failed_game_ids.txt"


def toi_to_seconds(toi_str: str) -> int:
    if not toi_str:
        return 0

    parts = toi_str.split(":")
    try:
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + int(seconds)
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    except ValueError:
        return 0

    return 0


def seconds_to_hhmmss(total_seconds: int) -> str:
    if total_seconds < 0:
        total_seconds = 0
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def get_faceoffs_for_game(game_id: str) -> List[Dict[str, Any]]:
    game_data_url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
    response = requests.get(game_data_url, timeout=20)
    response.raise_for_status()

    game_data = response.json()
    plays = game_data.get("plays", [])
    return [play for play in plays if play.get("typeCode") == 502]


def get_player_toi_for_game(game_id: str) -> Dict[str, Dict[str, Any]]:
    boxscore_url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
    response = requests.get(boxscore_url, timeout=20)
    response.raise_for_status()

    data = response.json()
    pbg = data.get("playerByGameStats", {})
    player_toi: Dict[str, Dict[str, Any]] = {}

    def collect_team(team_obj: Dict[str, Any], team_side: str) -> None:
        for group_key in ("forwards", "defense", "goalies"):
            for player in team_obj.get(group_key, []) or []:
                player_id = player.get("playerId")
                if player_id is None:
                    continue

                pid = str(player_id)
                toi_seconds = toi_to_seconds(player.get("toi"))
                player_toi[pid] = {
                    "name": (player.get("name") or {}).get("default"),
                    "team": team_side,
                    "position": group_key[:-1],
                    "toi": seconds_to_hhmmss(toi_seconds),
                    "toi_seconds": toi_seconds,
                }

    collect_team(pbg.get("awayTeam", {}), "away")
    collect_team(pbg.get("homeTeam", {}), "home")

    return player_toi


def process_game(game_id: str) -> bool:
    try:
        faceoffs = get_faceoffs_for_game(game_id)
        player_toi = get_player_toi_for_game(game_id)
    except requests.RequestException as exc:
        print(f"{game_id}: request failed ({exc})")
        return False
    except Exception as exc:
        print(f"{game_id}: failed to process ({exc})")
        return False

    payload = {
        "game_id": game_id,
        "faceoffs": faceoffs,
        "player_time_on_ice": player_toi,
    }

    out_path = OUTPUT_DIR / f"{game_id}_faceoff_data.json"
    with out_path.open("w") as out_file:
        json.dump(payload, out_file, indent=4)

    print(f"{game_id}: wrote {out_path} (faceoffs={len(faceoffs)}, players={len(player_toi)})")
    return True


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not GAME_NUMS_FILE.exists():
        print(f"Missing game list: {GAME_NUMS_FILE}")
        return

    game_ids = [line.strip() for line in GAME_NUMS_FILE.read_text().splitlines() if line.strip()]
    if not game_ids:
        print("No game IDs found in game_nums.txt")
        return

    success_count = 0
    failed_game_ids: List[str] = []
    for game_id in game_ids:
        if process_game(game_id):
            success_count += 1
        else:
            failed_game_ids.append(game_id)

    if failed_game_ids:
        FAILED_LOG_FILE.write_text("\n".join(failed_game_ids) + "\n")
        print(f"Logged {len(failed_game_ids)} failed game IDs to {FAILED_LOG_FILE}")
    elif FAILED_LOG_FILE.exists():
        FAILED_LOG_FILE.unlink()

    print(f"Done. Successfully processed {success_count}/{len(game_ids)} games.")


if __name__ == "__main__":
    main()