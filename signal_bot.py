
import os
import io
import time
import requests
import pytz
import pandas as pd
import mplfinance as mpf
from datetime import datetime
from telegram import Bot
from apscheduler.schedulers.background import BackgroundScheduler

# === Credentials ===
TELEGRAM_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
TELEGRAM_CHAT_ID = "7765972595"
TWELVE_DATA_API_KEY = "4ccb15917ae74f2187aee708f1f1afe1"
FINNHUB_API_KEY = "YOUR_FINNHUB_API_KEY"

# === Config ===
symbols = ['EUR/USD', 'USD/JPY', 'GBP/USD', 'BTC/USD', 'XAU/USD']
interval = '15min'

def format_symbol(symbol):
    return symbol.replace('/', '')

def fetch_data(symbol):
    try:
        formatted_symbol = format_symbol(symbol)
        url = f"https://api.twelvedata.com/time_series?symbol={formatted_symbol}&interval={interval}&outputsize=100&apikey={TWELVE_DATA_API_KEY}&format=JSON"
        response = requests.get(url).json()
        if 'values' not in response:
            raise ValueError(response.get('message', 'No data'))
        df = pd.DataFrame(response['values'])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime')
        df.set_index('datetime', inplace=True)
        df = df.astype(float)
        return df
    except Exception as e:
        print(f"[❌] Error fetching {symbol}: {e}")
        return None

def check_signal(df):
    df['EMA20'] = df['close'].ewm(span=20).mean()
    df['EMA50'] = df['close'].ewm(span=50).mean()
    if len(df) < 3:
        return None
    if df['EMA20'].iloc[-2] < df['EMA50'].iloc[-2] and df['EMA20'].iloc[-1] > df['EMA50'].iloc[-1]:
        return 'Buy'
    elif df['EMA20'].iloc[-2] > df['EMA50'].iloc[-2] and df['EMA20'].iloc[-1] < df['EMA50'].iloc[-1]:
        return 'Sell'
    else:
        return None

def generate_chart(df, signal, symbol):
    df_chart = df[['open', 'high', 'low', 'close']].copy()
    df_chart.index.name = 'Date'
    add_plot = [
        mpf.make_addplot(df['EMA20'], color='blue'),
        mpf.make_addplot(df['EMA50'], color='red'),
        mpf.make_addplot([None]*(len(df_chart)-1) + [df['close'].iloc[-1]],
                         scatter=True, markersize=100,
                         marker='^' if signal == 'Buy' else 'v',
                         color='green' if signal == 'Buy' else 'red')
    ]
    buf = io.BytesIO()
    mpf.plot(df_chart, type='candle', style='yahoo',
             addplot=add_plot, title=f"{symbol} - {signal} Signal",
             ylabel='Price', volume=False, savefig=buf)
    buf.seek(0)
    return buf

def send_signal(symbol, signal, chart_image):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        message = f"📣 *{symbol}* - *{signal} Signal Detected!*
🕒 {timestamp} UTC"
        bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=chart_image, caption=message, parse_mode='Markdown')
        print(f"[📤] {symbol} - {signal} signal sent.")
    except Exception as e:
        print(f"[❌] Telegram error: {e}")

def scan():
    print(f"
[⏳] Scan started at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    for symbol in symbols:
        df = fetch_data(symbol)
        if df is None or len(df) < 60:
            continue
        signal = check_signal(df)
        if signal:
            chart = generate_chart(df, signal, symbol)
            send_signal(symbol, signal, chart)

scheduler = BackgroundScheduler(timezone=pytz.utc)
scheduler.add_job(scan, 'interval', minutes=15)
scheduler.start()

try:
    while True:
        time.sleep(60)
except (KeyboardInterrupt, SystemExit):
    scheduler.shutdown()
