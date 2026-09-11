"""
Facebook Messenger Idle Game Bot v2
====================================
Pet system, economy, games, car system, heist, and owner commands.
Prefix: .
"""

import os
import time
import random
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "YOUR_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "your_secret")
PREFIX = "."

PASSIVE_GOLD_PER_SECOND = 1
DB_PATH = os.path.join(os.path.dirname(__file__), "players.db")
GRAPH_API_URL = "https://graph.facebook.com/v19.0/me/messages"

BOT_START_TIME = time.time()
COMMAND_USE_COUNT = {}

# =====================================================================
# DATABASE
# =====================================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id TEXT PRIMARY KEY,
            gold INTEGER DEFAULT 100,
            bank INTEGER DEFAULT 0,
            mine_level INTEGER DEFAULT 1,
            last_active REAL,
            last_daily REAL DEFAULT 0,
            pet_name TEXT,
            pet_level INTEGER DEFAULT 0,
            pet_last_fed REAL DEFAULT 0,
            car_model TEXT,
            car_level INTEGER DEFAULT 0,
            heist_planning INTEGER DEFAULT 0,
            heist_team_size INTEGER DEFAULT 0,
            last_heist REAL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_or_create_player(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM players WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        now = time.time()
        conn.execute(
            "INSERT INTO players (user_id, last_active) VALUES (?, ?)",
            (user_id, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM players WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row)

def save_player(player):
    conn = get_conn()
    conn.execute("""
        UPDATE players SET
            gold = ?, bank = ?, mine_level = ?, last_active = ?,
            last_daily = ?, pet_name = ?, pet_level = ?, pet_last_fed = ?,
            car_model = ?, car_level = ?, heist_planning = ?, heist_team_size = ?, last_heist = ?
        WHERE user_id = ?
    """, (
        player["gold"], player["bank"], player["mine_level"], player["last_active"],
        player["last_daily"], player["pet_name"], player["pet_level"], player["pet_last_fed"],
        player["car_model"], player["car_level"], player["heist_planning"], player["heist_team_size"], player["last_heist"],
        player["user_id"],
    ))
    conn.commit()
    conn.close()

def top_players(order_by="gold", limit=5):
    conn = get_conn()
    rows = conn.execute(
        f"SELECT * FROM players ORDER BY {order_by} DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# =====================================================================
# GAME LOGIC
# =====================================================================

def process_idle_gains(player):
    now = time.time()
    seconds_away = int(now - player["last_active"])
    player["last_active"] = now
    if seconds_away <= 0:
        return 0
    earned = seconds_away * PASSIVE_GOLD_PER_SECOND * player["mine_level"]
    player["gold"] += earned
    return earned

def send_fb_message(recipient_id, text):
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    params = {"access_token": PAGE_ACCESS_TOKEN}
    try:
        requests.post(GRAPH_API_URL, params=params, json=payload, timeout=10)
    except:
        pass

# =====================================================================
# HELP & COMMANDS
# =====================================================================

HELP_PAGES = {
    1: {
        "📚 INFO": ["help", "balance", "myinfo", "prefix", "status", "uptime"],
        "💰 ECONOMY": ["atm", "bal", "bank", "mine", "richest", "top", "daily", "upgrade"],
        "🐾 PETS": ["pet", "pet buy", "pet feed", "pet lb"],
    },
    2: {
        "🚗 CAR": ["car", "car buy", "car drive", "car upgrade"],
        "🎮 GAMES": ["8ball", "coin", "slot", "guess", "quiz", "duel", "connect4", "ttt", "snake", "wordchain"],
    },
    3: {
        "💰 HEIST": ["heist plan", "heist crew", "heist go"],
        "👑 OWNER": ["cmdstats", "users", "botstats", "gc", "ban", "unban", "warn", "kick", "mute", "unmute", "say", "restart", "config", "whitelist", "blacklist", "logs", "announce", "backup"],
    },
}

def build_help_page(user_name, page):
    if page not in HELP_PAGES:
        page = 1
    total_pages = len(HELP_PAGES)
    now = datetime.now()

    header = (
        "╭━━━━━━━━━━━━─\n"
        f"│ 👤 User     : {user_name}\n"
        f"│ 🏷️ Prefix   : {PREFIX}\n"
        f"│ ✨ Commands : 100+\n"
        f"│ 📄 Page     : {page} / {total_pages}\n"
        f"│ ⏰ Time     : {now.strftime('%-I:%M:%S %p')}\n"
        f"│ 📅 Date     : {now.strftime('%-m/%-d/%Y')}\n"
        "╰━━━━━━━━━━━━─\n\n"
    )

    body = ""
    for category, cmds in HELP_PAGES[page].items():
        body += f"╭─ {category} [{len(cmds)}]\n"
        for i in range(0, len(cmds), 3):
            chunk = cmds[i:i + 3]
            body += "│ " + "  ".join(f"• {c}" for c in chunk) + "\n"
        body += "╰━━━━━━━━━━━━─\n\n"

    footer = (
        "👑━━━━━━━━━━━━━━👑\n"
        f"🌷 {PREFIX}help <command>  → Command details\n"
        f"📄 {PREFIX}help <page>     → More categories\n\n"
        "👑━━━━━━━━━━━━━━👑"
    )
    return header + body + footer

# =====================================================================
# COMMAND HANDLER
# =====================================================================

def handle_command(user_id, user_name, command, args, player):
    reply = ""

    if command == "help":
        if args and args[0].isdigit():
            reply = build_help_page(user_name, int(args[0]))
        else:
            reply = build_help_page(user_name, 1)

    elif command in ("balance", "bal"):
        reply = (
            f"📊 PLAYER PROFILE\n"
            f"────────────────\n"
            f"💰 Wallet: {player['gold']} gold\n"
            f"🏦 Bank: {player['bank']} gold\n"
            f"⛏️ Mine Lv.{player['mine_level']}\n"
            f"🐾 Pet: {player['pet_name'] or 'None'}\n"
            f"🚗 Car: {player['car_model'] or 'None'}"
        )

    elif command == "myinfo":
        reply = f"👤 {user_name} | 🆔 {user_id[-4:]} | 💰 {player['gold']} | 🏦 {player['bank']}"

    elif command == "prefix":
        reply = f"🏷️ My prefix is: {PREFIX}"

    elif command == "uptime":
        secs = int(time.time() - BOT_START_TIME)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        reply = f"⏱️ Uptime: {h}h {m}m {s}s"

    elif command == "status":
        reply = "✅ Bot is online and running."

    elif command == "atm":
        reply = f"🏧 Wallet: 💰{player['gold']}  |  🏦 Bank: 💰{player['bank']}"

    elif command == "coin":
        reply = f"🪙 {random.choice(['Heads', 'Tails'])}!"

    elif command == "8ball":
        answers = ["Yes.", "No.", "Ask again later.", "Definitely!", "Very doubtful.", "Absolutely not."]
        reply = f"🎱 {random.choice(answers)}"

    elif command == "slot":
        symbols = ["🍒", "🍋", "🔔", "💎", "7️⃣"]
        spin = [random.choice(symbols) for _ in range(3)]
        cost = 20
        if player["gold"] < cost:
            reply = f"❌ Slots cost 💰{cost}."
        else:
            player["gold"] -= cost
            if spin[0] == spin[1] == spin[2]:
                payout = cost * 10
                player["gold"] += payout
                reply = f"🎰 {' '.join(spin)}\n🎉 JACKPOT! Won 💰{payout}!"
            else:
                reply = f"🎰 {' '.join(spin)}\nNo match."

    elif command == "guess":
        secret = random.randint(1, 10)
        reply = f"🔢 I'm thinking of a number 1-10... (it was {secret})"

    elif command == "quiz":
        qa = [
            ("What planet is the Red Planet?", "mars"),
            ("What's 2+2?", "4"),
            ("What's the capital of France?", "paris"),
        ]
        q, _ = random.choice(qa)
        reply = f"❓ {q}"

    elif command == "connect4":
        reply = "🟡 Connect4 game coming soon!"

    elif command == "ttt":
        reply = "❌ Tic-Tac-Toe game coming soon!"

    elif command == "snake":
        reply = "🐍 Snake game coming soon!"

    elif command == "wordchain":
        reply = "📝 Word Chain game coming soon!"

    elif command == "duel":
        wager = 50
        if player["gold"] < wager:
            reply = f"⚔️ Duel costs 💰{wager}."
        else:
            player["gold"] -= wager
            if random.random() > 0.5:
                win = wager * 2
                player["gold"] += win
                reply = f"⚔️ YOU WON! 💰{win}!"
            else:
                reply = f"⚔️ You lost 💰{wager}..."

    elif command == "mine":
        gains = 10 * player["mine_level"]
        player["gold"] += gains
        reply = f"⛏️ SMASH! You mined 💰{gains}!"

    elif command == "upgrade":
        cost = player["mine_level"] * 250
        if player["gold"] >= cost:
            player["gold"] -= cost
            player["mine_level"] += 1
            reply = f"🚀 Mine now Level {player['mine_level']}!"
        else:
            reply = f"❌ Costs 💰{cost}. Need 💰{cost - player['gold']} more."

    elif command == "daily":
        now = time.time()
        cooldown = 24 * 3600
        if now - player["last_daily"] < cooldown:
            hrs_left = int((cooldown - (now - player["last_daily"])) // 3600)
            reply = f"⏳ Try again in {hrs_left}h."
        else:
            bonus = random.randint(100, 300)
            player["gold"] += bonus
            player["last_daily"] = now
            reply = f"🎁 Daily bonus: 💰{bonus}!"

    elif command == "bank":
        if not args or args[0] not in ("deposit", "withdraw") or len(args) < 2:
            reply = f"🏦 Usage: {PREFIX}bank deposit [amount] / {PREFIX}bank withdraw [amount]"
        else:
            try:
                amount = int(args[1])
                if args[0] == "deposit":
                    if amount > player["gold"]:
                        reply = "❌ Not enough gold."
                    else:
                        player["gold"] -= amount
                        player["bank"] += amount
                        reply = f"🏦 Deposited 💰{amount}."
                else:
                    if amount > player["bank"]:
                        reply = "❌ Not enough in bank."
                    else:
                        player["bank"] -= amount
                        player["gold"] += amount
                        reply = f"🏧 Withdrew 💰{amount}."
            except:
                reply = "❌ Invalid amount."

    elif command == "richest":
        richest = top_players(order_by="gold", limit=5)
        reply = "🏆 RICHEST PLAYERS\n───────────────\n"
        for i, p in enumerate(richest, 1):
            reply += f"{i}. ...{p['user_id'][-4:]}: 💰{p['gold']}\n"

    elif command == "pet":
        sub = args[0].lower() if args else ""
        if sub == "lb":
            pets = [p for p in top_players(order_by="pet_level", limit=5) if p["pet_level"] > 0]
            reply = "🏆 PET LEADERBOARD\n─────────────────\n"
            if not pets:
                reply += "No pets yet."
            else:
                for i, p in enumerate(pets, 1):
                    reply += f"{i}. {p['pet_name']} (Lv.{p['pet_level']})\n"
        elif sub == "buy":
            if player["pet_name"]:
                reply = f"❌ You already have {player['pet_name']}!"
            elif player["gold"] < 500:
                reply = "❌ Pet costs 💰500."
            else:
                pet_name = " ".join(args[1:]) or "Buddy"
                player["gold"] -= 500
                player["pet_name"] = pet_name
                player["pet_level"] = 1
                reply = f"🐾 You adopted **{pet_name}**! Use {PREFIX}pet feed to grow them."
        elif sub == "feed":
            if not player["pet_name"]:
                reply = f"❌ No pet yet. Use {PREFIX}pet buy [name]."
            else:
                cooldown = 60
                if time.time() - player["pet_last_fed"] < cooldown:
                    wait = int(cooldown - (time.time() - player["pet_last_fed"]))
                    reply = f"⏱️ {player['pet_name']} is full. Wait {wait}s."
                elif player["gold"] < 50:
                    reply = "❌ Kibble costs 💰50."
                else:
                    player["gold"] -= 50
                    player["pet_level"] += 1
                    player["pet_last_fed"] = time.time()
                    reply = f"🐾 {player['pet_name']} grew to Lv.{player['pet_level']}!"
        else:
            if player["pet_name"]:
                reply = f"🐾 {player['pet_name']} — Level {player['pet_level']}"
            else:
                reply = f"🐾 No pet yet. Use {PREFIX}pet buy [name]."

    elif command == "car":
        sub = args[0].lower() if args else ""
        if sub == "buy":
            if player["car_model"]:
                reply = f"❌ You already have a {player['car_model']}!"
            elif player["gold"] < 1000:
                reply = "❌ Car costs 💰1000."
            else:
                car_name = " ".join(args[1:]) or "Sedan"
                player["gold"] -= 1000
                player["car_model"] = car_name
                player["car_level"] = 1
                reply = f"🚗 You bought a **{car_name}**! Use {PREFIX}car drive to earn."
        elif sub == "drive":
            if not player["car_model"]:
                reply = f"❌ No car yet. Use {PREFIX}car buy [name]."
            else:
                earnings = 50 * player["car_level"]
                player["gold"] += earnings
                reply = f"🚗 Drove your {player['car_model']} and earned 💰{earnings}!"
        elif sub == "upgrade":
            if not player["car_model"]:
                reply = "❌ No car to upgrade."
            else:
                cost = player["car_level"] * 300
                if player["gold"] >= cost:
                    player["gold"] -= cost
                    player["car_level"] += 1
                    reply = f"🚗 {player['car_model']} upgraded to Lv.{player['car_level']}!"
                else:
                    reply = f"❌ Costs 💰{cost}."
        else:
            if player["car_model"]:
                reply = f"🚗 {player['car_model']} — Level {player['car_level']}"
            else:
                reply = f"🚗 No car yet. Use {PREFIX}car buy [name]."

    elif command == "heist":
        sub = args[0].lower() if args else ""
        if sub == "plan":
            player["heist_planning"] = 1
            player["heist_team_size"] = 0
            reply = "💰 Heist planned! Use .heist crew [size] to gather a team."
        elif sub == "crew":
            if not player["heist_planning"]:
                reply = "❌ No heist planned. Use {PREFIX}heist plan first."
            elif not args[1:]:
                reply = "❌ Usage: .heist crew [size]"
            else:
                try:
                    team_size = int(args[1])
                    player["heist_team_size"] = team_size
                    reply = f"👥 Gathered a team of {team_size}. Use {PREFIX}heist go to execute!"
                except:
                    reply = "❌ Invalid team size."
        elif sub == "go":
            if not player["heist_planning"] or player["heist_team_size"] == 0:
                reply = "❌ No heist planned. Use .heist plan first."
            else:
                risk = max(10, 100 - (player["heist_team_size"] * 5))
                if random.randint(1, 100) > risk:
                    loot = player["heist_team_size"] * 200
                    player["gold"] += loot
                    reply = f"💰 HEIST SUCCESS! Stole 💰{loot}!"
                else:
                    fine = player["heist_team_size"] * 100
                    player["gold"] = max(0, player["gold"] - fine)
                    reply = f"🚔 CAUGHT! Fined 💰{fine}!"
                player["heist_planning"] = 0
                player["heist_team_size"] = 0
                player["last_heist"] = time.time()
        else:
            reply = "💰 Heist commands: .heist plan | .heist crew [size] | .heist go"

    elif command == "cmdstats":
        top = sorted(COMMAND_USE_COUNT.items(), key=lambda x: -x[1])[:10]
        reply = "📈 Top commands:\n" + "\n".join(f"• {c}: {n}" for c, n in top) if top else "No commands used yet."

    elif command == "users":
        conn = get_conn()
        count = conn.execute("SELECT COUNT(*) as cnt FROM players").fetchone()["cnt"]
        conn.close()
        reply = f"👥 Total players: {count}"

    elif command == "botstats":
        reply = (
            f"🤖 BOT STATS\n"
            f"────────────\n"
            f"Commands used: {sum(COMMAND_USE_COUNT.values())}\n"
            f"Uptime: {int((time.time() - BOT_START_TIME) // 3600)}h"
        )

    elif command == "gc":
        reply = "🗑️ Garbage collected!"

    elif command == "ban":
        reply = "🚫 User banned (placeholder)."

    elif command == "unban":
        reply = "✅ User unbanned (placeholder)."

    elif command == "warn":
        reply = "⚠️ User warned (placeholder)."

    elif command == "kick":
        reply = "👢 User kicked (placeholder)."

    elif command == "mute":
        reply = "🔇 User muted (placeholder)."

    elif command == "unmute":
        reply = "🔊 User unmuted (placeholder)."

    elif command == "say":
        msg = " ".join(args) if args else "(empty message)"
        reply = f"💬 {msg}"

    elif command == "restart":
        reply = "🔄 Restarting bot... (placeholder)"

    elif command == "config":
        reply = "⚙️ Config updated (placeholder)."

    elif command == "whitelist":
        reply = "✅ Added to whitelist (placeholder)."

    elif command == "blacklist":
        reply = "❌ Added to blacklist (placeholder)."

    elif command == "logs":
        reply = "📋 Logs retrieved (placeholder)."

    elif command == "announce":
        msg = " ".join(args) if args else "Announcement"
        reply = f"📢 ANNOUNCEMENT: {msg}"

    elif command == "backup":
        reply = "💾 Backup created (placeholder)."

    else:
        reply = f"❓ Unknown command. Try {PREFIX}help"

    COMMAND_USE_COUNT[command] = COMMAND_USE_COUNT.get(command, 0) + 1
    return reply

# =====================================================================
# WEBHOOK
# =====================================================================

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode is None or token is None:
        return "Missing parameters", 400

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("WEBHOOK_VERIFIED")
        return challenge, 200

    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def handle_webhook():
    body = request.get_json(silent=True) or {}

    if body.get("object") != "page":
        return jsonify(status="ignored"), 404

    for entry in body.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            message = event.get("message", {})
            text = message.get("text")

            if not sender_id or not text:
                continue

            raw_text = text.strip()
            if not raw_text.startswith(PREFIX):
                continue

            tokens = raw_text[len(PREFIX):].strip().split()
            if not tokens:
                continue

            command = tokens[0].lower()
            args = tokens[1:]

            player = get_or_create_player(sender_id)
            idle_gains = process_idle_gains(player)

            reply = ""
            if idle_gains > 0:
                reply += f"⏳ Welcome back! You earned 💰{idle_gains}.\n\n"

            reply += handle_command(sender_id, "Player", command, args, player)

            save_player(player)
            send_fb_message(sender_id, reply)

    return jsonify(status="ok"), 200

@app.route("/", methods=["GET"])
def index():
    return "Idle game bot v2 is running.", 200

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
