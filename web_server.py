import os
import sys
import subprocess
import threading
import json
from flask import Flask, request, jsonify, render_template_string, redirect

# Add working directory to path to import local modules
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
sys.path.append(os.path.join(os.path.abspath(os.path.dirname(__file__)), "live_runs"))

from live_runs.get_game_ids import get_games_from_sportsradar
from live_runs.matchup_elo import load_player, win_probability, get_player_weights
from live_runs.live_matchup_monitor import _extract_player_id, PLAYER_ELOS_DIR

app = Flask(__name__)

# --- In-Memory State ---
current_state = {
    "game_period": 1,
    "game_clock": "20:00",
    "home_name": "Home",
    "away_name": "Away",
    "home_players": [],
    "away_players": [],
    "next_faceoff": 1,
    "home_prob": 0,
    "away_prob": 0,
    "home_odds": "N/A",
    "away_odds": "N/A"
}

bets = []
monitor_proc = None

# We can suppress stdout from weights calculation
def _quiet_weights(elo_players, label):
    old_stdout = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    try:
        return get_player_weights(elo_players, label=label)
    finally:
        sys.stdout.close()
        sys.stdout = old_stdout

def _probability_to_american_odds(prob: float) -> str:
    if prob <= 0.0: return "N/A"
    if prob >= 1.0: return "-INF"
    if prob >= 0.5:
        odds = -100.0 * prob / (1.0 - prob)
    else:
        odds = 100.0 * (1.0 - prob) / prob
    rounded = int(round(odds))
    return f"+{rounded}" if rounded > 0 else str(rounded)

def calculate_odds(home_players, away_players, home_name, away_name):
    home_ids = [_extract_player_id(p) for p in home_players]
    away_ids = [_extract_player_id(p) for p in away_players]
    home_ids = [i for i in home_ids if i is not None]
    away_ids = [i for i in away_ids if i is not None]
    
    home_elo_players = [load_player(pid, player_elos_dir=PLAYER_ELOS_DIR) for pid in home_ids]
    away_elo_players = [load_player(pid, player_elos_dir=PLAYER_ELOS_DIR) for pid in away_ids]
    
    home_elo_players = [p for p in home_elo_players if p is not None]
    away_elo_players = [p for p in away_elo_players if p is not None]
    
    if not home_elo_players or not away_elo_players:
        return 0, 0, "N/A", "N/A"

    home_weights = _quiet_weights(home_elo_players, label=home_name)
    away_weights = _quiet_weights(away_elo_players, label=away_name)
    
    overall_home = 0.0
    for i, hp in enumerate(home_elo_players):
        for j, ap in enumerate(away_elo_players):
            p_win = win_probability(hp["elo"], ap["elo"])
            mw = home_weights[i] * away_weights[j]
            overall_home += p_win * mw
            
    home_prob = overall_home
    away_prob = 1 - overall_home
    return home_prob, away_prob, _probability_to_american_odds(home_prob), _probability_to_american_odds(away_prob)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Faceoff Live Bettor</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #fdfdfd; }
        .card { background: white; border: 1px solid #ddd; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 2px 2px 8px rgba(0,0,0,0.05); }
        .header { display: flex; justify-content: space-between; align-items: center; }
        .odds { font-size: 24px; font-weight: bold; color: #1a73e8; }
        .btn { padding: 10px 15px; background: #1a73e8; color: white; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; }
        .btn:hover { background: #135aba; }
        .btn-danger { background: #e53935; }
        .btn-danger:hover { background: #b71c1c; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
        .bet-resolved { background: #e8f5e9; }
        .bet-resolved.success { background: #e8f5e9; }
        .bet-unresolved { background: #fff8e1; }
    </style>
    <script>
        // Auto refresh state every 2 seconds
        setInterval(() => window.location.reload(), 2000);
    </script>
</head>
<body>

<h1>Faceoff Live Monitor & Bettor</h1>

<div class="card">
    <div class="header">
        <h2>Live Monitor Control</h2>
        {% if is_running %}
            <form action="/stop_monitor" method="post">
                <button type="submit" class="btn btn-danger">Stop Monitor</button>
            </form>
        {% else %}
            <div>
                <h3>Start Monitor</h3>
                <form action="/start_monitor" method="post" style="display:flex; gap:10px;">
                    <select name="game_id" required>
                        <option value="" disabled selected>Select a Game</option>
                        {% for g in games %}
                            <option value="{{ g.sr_game_id }}|{{ g.home_team.name }}|{{ g.away_team.name }}">
                                {{ g.away_team.name }} @ {{ g.home_team.name }}
                            </option>
                        {% endfor %}
                    </select>
                    <button type="submit" class="btn">Start Monitoring</button>
                </form>
            </div>
        {% endif %}
    </div>
</div>

<div class="card">
    <h2>Current State: {{ state.away_name }} @ {{ state.home_name }}</h2>
    <p><strong>Period:</strong> {{ state.game_period }} | <strong>Clock:</strong> {{ state.game_clock }}</p>
    <p><strong>Anticipated Next Faceoff in Period:</strong> #{{ state.next_faceoff }}</p>

    <div style="display: flex; gap: 20px; margin-top:20px;">
        <div style="flex: 1;">
            <h3>🏠 {{ state.home_name }} On Ice</h3>
            <p class="odds">Win Prob: {{ "%.1f"|format(state.home_prob * 100) }}% | Odds: {{ state.home_odds }}</p>
            <ul>
                {% for p in state.home_players %}
                    <li>{{ p.full_name | default(p.name | default('Unknown')) }}</li>
                {% endfor %}
            </ul>
        </div>
        <div style="flex: 1;">
            <h3>🚌 {{ state.away_name }} On Ice</h3>
            <p class="odds">Win Prob: {{ "%.1f"|format(state.away_prob * 100) }}% | Odds: {{ state.away_odds }}</p>
            <ul>
                {% for p in state.away_players %}
                    <li>{{ p.full_name | default(p.name | default('Unknown')) }}</li>
                {% endfor %}
            </ul>
        </div>
    </div>

    <form action="/place_bet" method="post" style="margin-top: 20px;">
        <input type="hidden" name="expected_faceoff" value="{{ state.next_faceoff }}">
        <input type="hidden" name="game_period" value="{{ state.game_period }}">
        <select name="team_pick" required style="padding: 10px; font-size:16px;">
            <option value="{{ state.home_name }}">{{ state.home_name }} ({{ state.home_odds }})</option>
            <option value="{{ state.away_name }}">{{ state.away_name }} ({{ state.away_odds }})</option>
        </select>
        <button type="submit" class="btn">Lock in Bet!</button>
    </form>
</div>

<div class="card">
    <h2>Bet Log</h2>
    <table style="font-size: 14px;">
        <tr>
            <th>ID</th>
            <th>Expected FO</th>
            <th>Pick</th>
            <th>Locked Odds</th>
            <th>Locked On-Ice</th>
            <th>Status</th>
            <th>Actual Faceoff Description</th>
            <th>Actual On-Ice</th>
            <th>Winner</th>
        </tr>
        {% for bet in bets | reverse %}
        <tr class="{{ 'bet-resolved' if bet.resolved else 'bet-unresolved' }}">
            <td>{{ loop.index }}</td>
            <td>P{{ bet.game_period }} #{{ bet.expected_faceoff }}</td>
            <td>{{ bet.team_pick }}</td>
            <td>{{ bet.locked_odds }}</td>
            <td><small><b>H:</b> {{ bet.snapshot_home_players | join(", ") }}<br><b>A:</b> {{ bet.snapshot_away_players | join(", ") }}</small></td>
            <td>{{ "Resolved" if bet.resolved else "Pending..." }}</td>
            <td>{{ bet.actual_event.description if bet.resolved else "-" }}</td>
            <td>
                {% if bet.resolved and bet.actual_event.on_ice %}
                    <small><b>H:</b> {{ (bet.actual_event.on_ice.home | map(attribute='full_name')) | join(", ") }}<br><b>A:</b> {{ (bet.actual_event.on_ice.away | map(attribute='full_name')) | join(", ") }}</small>
                {% else %}
                    -
                {% endif %}
            </td>
            <td>
                {% if bet.resolved %}
                    {% if bet.pick_won %}
                        <strong style="color:green;">YES</strong>
                    {% elif bet.pick_won == False %}
                        <strong style="color:red;">NO</strong>
                    {% else %}
                        <strong style="color:gray;">TBD</strong>
                    {% endif %}
                {% else %}
                    -
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
</div>

</body>
</html>
"""

@app.route("/")
def index():
    games = []
    if monitor_proc is None:
        api_key = app.config.get("SPORTRADAR_API_KEY")
        if api_key:
            try:
                games = get_games_from_sportsradar(api_key=api_key)
            except Exception as e:
                print("Error loading games:", e)
    
    return render_template_string(HTML_TEMPLATE, state=current_state, bets=bets, is_running=(monitor_proc is not None), games=games)

@app.route("/start_monitor", methods=["POST"])
def start_monitor():
    global monitor_proc
    if monitor_proc is not None:
        return redirect("/")
    
    api_key = app.config.get("SPORTRADAR_API_KEY")
    game_str = request.form.get("game_id") # "sr_id|home|away"
    
    if not api_key or not game_str:
        return redirect("/")
        
    sr_id, home, away = game_str.split("|")
    
    # Start process
    monitor_script = os.path.join(os.path.dirname(__file__), "live_runs", "live_matchup_monitor.py")
    cmd = [
        sys.executable, monitor_script,
        "--sportsradar-key", api_key,
        "--sr-game-id", sr_id,
        "--home-name", home,
        "--away-name", away,
        "--interval", "4"
    ]
    
    monitor_proc = subprocess.Popen(cmd)
    return redirect("/")

@app.route("/stop_monitor", methods=["POST"])
def stop_monitor():
    global monitor_proc
    if monitor_proc is not None:
        monitor_proc.terminate()
        monitor_proc = None
    return redirect("/")

@app.route("/state", methods=["POST"])
def update_state():
    global current_state
    data = request.json
    current_state.update(data)
    
    home_prob, away_prob, home_odds, away_odds = calculate_odds(
        data.get("home_players", []),
        data.get("away_players", []),
        data.get("home_name", "Home"),
        data.get("away_name", "Away")
    )
    current_state["home_prob"] = home_prob
    current_state["away_prob"] = away_prob
    current_state["home_odds"] = home_odds
    current_state["away_odds"] = away_odds
    
    return jsonify({"status": "ok"})

@app.route("/faceoff", methods=["POST"])
def log_faceoff():
    data = request.json
    faceoff_num = data.get("faceoff_number")
    game_period = data.get("game_period")
    description = data.get("description", "").lower()
    on_ice = data.get("on_ice", {})
    
    # Check if there are any active bets waiting for this faceoff
    for bet in bets:
        if not bet.get("resolved") and bet["expected_faceoff"] == faceoff_num and bet["game_period"] == game_period:
            bet["resolved"] = True
            bet["actual_event"] = data
            
            # Simple check to see if the chosen team won the faceoff based on the description
            team_pick = bet["team_pick"].lower()
            
            # Find which player won
            # Expected "Player Name won faceoff"
            winner_str = description.split(" won faceoff")[0].strip() if " won faceoff" in description else ""
            
            # See if winner_str is in the chosen team's snapshot or actual on-ice roster
            # We match vs team_pick. We have actual_event.on_ice."home" and "away"
            is_home_pick = (team_pick == current_state["home_name"].lower())
            
            check_list = on_ice.get("home", []) if is_home_pick else on_ice.get("away", [])
            pick_won = None
            for p in check_list:
                pname = (p.get("full_name") or p.get("name") or "").lower()
                if winner_str and winner_str in pname:
                    pick_won = True
                    break
            
            # If not in our picked team, they might be in the opposing team
            if pick_won is None and winner_str:
                opp_list = on_ice.get("away", []) if is_home_pick else on_ice.get("home", [])
                for p in opp_list:
                    pname = (p.get("full_name") or p.get("name") or "").lower()
                    if winner_str in pname:
                        pick_won = False
                        break

            bet["pick_won"] = pick_won

    return jsonify({"status": "ok"})

@app.route("/place_bet", methods=["POST"])
def place_bet():
    team_pick = request.form.get("team_pick")
    expected_faceoff = int(request.form.get("expected_faceoff", 1))
    game_period = int(request.form.get("game_period", 1))
    
    locked_odds = current_state["home_odds"] if team_pick == current_state["home_name"] else current_state["away_odds"]
    
    # Store snapshot of who was on ice AT TIME of placing bet
    snapshot_home_players = [p.get("full_name") or p.get("name") or "Unknown" for p in current_state.get("home_players", [])]
    snapshot_away_players = [p.get("full_name") or p.get("name") or "Unknown" for p in current_state.get("away_players", [])]

    bets.append({
        "team_pick": team_pick,
        "expected_faceoff": expected_faceoff,
        "game_period": game_period,
        "locked_odds": locked_odds,
        "snapshot_home_players": snapshot_home_players,
        "snapshot_away_players": snapshot_away_players,
        "resolved": False,
        "actual_event": None
    })
    
    return redirect("/")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Live faceoff Elo bettor")
    parser.add_argument("--sportsradar-key", required=True, help="Sportradar API key")
    args = parser.parse_args()
    
    # Expose the API key globally so the app route can use it implicitly
    app.config["SPORTRADAR_API_KEY"] = args.sportsradar_key
    
    app.run(host="0.0.0.0", port=3000, debug=True)
