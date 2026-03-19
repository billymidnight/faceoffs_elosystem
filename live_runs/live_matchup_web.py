"""Web UI for live faceoff matchup monitoring.

This app wraps the live matchup monitor in a Flask interface, allowing:
- game selection from today's Sportsradar schedule
- live polling of on-ice rosters and Elo matchup odds
- manual snapshot logging via button press
- automatic faceoff-time comparison against logged manual snapshots
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stdout
from threading import Lock
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template_string, request

from get_game_ids import get_games_from_sportsradar
from matchup_elo import (
    load_player,
    faceoffs_per_minute,
    win_probability,
    get_player_weights,
)
from on_ice import (
    get_players_on_ice,
    build_lineup_key,
    extract_player_id,
    probability_to_american_odds,
    log_manual_odds_snapshot,
    pick_manual_snapshot_for_faceoff,
    log_faceoff_odds_comparison,
)

PLAYER_ELOS_DIR = os.path.join(os.path.dirname(__file__), "..", "player_elos")
ODDS_LOG_PATH = os.path.join(os.path.dirname(__file__), "odds_comparison_log.jsonl")

app = Flask(__name__)

_STATE_LOCK = Lock()
_STATE: Dict[str, Any] = {
    "api_key": None,
    "game": None,
    "interval": 5,
    "manual_snapshots": [],
    "faceoff_keys": set(),
    "latest": None,
    "last_faceoff_comparison": None,
}


def _format_game_state(period: Optional[int], clock: Optional[str], status: Optional[str]) -> str:
    period_txt = f"P{period}" if period is not None else "P?"
    clock_txt = clock if clock else "--:--"
    if status:
        return f"{period_txt} {clock_txt} ({status})"
    return f"{period_txt} {clock_txt}"


def _load_elo_players(player_ids: List[int]) -> List[Dict[str, Any]]:
    loaded = []
    for pid in player_ids:
        p = load_player(pid, player_elos_dir=PLAYER_ELOS_DIR)
        if p is not None:
            loaded.append(p)
    return loaded


def _player_name(player: Dict[str, Any]) -> str:
    return (
        player.get("full_name")
        or player.get("name")
        or f"ID {player.get('reference') or player.get('id', '?')}"
    )


def _build_snapshot(home_raw: List[Dict[str, Any]], away_raw: List[Dict[str, Any]], home_name: str, away_name: str) -> Dict[str, Any]:
    home_ids = [pid for pid in (extract_player_id(p) for p in home_raw) if pid is not None]
    away_ids = [pid for pid in (extract_player_id(p) for p in away_raw) if pid is not None]

    home_elo_players = _load_elo_players(home_ids)
    away_elo_players = _load_elo_players(away_ids)

    report_lines: List[str] = []
    report_lines.append(f"{away_name} @ {home_name}")
    report_lines.append("-" * 72)

    report_lines.append(f"HOME ON ICE ({home_name}):")
    for p in home_raw:
        name = _player_name(p)
        pid = extract_player_id(p)
        tag = f" (#{pid})" if pid is not None else ""
        report_lines.append(f"  - {name}{tag}")

    report_lines.append("")
    report_lines.append(f"AWAY ON ICE ({away_name}):")
    for p in away_raw:
        name = _player_name(p)
        pid = extract_player_id(p)
        tag = f" (#{pid})" if pid is not None else ""
        report_lines.append(f"  - {name}{tag}")

    if not home_elo_players or not away_elo_players:
        report_lines.append("")
        report_lines.append("Not enough Elo data for matchup odds.")
        return {
            "ok": False,
            "lineup_key": build_lineup_key(home_raw, away_raw),
            "home_probability": None,
            "away_probability": None,
            "home_odds": "N/A",
            "away_odds": "N/A",
            "home_players": [_player_name(p) for p in home_raw],
            "away_players": [_player_name(p) for p in away_raw],
            "pairwise": [],
            "report": "\n".join(report_lines),
        }

    with redirect_stdout(io.StringIO()):
        home_weights = get_player_weights(home_elo_players, label=home_name)
        away_weights = get_player_weights(away_elo_players, label=away_name)

    overall_home = 0.0
    pairwise_rows: List[Dict[str, Any]] = []

    for i, hp in enumerate(home_elo_players):
        for j, ap in enumerate(away_elo_players):
            p_home = win_probability(hp["elo"], ap["elo"])
            weight = home_weights[i] * away_weights[j]
            overall_home += p_home * weight
            pairwise_rows.append(
                {
                    "home_player": hp["player_name"],
                    "away_player": ap["player_name"],
                    "home_probability": p_home,
                    "home_odds": probability_to_american_odds(p_home),
                    "weight": weight,
                }
            )

    overall_away = 1.0 - overall_home
    home_odds = probability_to_american_odds(overall_home)
    away_odds = probability_to_american_odds(overall_away)

    report_lines.append("")
    report_lines.append("ELO PROBABILITY SUMMARY:")
    report_lines.append(f"  {home_name}: {overall_home:.2%} ({home_odds})")
    report_lines.append(f"  {away_name}: {overall_away:.2%} ({away_odds})")

    return {
        "ok": True,
        "lineup_key": build_lineup_key(home_raw, away_raw),
        "home_probability": overall_home,
        "away_probability": overall_away,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "home_players": [_player_name(p) for p in home_raw],
        "away_players": [_player_name(p) for p in away_raw],
        "pairwise": pairwise_rows,
        "report": "\n".join(report_lines),
    }


def _poll_once() -> Dict[str, Any]:
    with _STATE_LOCK:
        api_key = _STATE.get("api_key")
        game = _STATE.get("game")

    if not api_key or not game:
        return {"ok": False, "error": "Monitor not started yet."}

    sr_game_id = game.get("sr_game_id") or game.get("game_id")
    home_name = game["home_team"]["name"] or "Home"
    away_name = game["away_team"]["name"] or "Away"

    on_ice = get_players_on_ice(sr_game_id, api_key=api_key)
    home_players = on_ice.get("home", [])
    away_players = on_ice.get("away", [])

    game_clock = on_ice.get("clock")
    game_period = on_ice.get("period")
    game_status = on_ice.get("status")
    game_state = _format_game_state(game_period, game_clock, game_status)

    snapshot = _build_snapshot(home_players, away_players, home_name, away_name)

    payload: Dict[str, Any] = {
        "ok": True,
        "game_id": sr_game_id,
        "home_name": home_name,
        "away_name": away_name,
        "game_state": game_state,
        "event_type": (on_ice.get("event_type") or "").lower(),
        "event_description": on_ice.get("event_description") or "",
        "event_id": on_ice.get("event_id"),
        "snapshot": snapshot,
    }

    if payload["event_type"] == "faceoff":
        faceoff_key = f"{payload['event_id']}|{payload['event_description']}|{game_period}|{game_clock}"
        with _STATE_LOCK:
            seen_faceoffs = _STATE["faceoff_keys"]
            if faceoff_key not in seen_faceoffs:
                manual_snapshot = pick_manual_snapshot_for_faceoff(
                    _STATE["manual_snapshots"],
                    snapshot["lineup_key"],
                )
                comparison = log_faceoff_odds_comparison(
                    log_path=ODDS_LOG_PATH,
                    game_id=str(sr_game_id),
                    home_name=home_name,
                    away_name=away_name,
                    game_state=game_state,
                    event_id=payload["event_id"],
                    event_description=payload["event_description"],
                    faceoff_lineup_key=snapshot["lineup_key"],
                    faceoff_home_probability=float(snapshot["home_probability"] or 0.0),
                    faceoff_away_probability=float(snapshot["away_probability"] or 0.0),
                    faceoff_home_odds=snapshot["home_odds"],
                    faceoff_away_odds=snapshot["away_odds"],
                    manual_snapshot=manual_snapshot,
                )
                seen_faceoffs.add(faceoff_key)
                _STATE["last_faceoff_comparison"] = comparison

    with _STATE_LOCK:
        _STATE["latest"] = payload
        payload["last_faceoff_comparison"] = _STATE.get("last_faceoff_comparison")

    return payload


@app.get("/")
def index() -> str:
    return render_template_string(
        """
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Live Faceoff Matchup Web Monitor</title>
  <style>
    :root {
      --bg: #f6f4ef;
      --panel: #ffffff;
      --ink: #1f2937;
      --accent: #0f766e;
      --line: #d6d3d1;
      --muted: #6b7280;
    }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at top left, #fff7ed 0%, var(--bg) 45%, #ecfeff 100%);
    }
    .wrap {
      max-width: 1060px;
      margin: 24px auto;
      padding: 0 16px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
      margin-bottom: 14px;
      box-shadow: 0 6px 18px rgba(31, 41, 55, 0.06);
    }
    h1 {
      margin: 0 0 10px 0;
      font-size: 1.45rem;
      letter-spacing: 0.02em;
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    input, select, button {
      font-size: 0.95rem;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    button {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      cursor: pointer;
    }
    button.secondary {
      background: #fff;
      color: var(--accent);
    }
    pre {
      white-space: pre-wrap;
      margin: 0;
      font-size: 0.9rem;
      line-height: 1.35;
      color: #111827;
    }
    .muted {
      color: var(--muted);
      font-size: 0.9rem;
    }
    .pill {
      display: inline-block;
      margin-left: 6px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 0.82rem;
    }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"panel\">
      <h1>Live Faceoff Matchup Web Monitor</h1>
      <div class=\"row\">
        <input id=\"apiKey\" placeholder=\"Sportsradar API Key\" size=\"40\" />
        <input id=\"interval\" type=\"number\" min=\"2\" value=\"5\" style=\"width: 90px\" />
        <button onclick=\"fetchGames()\">Fetch Today\'s Games</button>
      </div>
      <div class=\"row\" style=\"margin-top: 10px;\">
        <select id=\"games\" style=\"min-width: 560px;\"></select>
        <button onclick=\"startMonitor()\">Start Monitor</button>
        <button class=\"secondary\" onclick=\"logOddsNow()\">Log Odds Now</button>
      </div>
      <p id=\"statusMsg\" class=\"muted\"></p>
    </div>

    <div class=\"panel\">
      <div id=\"headline\" class=\"muted\">Waiting for monitor start.</div>
      <pre id=\"report\"></pre>
    </div>

    <div class=\"panel\">
      <strong>Last faceoff comparison</strong>
      <pre id=\"comparison\" class=\"muted\">None yet.</pre>
    </div>
  </div>

<script>
let cachedGames = [];
let timer = null;

function setStatus(msg) {
  document.getElementById("statusMsg").textContent = msg;
}

function renderComparison(comp) {
  const box = document.getElementById("comparison");
  if (!comp) {
    box.textContent = "None yet.";
    return;
  }
  const manual = comp.manual_snapshot;
  const lines = [];
  lines.push(`Faceoff: ${comp.event_description || "(no description)"}`);
  lines.push(`Game state: ${comp.game_state}`);
  lines.push(`Faceoff odds: Home ${comp.faceoff_home_odds} | Away ${comp.faceoff_away_odds}`);
  if (!manual) {
    lines.push("Manual snapshot: none available");
  } else {
    lines.push(`Manual odds: Home ${manual.home_odds} | Away ${manual.away_odds}`);
    lines.push(`Lineup match: ${comp.lineup_match ? "yes" : "no"}`);
    if (typeof comp.delta_home_probability === "number") {
      lines.push(`Delta home probability: ${(comp.delta_home_probability * 100).toFixed(2)}%`);
    }
  }
  box.textContent = lines.join("\n");
}

async function fetchGames() {
  const apiKey = document.getElementById("apiKey").value.trim();
  if (!apiKey) {
    setStatus("API key is required.");
    return;
  }
  setStatus("Fetching games...");
  const r = await fetch(`/api/games?api_key=${encodeURIComponent(apiKey)}`);
  const data = await r.json();
  if (!data.ok) {
    setStatus(`Error: ${data.error}`);
    return;
  }

  cachedGames = data.games;
  const sel = document.getElementById("games");
  sel.innerHTML = "";
  cachedGames.forEach((g, idx) => {
    const t = g.start_time_common || g.start_time_est || "TBD";
    const opt = document.createElement("option");
    opt.value = String(idx);
    opt.textContent = `${g.away_team.name || "Away"} @ ${g.home_team.name || "Home"} (${t})`;
    sel.appendChild(opt);
  });
  setStatus(`Loaded ${cachedGames.length} games.`);
}

async function startMonitor() {
  const apiKey = document.getElementById("apiKey").value.trim();
  const interval = Number(document.getElementById("interval").value || 5);
  const sel = document.getElementById("games");
  if (!apiKey || sel.selectedIndex < 0 || cachedGames.length === 0) {
    setStatus("Fetch games and select one first.");
    return;
  }
  const game = cachedGames[Number(sel.value)];

  const r = await fetch("/api/start", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({api_key: apiKey, interval, game}),
  });
  const data = await r.json();
  if (!data.ok) {
    setStatus(`Start failed: ${data.error}`);
    return;
  }

  setStatus("Monitor started.");
  if (timer) {
    clearInterval(timer);
  }
  await pollStatus();
  timer = setInterval(pollStatus, Math.max(2, interval) * 1000);
}

async function pollStatus() {
  const r = await fetch("/api/status");
  const data = await r.json();
  if (!data.ok) {
    setStatus(data.error || "Status error.");
    return;
  }

  const s = data.snapshot;
  const headline = `${data.away_name} @ ${data.home_name} | ${data.game_state}`;
  document.getElementById("headline").innerHTML = `${headline} <span class=\"pill\">${data.event_type || "event"}</span>`;
  document.getElementById("report").textContent = s.report;
  renderComparison(data.last_faceoff_comparison);
  setStatus("Live update OK.");
}

async function logOddsNow() {
  const r = await fetch("/api/log-odds", {method: "POST"});
  const data = await r.json();
  if (!data.ok) {
    setStatus(`Log failed: ${data.error}`);
    return;
  }
  setStatus(`Logged manual snapshot at ${data.record.timestamp_est}.`);
}
</script>
</body>
</html>
        """
    )


@app.get("/api/games")
def api_games() -> Any:
    api_key = (request.args.get("api_key") or "").strip()
    if not api_key:
        return jsonify({"ok": False, "error": "Missing api_key query parameter."}), 400

    try:
        games = get_games_from_sportsradar(api_key=api_key)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

    return jsonify({"ok": True, "games": games})


@app.post("/api/start")
def api_start() -> Any:
    body = request.get_json(silent=True) or {}
    api_key = (body.get("api_key") or "").strip()
    game = body.get("game")
    interval = int(body.get("interval") or 5)

    if not api_key or not isinstance(game, dict):
        return jsonify({"ok": False, "error": "api_key and game are required."}), 400

    with _STATE_LOCK:
        _STATE["api_key"] = api_key
        _STATE["game"] = game
        _STATE["interval"] = max(2, interval)
        _STATE["manual_snapshots"] = []
        _STATE["faceoff_keys"] = set()
        _STATE["latest"] = None
        _STATE["last_faceoff_comparison"] = None

    return jsonify({"ok": True})


@app.get("/api/status")
def api_status() -> Any:
    try:
        return jsonify(_poll_once())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/log-odds")
def api_log_odds() -> Any:
    try:
        current = _poll_once()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    if not current.get("ok"):
        return jsonify(current), 400

    snap = current["snapshot"]
    if snap.get("home_probability") is None or snap.get("away_probability") is None:
        return jsonify({"ok": False, "error": "No valid Elo snapshot is currently available."}), 409

    record = log_manual_odds_snapshot(
        log_path=ODDS_LOG_PATH,
        game_id=str(current["game_id"]),
        home_name=current["home_name"],
        away_name=current["away_name"],
        game_state=current["game_state"],
        lineup_key=snap["lineup_key"],
        home_probability=float(snap["home_probability"]),
        away_probability=float(snap["away_probability"]),
        home_odds=snap["home_odds"],
        away_odds=snap["away_odds"],
    )

    with _STATE_LOCK:
        _STATE["manual_snapshots"].append(record)

    return jsonify({"ok": True, "record": record})


def main() -> None:
    app.run(host="127.0.0.1", port=5050, debug=False)


if __name__ == "__main__":
    main()
