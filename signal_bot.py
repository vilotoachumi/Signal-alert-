import os
import io
import time
import requests
import pytz
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime
from telegram import Bot
from apscheduler.schedulers.background import BackgroundScheduler

# === Your Credentials ===
TELEGRAM_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
TELEGRAM_CHAT_ID = "7765972595"
TWELVE_DATA_API_KEY = "4ccb15917ae74f2187aee708f1f1afe1"

# === Configuration ===
symbols = ['EUR/USD', 'USD/JPY', 'GBP/USD', 'BTC/USD', 'XAU/USD']
confirm_timeframes = ['15min', '1h']
main_interval = '15min'
min_bars = 100

# === Fetch Data from Twelve Data ===
def fetch_data(symbol, interval):
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={min_bars}&apikey={TWELVE_DATA_API_KEY}"
        response = requests.get(url).json()
        if 'values' not in response:
            raise Exception(response.get('message', 'No data returned.'))
        df = pd.DataFrame(response['values'])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime')
        df.set_index('datetime', inplace=True)
        df = df.astype(float)
        return df
    except Exception as e:
        print(f"[❌] Fetch failed: {symbol} @ {interval} → {e}")
        return None

# === Strategy Logic ===
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def apply_strategy(df):
    df['EMA20'] = df['close'].ewm(span=20).mean()
    df['EMA50'] = df['close'].ewm(span=50).mean()
    df['RSI'] = compute_rsi(df['close'], 14)
    df['MACD'] = df['close'].ewm(12).mean() - df['close'].ewm(26).mean()
    df['MACD_signal'] = df['MACD'].ewm(9).mean()

    if len(df) < 50:
        return None

    ema_cross = df['EMA20'].iloc[-2] < df['EMA50'].iloc[-2] and df['EMA20'].iloc[-1] > df['EMA50'].iloc[-1]
    rsi_ok = df['RSI'].iloc[-1] > 50
    macd_ok = df['MACD'].iloc[-1] > df['MACD_signal'].iloc[-1]

    if ema_cross and rsi_ok and macd_ok:
        return 'Buy'

    ema_cross_down = df['EMA20'].iloc[-2] > df['EMA50'].iloc[-2] and df['EMA20'].iloc[-1] < df['EMA50'].iloc[-1]
    rsi_down = df['RSI'].iloc[-1] < 50
    macd_down = df['MACD'].iloc[-1] < df['MACD_signal'].iloc[-1]

    if ema_cross_down and rsi_down and macd_down:
        return 'Sell'

    return None

# === Chart Drawing ===
def generate_chart(df, signal, symbol):
    last_price = df['close'].iloc[-1]
    sl = df['low'].iloc[-10:-1].min() if signal == 'Buy' else df['high'].iloc[-10:-1].max()
    tp = last_price + (last_price - sl) * 1.5 if signal == 'Buy' else last_price - (sl - last_price) * 1.5

    ap = [
        mpf.make_addplot(df['EMA20'], color='blue'),
        mpf.make_addplot(df['EMA50'], color='red'),
        mpf.make_addplot([None]*(len(df)-1) + [last_price],
                         scatter=True, markersize=200,
                         marker='^' if signal == 'Buy' else 'v',
                         color='green' if signal == 'Buy' else 'red'),
    ]

    fig, ax = mpf.plot(df[-50:], type='candle', style='yahoo', addplot=ap,
                       returnfig=True, volume=False,
                       title=f'{symbol} - {signal} Signal',
                       ylabel='Price')

    ax[0].axhline(sl, color='red', linestyle='--', label='Stop Loss')
    ax[0].axhline(tp, color='green', linestyle='--', label='Take Profit')
    ax[0].legend()

    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return buf

# === Send Alert ===
def send_signal(symbol, signal, chart_image):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        message = f"📣 *{symbol}* - *{signal} Signal*\n🕒 {timestamp} UTC"
        bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=chart_image, caption=message, parse_mode='Markdown')
        print(f"[✅] Alert sent for {symbol}")
    except Exception as e:
        print(f"[❌] Telegram error for {symbol}: {e}")

# === Main Bot Logic ===
def scan():
    print(f"\n🔎 Scan started @ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    for symbol in symbols:
        print(f"🔍 Checking {symbol}...")
        signals = []
        for tf in confirm_timeframes:
            df = fetch_data(symbol, tf)
            if df is None:
                print(f"[⚠️] Skipping {symbol} due to missing data on {tf}")
                break
            signal = apply_strategy(df)
            signals.append(signal)
        if len(signals) == len(confirm_timeframes) and signals.count(signals[0]) == len(signals) and signals[0] in ['Buy', 'Sell']:
            main_df = fetch_data(symbol, main_interval)
            if main_df is not None:
                chart = generate_chart(main_df, signals[0], symbol)
                send_signal(symbol, signals[0], chart)
        else:
            print(f"[ℹ️] No consensus signal for {symbol}")

# === Scheduler ===
scheduler = BackgroundScheduler(timezone=pytz.utc)
scheduler.add_job(scan, 'interval', minutes=15)
scheduler.start()

print("[🚀] Signal bot running every 15 min with 15min + 1h confirmation...")

# === Loop ===
try:
    while True:
        time.sleep(60)
except (KeyboardInterrupt, SystemExit):
    scheduler.shutdown()
    print("[🛑] Bot stopped.")
