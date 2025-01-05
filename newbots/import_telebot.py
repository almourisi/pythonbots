from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, JobQueue
import requests
import pandas as pd
import pandas_ta as ta
from concurrent.futures import ThreadPoolExecutor
import time
import matplotlib.pyplot as plt
import logging

# إعداد سجل الأخطاء
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levellevel)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# توكن البوت
BOT_TOKEN = "8139823264:AAGK947IH6riOFNti4QOEklBLgoxXzNDcXQ"

# معرف القناة الفريد
CHANNEL_ID = "@Future_Deals"

# دالة لجلب بيانات الشموع وتحليلها لكل زوج
def analyze_symbol(symbol):
    logger.info(f"Analyzing symbol: {symbol}")

    # جلب بيانات فريم ساعة واحدة لاكتشاف الصفقات وتحديد نقاط الدخول والخروج
    klines_url_1h = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=100"
    try:
        klines_response_1h = requests.get(klines_url_1h)
        klines_response_1h.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching 1h data for {symbol}: {e}")
        return None

    klines_data_1h = klines_response_1h.json()
    if not klines_data_1h:
        logger.warning(f"No data returned for {symbol}")
        return None

    df_1h = pd.DataFrame(klines_data_1h, columns=["time", "open", "high", "low", "close", "volume", "close_time", "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"])
    df_1h["close"] = pd.to_numeric(df_1h["close"])
    df_1h["high"] = pd.to_numeric(df_1h["high"])
    df_1h["low"] = pd.to_numeric(df_1h["low"])

    # إضافة المؤشرات الفنية
    df_1h["ema_9"] = ta.ema(df_1h["close"], length=9)
    df_1h["ema_21"] = ta.ema(df_1h["close"], length=21)
    df_1h["rsi"] = ta.rsi(df_1h["close"], length=14)
    df_1h["volume"] = df_1h["volume"]
    
    # حساب مؤشر بولينجر باندز
    bbands = ta.bbands(df_1h["close"], length=20, std=2)
    df_1h["bollinger_upper"] = bbands["BBU_20_2.0"]
    df_1h["bollinger_middle"] = bbands["BBM_20_2.0"]
    df_1h["bollinger_lower"] = bbands["BBL_20_2.0"]

    # حساب مؤشر MACD
    macd = ta.macd(df_1h["close"], fast=12, slow=26, signal=9)
    df_1h["macd"] = macd["MACD_12_26_9"]
    df_1h["macd_signal"] = macd["MACDs_12_26_9"]
    df_1h["macd_hist"] = macd["MACDh_12_26_9"]

    close_price = df_1h["close"].iloc[-1]

    # طباعة القيم المستخدمة في التحليل لتصحيح الأخطاء
    logger.info(f"Symbol: {symbol}, EMA9: {df_1h['ema_9'].iloc[-1]}, EMA21: {df_1h['ema_21'].iloc[-1]}, RSI: {df_1h['rsi'].iloc[-1]}, Close: {close_price}, BB Lower: {df_1h['bollinger_lower'].iloc[-1]}, BB Upper: {df_1h['bollinger_upper'].iloc[-1]}")

    # تحديد مستويات الدعم والمقاومة على فريم ساعة واحدة
    support_1h = df_1h["low"].min()
    resistance_1h = df_1h["high"].max()

    # تحديد الصفقات بناءً على المؤشرات
    if df_1h["ema_9"].iloc[-1] > df_1h["ema_21"].iloc[-1] and df_1h["rsi"].iloc[-1] < 55 and close_price <= df_1h["bollinger_lower"].iloc[-1]:
        entry = close_price
        stop_loss = support_1h - (support_1h * 0.01)  # إيقاف الخسارة بعد الدعم
        take_profit = resistance_1h - (resistance_1h * 0.01)  # أخذ الربح قبل المقاومة
        logger.info(f"Buy signal for {symbol}")
        return {
            "symbol": symbol,
            "price": close_price,
            "side": "شراء 🟢",
            "entry": round(entry, 4),
            "take_profit": round(take_profit, 4),
            "stop_loss": round(stop_loss, 4),
            "support": support_1h,
            "resistance": resistance_1h,
            "trend": "صاعد 📈"
        }
    elif df_1h["ema_9"].iloc[-1] < df_1h["ema_21"].iloc[-1] and df_1h["rsi"].iloc[-1] > 45 and close_price >= df_1h["bollinger_upper"].iloc[-1]:
        entry = close_price
        stop_loss = resistance_1h + (resistance_1h * 0.01)  # إيقاف الخسارة بعد المقاومة
        take_profit = support_1h + (support_1h * 0.01)  # أخذ الربح قبل الدعم
        logger.info(f"Sell signal for {symbol}")
        return {
            "symbol": symbol,
            "price": close_price,
            "side": "بيع 🔴",
            "entry": round(entry, 4),
            "take_profit": round(take_profit, 4),
            "stop_loss": round(stop_loss, 4),
            "support": support_1h,
            "resistance": resistance_1h,
            "trend": "هابط 📉"
        }
    logger.info(f"No signal for {symbol}")
    return None

# دالة لجلب بيانات الشموع وتحليلها لجميع الأزواج
def fetch_crypto_signals():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching ticker data: {e}")
        return []

    data = response.json()

    symbols = [item["symbol"] for item in data if item["symbol"].endswith("USDT") and float(item["volume"]) > 100000 and abs(float(item["priceChangePercent"])) > 2]

    signals = []
    with ThreadPoolExecutor() as executor:
        results = executor.map(analyze_symbol, symbols)
        for result in results:
            if result:
                signals.append(result)

    # اختيار أفضل 5 صفقات
    signals = signals[:5]

    return signals

# دالة لإرسال التوصيات بشكل دوري
async def send_signals(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    signals = fetch_crypto_signals()

    if not signals:
        await context.bot.send_message(chat_id, "لم أجد أي صفقات مناسبة حاليًا. 🚫")
    else:
        reply = "📊 أفضل التوصيات:\n\n"
        for signal in signals:
            reply += (
                f"🔹 <b>العملة</b>: {signal['symbol']}\n"
                f"📈 <b>الجانب</b>: {signal['side']}\n"
                f"💰 <b>السعر الحالي</b>: {signal['price']:.4f}\n"
                f"🚀 <b>سعر الدخول</b>: {signal['entry']:.4f}\n"
                f"🎯 <b>أخذ الربح</b>: {signal['take_profit']:.4f}\n"
                f"🛑 <b>إيقاف الخسارة</b>: {signal['stop_loss']:.4f}\n"
                f"📉 <b>الدعم</b>: {signal['support']:.4f}\n"
                f"📈 <b>المقاومة</b>: {signal['resistance']:.4f}\n"
                f"📈 <b>الاتجاه العام</b>: {signal['trend']}\n\n"
            )
            # إنشاء الرسم البياني وحفظه كصورة
            plt.figure(figsize=(10, 5))
            plt.plot(signal['price'], label='Price')
            plt.axhline(y=signal['entry'], color='g', linestyle='--', label='Entry')
            plt.axhline(y=signal['take_profit'], color='b', linestyle='--', label='Take Profit')
            plt.axhline(y=signal['stop_loss'], color='r', linestyle='--', label='Stop Loss')
            plt.legend()
            plt.title(f"{signal['symbol']} - {signal['side']}")
            plt.xlabel('Time')
            plt.ylabel('Price')
            plt.grid(True)
            plt.savefig(f"{signal['symbol']}.png")
            plt.close()

            # إرسال الصورة عبر Telegram
            with open(f"{signal['symbol']}.png", 'rb') as photo:
                await context.bot.send_photo(chat_id, photo)

        await send_message_in_chunks(chat_id, reply, context)

# دالة الترحيب
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("بدء إرسال التوصيات", callback_data='start_sending_signals'),
            InlineKeyboardButton("إيقاف إرسال التوصيات", callback_data='stop_sending_signals'),
        ],
        [InlineKeyboardButton("جلب التوصيات الآن", callback_data='get_signals')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("مرحبًا! استخدم الأزرار أدناه للتحكم في البوت:", reply_markup=reply_markup)

# دالة جلب التوصيات
async def get_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جاري جلب البيانات، الرجاء الانتظار... ⏳")
    signals = fetch_crypto_signals()

    if not signals:
        await update.message.reply_text("لم أجد أي صفقات مناسبة حاليًا. 🚫")
    else:
        reply = "📊 أفضل التوصيات:\n\n"
        for signal in signals:
            reply += (
                f"🔹 <b>العملة</b>: {signal['symbol']}\n"
                f"📈 <b>الجانب</b>: {signal['side']}\n"
                f"💰 <b>السعر الحالي</b>: {signal['price']:.4f}\n"
                f"🚀 <b>سعر الدخول</b>: {signal['entry']:.4f}\n"
                f"🎯 <b>أخذ الربح</b>: {signal['take_profit']:.4f}\n"
                f"🛑 <b>إيقاف الخسارة</b>: {signal['stop_loss']:.4f}\n"
                f"📉 <b>الدعم</b>: {signal['support']:.4f}\n"
                f"📈 <b>المقاومة</b>: {signal['resistance']:.4f}\n"
                f"📈 <b>الاتجاه العام</b>: {signal['trend']}\n\n"
            )
            # إنشاء الرسم البياني وحفظه كصورة
            plt.figure(figsize=(10, 5))
            plt.plot(signal['price'], label='Price')
            plt.axhline(y=signal['entry'], color='g', linestyle='--', label='Entry')
            plt.axhline(y=signal['take_profit'], color='b', linestyle='--', label='Take Profit')
            plt.axhline(y=signal['stop_loss'], color='r', linestyle='--', label='Stop Loss')
            plt.legend()
            plt.title(f"{signal['symbol']} - {signal['side']}")
            plt.xlabel('Time')
            plt.ylabel('Price')
            plt.grid(True)
            plt.savefig(f"{signal['symbol']}.png")
            plt.close()

            # إرسال الصورة عبر Telegram
            with open(f"{signal['symbol']}.png", 'rb') as photo:
                await context.bot.send_photo(update.message.chat_id, photo)

        await send_message_in_chunks(update.message.chat_id, reply, context)

        # طباعة الصفقات في التيرمينال
        logger.info("📊 أفضل التوصيات:\n")
        for signal in signals:
            logger.info(
                f"🔹 <b>العملة</b>: {signal['symbol']}\n"
                f"📈 <b>الجانب</b>: {signal['side']}\n"
                f"💰 <b>السعر الحالي</b>: {signal['price']:.4f}\n"
                f"🚀 <b>سعر الدخول</b>: {signal['entry']:.4f}\n"
                f"🎯 <b>أخذ الربح</b>: {signal['take_profit']:.4f}\n"
                f"🛑 <b>إيقاف الخسارة</b>: {signal['stop_loss']:.4f}\n"
                f"📉 <b>الدعم</b>: {signal['support']:.4f}\n"
                f"📈 <b>المقاومة</b>: {signal['resistance']}\n"
                f"📈 <b>الاتجاه العام</b>: {signal['trend']}\n"
            )

# دالة لإرسال الرسائل على دفعات
async def send_message_in_chunks(chat_id, text, context, chunk_size=4096):
    for i in range(0, len(text), chunk_size):
        await context.bot.send_message(chat_id, text[i:i+chunk_size], parse_mode="HTML")

# دالة لبدء الجدولة
async def start_sending_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    job_queue = context.application.job_queue
    job_queue.run_repeating(send_signals, interval=60, first=0, data=chat_id, name=str(chat_id))  # كل دقيقة
    await update.message.reply_text("تم بدء إرسال التوصيات بشكل دوري كل دقيقة.")

# دالة لإيقاف الجدولة
async def stop_sending_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_jobs = context.application.job_queue.get_jobs_by_name(str(update.message.chat_id))
    if current_jobs:
        for job in current_jobs:
            job.schedule_removal()
        await update.message.reply_text("تم إيقاف إرسال التوصيات.")
    else:
        await update.message.reply_text("لا توجد مهام مجدولة.")

# دالة لمعالجة الأزرار التفاعلية
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'start_sending_signals':
        await start_sending_signals(query, context)
    elif query.data == 'stop_sending_signals':
        await stop_sending_signals(query, context)
    elif query.data == 'get_signals':
        await get_signals(query, context)

# تشغيل البوت
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))
app.add_handler(CommandHandler("get_signals", get_signals))
app.add_handler(CommandHandler("start_sending_signals", start_sending_signals))
app.add_handler(CommandHandler("stop_sending_signals", stop_sending_signals))

app.run_polling()   
