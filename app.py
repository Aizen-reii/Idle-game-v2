"""
Facebook Messenger Idle Game Bot
---------------------------------
A `.`-prefixed command bot with an economy, mining, pets, and a few
mini-games, plus a paginated `.help` menu.

Setup:
    1. pip install -r requirements.txt
    2. Set environment variables:
         PAGE_ACCESS_TOKEN  - from your Meta Developer Dashboard
         VERIFY_TOKEN       - a secret string you choose, used during webhook setup
    3. Run: python app.py
    4. Point your Messenger webhook at https://<your-host>/webhook

Storage: SQLite (players.db), created automatically on first run.
"""

import os
import time
import random
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "YOUR_FACEBOOK_PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "your_secret_webhook_verify_token")
PREFIX = "."

PASSIVE_GOLD_PER_SECOND = 1
DB_PATH = os.path.join(os.path.dirname(__file__), "players.db")

GRAPH_API_URL = "https://graph.facebook.com/v19.0/me/messages"

BOT_START_TIME = time.time()
COMMAND_USE_COUNT = {}  # in-memory counter, resets on restart


# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------

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
            pet_last_fed REAL DEFAULT 0
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
            last_daily = ?, pet_name = ?, pet_level = ?, pet_last_fed = ?
        WHERE user_id = ?
    """, (
        player["gold"], player["bank"], player["mine_level"], player["last_active"],
        player["last_daily"], player["pet_name"], player["pet_level"], player["pet_last_fed"],
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


# ---------------------------------------------------------------------------
# GAME LOGIC
# ---------------------------------------------------------------------------

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
        resp = requests.post(GRAPH_API_URL, params=params, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"[FB API ERROR] {resp.status_code}: {resp.text}")
    except requests.RequestException as e:
        print(f"[FB API EXCEPTION] {e}")


# ---------------------------------------------------------------------------
# HELP MENU (paginated, styled to match the requested layout)
# ---------------------------------------------------------------------------

HELP_PAGES = {
    1: {
        "📚 INFO": ["help", "balance", "myinfo", "prefix", "status", "sysinfo", "uid", "uptime"],
        "🛠️ UTILITY": ["accept", "theme"],
        "💰 ECONOMY": ["atm", "bal", "bank", "coin", "mine", "richest", "top", "daily", "upgrade"],
        "🎀 GAME": ["8ball", "guessnumber", "pet", "quiz", "slot"],
    },
    2: {
        "🎀 GAME (cont.)": ["duel"],
    },
}


def build_help_page(user_name, page):
    pages = sorted(HELP_PAGES.keys())
    if page not in HELP_PAGES:
        page = 1
    total_pages = len(pages)
    now = datetime.now()

    header = (
        "╭━━━━━━━━━━━━─\n"
        f"│ 👤 User     : {user_name}\n"
        f"│ 🏷️ Prefix   : {PREFIX}\n"
        f"│ ✨ Commands : {sum(len(cmds) for page in HELP_PAGES.values() for cmds in page.values())}\n"
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


COMMAND_DETAILS = {
    "mine": "⛏️ .mine — Actively swing your pickaxe for an instant gold payout, scaled by your mine level.",
    "upgrade": "🚀 .upgrade — Spend gold to raise your mine level, boosting both passive and active mining gold.",
    "pet": "🐾 .pet — View your pet. .pet buy [name] adopts one (💰500). .pet feed grows it. .pet lb shows the leaderboard.",
    "daily": "🎁 .daily — Claim a once-per-24h gold bonus.",
    "bal": "💰 .bal — Check your gold and bank balance.",
    "bank": "🏦 .bank deposit/withdraw [amount] — Move gold between your wallet and bank.",
}


# ---------------------------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------------------------

def handle_command(user_id, user_name, command, args, player):
    reply = ""

    if command == "help":
        if args and args[0].isdigit():
            reply = build_help_page(user_name, int(args[0]))
        elif args and args[0].lower() in COMMAND_DETAILS:
            reply = COMMAND_DETAILS[args[0].lower()]
        elif args:
            reply = f"❌ Unknown command '{args[0]}'. Try {PREFIX}help for the full list."
        else:
            reply = build_help_page(user_name, 1)

    elif command in ("balance", "bal"):
        reply = (
            f"📊 PLAYER PROFILE\n"
            f"────────────────\n"
            f"💰 Wallet: {player['gold']} gold\n"
            f"🏦 Bank:   {player['bank']} gold\n"
            f"⛏️ Mine Level: {player['mine_level']}"
        )

    elif command == "myinfo":
        reply = (
            f"👤 {user_name}\n"
            f"🆔 ID: {user_id}\n"
            f"💰 Gold: {player['gold']}  |  🏦 Bank: {player['bank']}\n"
            f"⛏️ Mine Lv.{player['mine_level']}  |  🐾 Pet: {player['pet_name'] or 'None'}"
        )

    elif command == "uid":
        reply = f"🆔 Your user ID: {user_id}"

    elif command == "prefix":
        reply = f"🏷️ My prefix is: {PREFIX}"

    elif command == "uptime":
        secs = int(time.time() - BOT_START_TIME)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        reply = f"⏱️ Uptime: {h}h {m}m {s}s"

    elif command == "status":
        reply = "✅ Bot is online and responding normally."

    elif command == "sysinfo":
        reply = f"🖥️ Python bot | Players tracked: {len(top_players(limit=10_000))}"

    elif command == "cmdstats":
        top = sorted(COMMAND_USE_COUNT.items(), key=lambda x: -x[1])[:10]
        reply = "📈 Most-used commands (since restart):\n" + "\n".join(
            f"• {c}: {n}" for c, n in top
        ) if top else "No commands used yet."

    elif command == "coin":
        result = random.choice(["Heads", "Tails"])
        reply = f"🪙 The coin landed on **{result}**!"

    elif command == "8ball":
        answers = ["Yes.", "No.", "Ask again later.", "Definitely!", "Very doubtful.", "Absolutely not."]
        if not args:
            reply = "❓ Ask a yes/no question after .8ball"
        else:
            reply = f"🎱 {random.choice(answers)}"

    elif command == "guessnumber":
        secret = random.randint(1, 10)
        reply = (
            "🔢 I'm thinking of a number between 1 and 10... "
            f"(psst, it was {secret} — full guessing-game state isn't wired up yet, "
            "this is a placeholder roll)"
        )

    elif command == "quiz":
        qa = [("What planet is known as the Red Planet?", "mars")]
        q, _ = random.choice(qa)
        reply = f"❓ {q}\n(Answer checking isn't wired up in this version yet.)"

    elif command == "slot":
        symbols = ["🍒", "🍋", "🔔", "💎", "7️⃣"]
        spin = [random.choice(symbols) for _ in range(3)]
        cost = 20
        if player["gold"] < cost:
            reply = f"❌ Slots cost 💰{cost} to play."
        else:
            player["gold"] -= cost
            win = spin[0] == spin[1] == spin[2]
            if win:
                payout = cost * 10
                player["gold"] += payout
                reply = f"🎰 {' '.join(spin)}\n🎉 JACKPOT! You won 💰{payout}!"
            else:
                reply = f"🎰 {' '.join(spin)}\nNo match. Better luck next spin."

    elif command == "mine":
        gains = 10 * player["mine_level"]
        player["gold"] += gains
        reply = f"⛏️ SMASH! You mined 💰{gains} gold!"

    elif command == "upgrade":
        cost = player["mine_level"] * 250
        if player["gold"] >= cost:
            player["gold"] -= cost
            player["mine_level"] += 1
            reply = f"🚀 UPGRADE SUCCESSFUL! Mine is now Level {player['mine_level']}."
        else:
            reply = f"❌ Upgrading costs 💰{cost}. You need {cost - player['gold']} more."

    elif command == "daily":
        now = time.time()
        cooldown = 24 * 3600
        elapsed = now - player["last_daily"]
        if elapsed < cooldown:
            hrs_left = int((cooldown - elapsed) // 3600)
            reply = f"⏳ Already claimed. Try again in about {hrs_left}h."
        else:
            bonus = random.randint(100, 300)
            player["gold"] += bonus
            player["last_daily"] = now
            reply = f"🎁 Daily bonus claimed: 💰{bonus} gold!"

    elif command == "atm":
        reply = f"🏧 Wallet: 💰{player['gold']}  |  🏦 Bank: 💰{player['bank']}"

    elif command == "bank":
        if not args or args[0] not in ("deposit", "withdraw") or len(args) < 2 or not args[1].isdigit():
            reply = f"🏦 Usage: {PREFIX}bank deposit [amount]  /  {PREFIX}bank withdraw [amount]"
        else:
            amount = int(args[1])
            if args[0] == "deposit":
                if amount > player["gold"]:
                    reply = "❌ You don't have that much gold on hand."
                else:
                    player["gold"] -= amount
                    player["bank"] += amount
                    reply = f"🏦 Deposited 💰{amount}. Bank balance: 💰{player['bank']}."
            else:
                if amount > player["bank"]:
                    reply = "❌ You don't have that much in the bank."
                else:
                    player["bank"] -= amount
                    player["gold"] += amount
                    reply = f"🏧 Withdrew 💰{amount}. Wallet balance: 💰{player['gold']}."

    elif command == "richest" or command == "top":
        richest = top_players(order_by="gold", limit=5)
        reply = "🏆 RICHEST PLAYERS 🏆\n───────────────────\n"
        if not richest:
            reply += "No players yet."
        else:
            for i, p in enumerate(richest, 1):
                reply += f"{i}. User ...{p['user_id'][-4:]}: 💰{p['gold']}\n"

    elif command == "pet":
        sub = args[0].lower() if args else ""
        if sub in ("leaderboard", "lb"):
            pets = top_players(order_by="pet_level", limit=5)
            reply = "🏆 PET LEADERBOARD 🏆\n───────────────────\n"
            pets = [p for p in pets if p["pet_level"] > 0]
            if not pets:
                reply += "No pets registered yet."
            else:
                for i, p in enumerate(pets, 1):
                    reply += f"{i}. User ...{p['user_id'][-4:]}: {p['pet_name']} (Lv.{p['pet_level']})\n"
        elif sub == "buy":
            if player["pet_name"]:
                reply = f"❌ You already have a companion, {player['pet_name']}!"
            elif player["gold"] < 500:
                reply = "❌ Adopting a pet costs 💰500."
            else:
                pet_name = " ".join(args[1:]) or "Buddy"
                player["gold"] -= 500
                player["pet_name"] = pet_name
                player["pet_level"] = 1
                reply = f"🐾 Congratulations! You adopted **{pet_name}**! Use {PREFIX}pet feed to grow them."
        elif sub == "feed":
            if not player["pet_name"]:
                reply = f"❌ You don't have a pet. Use {PREFIX}pet buy [name] first."
            else:
                cooldown = 60
                elapsed = time.time() - player["pet_last_fed"]
                if elapsed < cooldown:
                    reply = f"⏱️ {player['pet_name']} is full. Wait {int(cooldown - elapsed)}s."
                elif player["gold"] < 50:
                    reply = "❌ Pet kibble costs 💰50."
                else:
                    player["gold"] -= 50
                    player["pet_level"] += 1
                    player["pet_last_fed"] = time.time()
                    reply = f"🐾 {player['pet_name']} grew to Level {player['pet_level']}!"
        else:
            if player["pet_name"]:
                reply = f"🐾 {player['pet_name']} — Level {player['pet_level']}"
            else:
                reply = f"🐾 You don't have a pet yet. Try {PREFIX}pet buy [name]."

    elif command == "duel":
        reply = "⚔️ Duels aren't wired up yet — this needs a second player and a wager system. Let me know if you want that built out."

    elif command == "theme":
        reply = "🎨 Theme switching isn't implemented in this build yet."

    elif command == "accept":
        reply = "✅ Nothing pending to accept right now."

    else:
        reply = f"❓ Unknown command. Try {PREFIX}help"

    COMMAND_USE_COUNT[command] = COMMAND_USE_COUNT.get(command, 0) + 1
    return reply


# ---------------------------------------------------------------------------
# WEBHOOK ROUTES
# ---------------------------------------------------------------------------

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
                reply += f"⏳ Welcome back! You earned 💰{idle_gains} gold while away.\n\n"

            reply += handle_command(sender_id, "Player", command, args, player)

            save_player(player)
            send_fb_message(sender_id, reply)

    return jsonify(status="ok"), 200


@app.route("/", methods=["GET"])
def index():
    return "Idle game bot is running.", 200


# Always initialize the database on import, so it also works when this file
# is started by a production server (e.g. `gunicorn app:app`) rather than
# run directly with `python app.py`.
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
