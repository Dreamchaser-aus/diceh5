import os, random, logging, asyncio
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from psycopg2 import connect
from threading import Thread
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# 数据库连接
def get_conn():
    return connect(DATABASE_URL)

# 游戏首页跳转
@app.route("/")
def index():
    return "<h3>请从 Telegram 进入游戏。</h3>"

# 游戏页面
@app.route("/dice_game")
def dice_game():
    return render_template("dice_game.html")

# 游戏接口：通过 telegram_id 验证
@app.route("/api/play_game")
def play_game():
    telegram_id = request.args.get("telegram_id", type=int)
    if not telegram_id:
        return jsonify({"error": "缺少 telegram_id"}), 400

    try:
        with get_conn() as conn, conn.cursor() as c:
            c.execute("SELECT user_id, is_blocked, plays FROM users WHERE telegram_id = %s", (telegram_id,))
            row = c.fetchone()
            if not row:
                return jsonify({"error": "未绑定账号"}), 403
            user_id, is_blocked, plays = row
            if is_blocked:
                return jsonify({"error": "你已被封禁"})
            if plays >= 10:
                return jsonify({"error": "今日已达上限"})

            user_score, bot_score = random.randint(1, 6), random.randint(1, 6)
            score = 10 if user_score > bot_score else -5 if user_score < bot_score else 0
            result = '赢' if score > 0 else '输' if score < 0 else '平局'
            now = datetime.now().isoformat()

            c.execute("UPDATE users SET points = points + %s, plays = plays + 1, last_play = %s WHERE user_id = %s",
                      (score, now, user_id))
            c.execute("""INSERT INTO game_history 
                         (user_id, created_at, user_score, bot_score, result, points_change)
                         VALUES (%s, %s, %s, %s, %s, %s)""",
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
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

# Telegram Bot 绑定命令
async def bind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    first_name = update.effective_user.first_name

    with get_conn() as conn, conn.cursor() as c:
        c.execute("SELECT user_id FROM users WHERE telegram_id = %s", (telegram_id,))
        if c.fetchone():
            await update.message.reply_text("你已经绑定过账号了。")
            return

        c.execute("SELECT user_id FROM users WHERE telegram_id IS NULL LIMIT 1")
        row = c.fetchone()
        if not row:
            await update.message.reply_text("❌ 当前没有可绑定的账号，请联系管理员。")
            return

        user_id = row[0]
        c.execute("UPDATE users SET telegram_id = %s WHERE user_id = %s", (telegram_id, user_id))
        conn.commit()

    await update.message.reply_text(f"✅ 绑定成功！欢迎你，{first_name}！")

# 启动 Bot
def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("bind", bind))
    application.run_polling(close_loop=False, stop_signals=None)

# 启动 Flask 和 Bot
if __name__ == "__main__":
    Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
