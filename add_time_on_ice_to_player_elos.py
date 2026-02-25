"""Add time-on-ice seconds from player_total_time_on_ice.json into player_elos files."""

import json
from pathlib import Path


TOI_JSON = Path("player_total_time_on_ice.json")
PLAYER_ELOS_DIR = Path("player_elos")


def main() -> None:
    with TOI_JSON.open("r") as f:
        player_total_toi = json.load(f)

    updated = 0

    for player_id, payload in player_total_toi.items():
        player_file = PLAYER_ELOS_DIR / f"{player_id}.json"
        if not player_file.exists():
            continue

        seconds = payload.get("toi_seconds")
        if seconds is None:
            continue

        with player_file.open("r") as f:
            player_data = json.load(f)

        player_data["time_on_ice_seconds"] = int(seconds)

        with player_file.open("w") as f:
            json.dump(player_data, f, indent=4)

        updated += 1

    print(f"Updated {updated} player files.")


if __name__ == "__main__":
    main()
