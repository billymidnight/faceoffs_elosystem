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
last_faceoff = {}
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
        .bet-won { background: #c8e6c9 !important; }
        .bet-lost { background: #ffcdd2 !important; }
        .bet-unresolved { background: #fff8e1; }
        .last-faceoff-panel { background: #f3e5f5; border: 2px solid #ce93d8; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
        .last-faceoff-panel h3 { margin-top: 0; color: #6a1b9a; }
        .modal-overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:1000; justify-content:center; align-items:center; }
        .modal-overlay.active { display:flex; }
        .modal-box { background:white; padding:30px; border-radius:10px; box-shadow:0 4px 20px rgba(0,0,0,0.3); text-align:center; min-width:340px; }
        .modal-box h3 { margin-top:0; }
        .modal-box input { padding:12px; font-size:20px; width:160px; text-align:center; border:2px solid #1a73e8; border-radius:6px; margin:10px 0; }
        .modal-box .modal-btns { display:flex; gap:10px; justify-content:center; margin-top:15px; }
        .modal-box .modal-btns button { padding:10px 20px; font-size:15px; border:none; border-radius:4px; cursor:pointer; }
        .modal-box .btn-confirm { background:#1a73e8; color:white; }
        .modal-box .btn-confirm:hover { background:#135aba; }
        .modal-box .btn-skip { background:#757575; color:white; }
        .modal-box .btn-skip:hover { background:#616161; }
    </style>
    <script>
        var refreshTimer = setInterval(() => window.location.reload(), 2000);
        function pauseRefresh() { clearInterval(refreshTimer); }
        function resumeRefresh() { refreshTimer = setInterval(() => window.location.reload(), 2000); }

        function openBetModal(team, faceoff, period) {
            pauseRefresh();
            document.getElementById('modal_team_label').textContent = team;
            document.getElementById('modal_team_pick').value = team;
            document.getElementById('modal_expected_faceoff').value = faceoff;
            document.getElementById('modal_game_period').value = period;
            document.getElementById('modal_taken_odds').value = '';
            document.getElementById('modal_taken_odds').focus();
            document.getElementById('bet_modal').classList.add('active');
            setTimeout(function(){ document.getElementById('modal_taken_odds').focus(); }, 100);
        }

        function confirmBet() {
            document.getElementById('modal_bet_form').submit();
        }

        function skipOdds() {
            document.getElementById('modal_taken_odds').value = '';
            document.getElementById('modal_bet_form').submit();
        }

        function cancelBet() {
            document.getElementById('bet_modal').classList.remove('active');
            resumeRefresh();
        }
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
                            <option value="{{ g.game_id }}|{{ g.home_team.name }}|{{ g.away_team.name }}">
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

{% if last_faceoff %}
<div class="card last-faceoff-panel">
    <h3>Last Faceoff</h3>
    <div style="display:flex; gap:30px; flex-wrap:wrap; align-items:center;">
        <div><strong>Winning Team:</strong> {{ last_faceoff.winning_team }}</div>
        <div><strong>Winner:</strong> {{ last_faceoff.winner_player }}</div>
        <div><strong>Loser:</strong> {{ last_faceoff.loser_player }}</div>
        <div><strong>Period:</strong> P{{ last_faceoff.period }} | <strong>Clock:</strong> {{ last_faceoff.clock }}</div>
        <div><strong>FO #:</strong> {{ last_faceoff.faceoff_number }}</div>
    </div>
    <div style="margin-top:8px; font-size:13px; color:#555;"><em>{{ last_faceoff.description }}</em></div>
</div>
{% endif %}

<div class="card">
    <h2>Current State: {{ state.away_name }} @ {{ state.home_name }}</h2>
    <p><strong>Period:</strong> {{ state.game_period }} | <strong>Clock:</strong> {{ state.game_clock }}</p>
    <p><strong>Anticipated Next Faceoff in Period:</strong> #{{ state.next_faceoff }}</p>

    <div style="display: flex; gap: 20px; margin-top:20px;">
        <div style="flex: 1;">
            <h3>🏠 {{ state.home_name }} On Ice</h3>
            <p class="odds">Win Prob: {{ "%.1f"|format(state.home_prob * 100) }}% | Odds: {{ state.home_odds }}</p>
            <ul>
                {% if state.home_players_elo %}
                    {% for p in state.home_players_elo %}
                        <li>{{ p.name }} - Elo: {{ "%.1f"|format(p.elo) }} (Wt: {{ "%.1f"|format(p.weight * 100) }}%)</li>
                    {% endfor %}
                {% else %}
                    {% for p in state.home_players %}
                        <li>{{ p.full_name | default(p.name | default('Unknown')) }}</li>
                    {% endfor %}
                {% endif %}
            </ul>
        </div>
        <div style="flex: 1;">
            <h3>🚌 {{ state.away_name }} On Ice</h3>
            <p class="odds">Win Prob: {{ "%.1f"|format(state.away_prob * 100) }}% | Odds: {{ state.away_odds }}</p>
            <ul>
                {% if state.away_players_elo %}
                    {% for p in state.away_players_elo %}
                        <li>{{ p.name }} - Elo: {{ "%.1f"|format(p.elo) }} (Wt: {{ "%.1f"|format(p.weight * 100) }}%)</li>
                    {% endfor %}
                {% else %}
                    {% for p in state.away_players %}
                        <li>{{ p.full_name | default(p.name | default('Unknown')) }}</li>
                    {% endfor %}
                {% endif %}
            </ul>
        </div>
    </div>

    {% if state.matchups %}
    <div style="margin-top: 20px;">
        <h3>Detailed Matchups</h3>
        <table style="font-size: 14px;">
            <tr>
                <th>Home Player</th>
                <th>Away Player</th>
                <th>P(Home)</th>
                <th>Home Odds</th>
                <th>P(Away)</th>
                <th>Away Odds</th>
                <th>Matchup Weight</th>
            </tr>
            {% for m in state.matchups %}
            <tr>
                <td>{{ m.home_player }}</td>
                <td>{{ m.away_player }}</td>
                <td>{{ "%.1f"|format(m.prob_home * 100) }}%</td>
                <td>{{ m.odds_home }}</td>
                <td>{{ "%.1f"|format(m.prob_away * 100) }}%</td>
                <td>{{ m.odds_away }}</td>
                <td>{{ "%.2f"|format(m.weight * 100) }}%</td>
            </tr>
            {% endfor %}
        </table>
    </div>
    {% endif %}

    <div style="margin-top: 20px; display:flex; gap:15px; align-items:center; flex-wrap:wrap;">
        <button type="button" class="btn" style="font-size:15px; padding:10px 18px;"
            onclick="openBetModal('{{ state.home_name }}', '{{ state.next_faceoff }}', '{{ state.game_period }}')">
            Take {{ state.home_name }} ({{ state.home_odds }})
        </button>
        <button type="button" class="btn" style="font-size:15px; padding:10px 18px;"
            onclick="openBetModal('{{ state.away_name }}', '{{ state.next_faceoff }}', '{{ state.game_period }}')">
            Take {{ state.away_name }} ({{ state.away_odds }})
        </button>
    </div>
</div>

<!-- Bet Modal -->
<div id="bet_modal" class="modal-overlay">
    <div class="modal-box">
        <h3>Place Bet: <span id="modal_team_label"></span></h3>
        <form id="modal_bet_form" action="/place_bet" method="post">
            <input type="hidden" name="team_pick" id="modal_team_pick">
            <input type="hidden" name="expected_faceoff" id="modal_expected_faceoff">
            <input type="hidden" name="game_period" id="modal_game_period">
            <label style="font-weight:bold;">Taken Odds (American):</label><br>
            <input type="text" name="taken_odds" id="modal_taken_odds" placeholder="e.g. -110" autofocus>
            <div class="modal-btns">
                <button type="button" class="btn-confirm" onclick="confirmBet()">Confirm</button>
                <button type="button" class="btn-skip" onclick="skipOdds()">Skip (no odds)</button>
                <button type="button" class="btn-skip" onclick="cancelBet()" style="background:#e53935;">Cancel</button>
            </div>
        </form>
    </div>
</div>

<div class="card">
    <h2>Bet Log</h2>
    <table style="font-size: 14px;">
        <tr>
            <th>ID</th>
            <th>Expected FO</th>
            <th>Pick</th>
            <th>Fair Odds</th>
            <th>Taken Odds</th>
            <th>CLV</th>
            <th>Locked On-Ice</th>
            <th>Status</th>
            <th>Actual Faceoff Description</th>
            <th>Actual On-Ice</th>
            <th>Winner</th>
        </tr>
        {% for bet in bets | reverse %}
        <tr class="{% if bet.resolved %}{% if bet.pick_won %}bet-won{% elif bet.pick_won == False %}bet-lost{% else %}bet-resolved{% endif %}{% else %}bet-unresolved{% endif %}">
            <td>{{ loop.index }}</td>
            <td>P{{ bet.game_period }} #{{ bet.expected_faceoff }}</td>
            <td>{{ bet.team_pick }}</td>
            <td>{{ bet.locked_odds }}</td>
            <td>{{ bet.taken_odds if bet.taken_odds else "-" }}</td>
            <td>{{ bet.clv if bet.clv else "Pending" }}</td>
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
    
    return render_template_string(HTML_TEMPLATE, state=current_state, bets=bets, last_faceoff=last_faceoff, is_running=(monitor_proc is not None), games=games)

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
    
    return jsonify({"status": "ok"})

@app.route("/faceoff", methods=["POST"])
def log_faceoff():
    global last_faceoff
    data = request.json
    faceoff_num = data.get("faceoff_number")
    game_period = data.get("game_period")
    description = data.get("description", "").lower()
    on_ice = data.get("on_ice", {})
    
    # Parse winner/loser from description
    winner_str = description.split(" won faceoff")[0].strip() if " won faceoff" in description else ""
    loser_str = ""
    if " against " in description:
        loser_str = description.split(" against ")[-1].strip().rstrip(".")
    
    # Determine winning team
    winning_team = ""
    if winner_str:
        for p in on_ice.get("home", []):
            pname = (p.get("full_name") or p.get("name") or "").lower()
            if winner_str in pname:
                winning_team = current_state.get("home_name", "Home")
                break
        if not winning_team:
            for p in on_ice.get("away", []):
                pname = (p.get("full_name") or p.get("name") or "").lower()
                if winner_str in pname:
                    winning_team = current_state.get("away_name", "Away")
                    break
    
    # Update last faceoff panel
    last_faceoff = {
        "winner_player": winner_str.title(),
        "loser_player": loser_str.title(),
        "winning_team": winning_team or "Unknown",
        "period": game_period,
        "clock": on_ice.get("clock", ""),
        "faceoff_number": faceoff_num,
        "description": data.get("description", "")
    }
    
    # Check if there are any active bets waiting for this faceoff
    for bet in bets:
        if not bet.get("resolved") and bet["expected_faceoff"] == faceoff_num and bet["game_period"] == game_period:
            bet["resolved"] = True
            bet["actual_event"] = data
            
            # Capture CLV: fair price of the side we took right before this faceoff
            if bet["team_pick"] == current_state.get("home_name"):
                bet["clv"] = current_state.get("home_odds", "N/A")
            else:
                bet["clv"] = current_state.get("away_odds", "N/A")
            
            # Check if the chosen team won the faceoff
            team_pick = bet["team_pick"].lower()
            is_home_pick = (team_pick == current_state["home_name"].lower())
            
            check_list = on_ice.get("home", []) if is_home_pick else on_ice.get("away", [])
            pick_won = None
            for p in check_list:
                pname = (p.get("full_name") or p.get("name") or "").lower()
                if winner_str and winner_str in pname:
                    pick_won = True
                    break
            
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
    taken_odds = request.form.get("taken_odds", "")
    
    locked_odds = current_state["home_odds"] if team_pick == current_state["home_name"] else current_state["away_odds"]
    
    # Store snapshot of who was on ice AT TIME of placing bet
    snapshot_home_players = [p.get("full_name") or p.get("name") or "Unknown" for p in current_state.get("home_players", [])]
    snapshot_away_players = [p.get("full_name") or p.get("name") or "Unknown" for p in current_state.get("away_players", [])]

    bets.append({
        "team_pick": team_pick,
        "expected_faceoff": expected_faceoff,
        "game_period": game_period,
        "locked_odds": locked_odds,
        "taken_odds": taken_odds,
        "clv": "Pending",
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
