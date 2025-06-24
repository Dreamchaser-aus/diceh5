import os
import random
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from psycopg2 import connect
from dotenv import load_dotenv
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

# 初始化
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "mysecret")  # 登录用密钥

DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")

def get_conn():
    return connect(DATABASE_URL)

# --- 登录系统 ---
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "123456")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin")
        return render_template("login.html", error="登录失败")
    return render_template("login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/admin/login")

@app.route("/admin")
def admin_dashboard():
    if not session.get("admin"):
        return redirect("/admin/login")
    with get_conn() as conn, conn.cursor() as c:
        c.execute("SELECT user_id, username, phone, points, plays FROM users ORDER BY points DESC")
        users = c.fetchall()
        c.execute("SELECT user_id, user_score, bot_score, result, created_at FROM game_history ORDER BY created_at DESC LIMIT 20")
        history = c.fetchall()
    return render_template("dashboard.html", users=users, history=history)

# --- 游戏入口与API ---
@app.route("/")
def index():
    with get_conn() as conn, conn.cursor() as c:
        c.execute("SELECT user_id FROM users WHERE phone IS NOT NULL AND is_blocked = 0 ORDER BY created_at ASC LIMIT 1")
        row = c.fetchone()
        if not row:
            return "❌ 没有可用的用户，请先注册或授权手机号", 400
        return f'<meta http-equiv="refresh" content="0; url=/dice_game?user_id={row[0]}">'

@app.route("/dice_game")
def dice_game():
    return render_template("dice_game.html")

@app.route("/api/play_game")
def api_play_game():
    try:
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "缺少 user_id 参数"}), 400

        with get_conn() as conn, conn.cursor() as c:
            c.execute("SELECT is_blocked, plays, phone FROM users WHERE user_id = %s", (user_id,))
            row = c.fetchone()
            if not row:
                return jsonify({"error": "用户未注册"}), 400
            is_blocked, plays, phone = row
            if is_blocked:
                return jsonify({"error": "你已被封禁"})
            if not phone:
                return jsonify({"error": "请先授权手机号"})
            if plays >= 10:
                return jsonify({"error": "今日已达游戏次数上限"})

            user_score = random.randint(1, 6)
            bot_score = random.randint(1, 6)
            score = 10 if user_score > bot_score else -5 if user_score < bot_score else 0
            result = '赢' if score > 0 else '输' if score < 0 else '平局'
            now = datetime.now().isoformat()

            c.execute("UPDATE users SET points = points + %s, plays = plays + 1, last_play = %s WHERE user_id = %s",
                      (score, now, user_id))
            c.execute("INSERT INTO game_history (user_id, created_at, user_score, bot_score, result, points_change) "
                      "VALUES (%s, %s, %s, %s, %s, %s)", (user_id, now, user_score, bot_score, result, score))
            c.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
            total = c.fetchone()[0]
            conn.commit()

        return jsonify({
            "user_score": user_score,
            "bot_score": bot_score,
            "message": f"你{result}了！{'+' if score > 0 else ''}{score} 分",
            "total_points": total
        })
    except Exception as e:
        import traceback
        return jsonify({"error": "服务器错误", "trace": traceback.format_exc()}), 500

# --- Telegram Bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎲 欢迎来到骰子游戏机器人！发送 /start 开始")

def run_bot():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    loop.run_until_complete(application.run_polling(close_loop=False))

# --- 每日重置任务 ---
def reset_daily():
    with get_conn() as conn, conn.cursor() as c:
        c.execute("UPDATE users SET plays = 0 WHERE plays > 0")
        conn.commit()

scheduler = BackgroundScheduler()
scheduler.add_job(reset_daily, "cron", hour=0)
scheduler.start()

if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
