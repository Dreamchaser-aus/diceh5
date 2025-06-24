import os
import random
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from psycopg2 import connect
from dotenv import load_dotenv
from threading import Thread
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)

# 初始化
load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")

print(f"[DEBUG] BOT_TOKEN = {BOT_TOKEN!r}")

# 数据库连接
def get_conn():
    return connect(DATABASE_URL)

# 首页跳转
@app.route("/")
def index():
    try:
        with get_conn() as conn, conn.cursor() as c:
            c.execute("""
                SELECT user_id FROM users
                WHERE phone IS NOT NULL AND is_blocked = 0
                ORDER BY created_at ASC LIMIT 1
            """)
            row = c.fetchone()
            if not row:
                return "❌ 没有可用的用户，请先注册或授权手机号", 400
            user_id = row[0]
            return f'<meta http-equiv="refresh" content="0; url=/dice_game?user_id={user_id}">'
    except Exception as e:
        return f"<pre>数据库错误：{e}</pre>", 500

# 游戏页面
@app.route("/dice_game")
def dice_game():
    return render_template("dice_game.html")

# 游戏 API
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
                      "VALUES (%s, %s, %s, %s, %s, %s)",
                      (user_id, now, user_score, bot_score, result, score))
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

# Telegram Bot 部分（使用 v21+）
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎲 欢迎来到骰子游戏机器人！发送 /start 开始")

def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.run_polling()

# 启动入口
if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
    
