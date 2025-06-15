import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
import pytz
import datetime
import telegram

# === CONFIG ===
TELEGRAM_TOKEN = "7613620588:AAEui2boeLqJ7ukxmjiiUNF8njOgEUoWRM8"
TELEGRAM_CHAT_ID = "7765972595"
TWELVE_DATA_API_KEY = "4ccb15917ae74f2187aee708f1f1afe1"
symbols = [
    {"symbol": "EUR/USD", "exchange": "forex"},
    {"symbol": "USD/JPY", "exchange": "forex"},
    {"symbol": "GBP/USD", "exchange": "forex"},
    {"symbol": "XAU/USD", "exchange": "forex"},
    {"symbol": "BTC/USD", "exchange": "binance"},
]
interval = "15min"
min_bars = 100

bot = telegram.Bot(token=TELEGRAM_TOKEN)

def fetch_data(symbol, exchange):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&exchange={exchange}&interval={interval}&outputsize={min_bars}&apikey={TWELVE_DATA_API_KEY}"
    response = requests.get(url).json()
    if 'values' not in response:
        raise ValueError(response.get('message', 'Data fetch error'))
    df = pd.DataFrame(response['values'])
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')
    df.set_index('datetime', inplace=True)
    df = df.astype(float)
    return df

def detect_zones(df, lookback=20):
    recent = df[-lookback:]
    demand = recent[recent['low'] == recent['low'].min()]
    supply = recent[recent['high'] == recent['high'].max()]
    return demand['low'].values[0], supply['high'].values[0]

def triple_confirmation(df):
    df['EMA20'] = df['close'].ewm(span=20).mean()
    df['EMA50'] = df['close'].ewm(span=50).mean()
    df['RSI'] = compute_rsi(df['close'])
    df['MACD'], df['MACD_signal'] = compute_macd(df['close'])

    latest = df.iloc[-1]

    buy_signal = (
        latest['EMA20'] > latest['EMA50'] and
        latest['RSI'] > 50 and
        latest['MACD'] > latest['MACD_signal']
    )
    sell_signal = (
        latest['EMA20'] < latest['EMA50'] and
        latest['RSI'] < 50 and
        latest['MACD'] < latest['MACD_signal']
    )
    return buy_signal, sell_signal

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(window=period).mean()
    avg_loss = pd.Series(loss).rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def compute_macd(series):
    exp1 = series.ewm(span=12, adjust=False).mean()
    exp2 = series.ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal

def check_price_breakout(df, demand, supply):
    latest_close = df['close'].iloc[-1]
    if latest_close > supply:
        return "breakout_up"
    elif latest_close < demand:
        return "breakout_down"
    return None

def plot_chart(df, symbol):
    mpf.plot(
        df[-50:],
        type='candle',
        style='charles',
        title=f"{symbol} - 15min",
        ylabel='Price',
        volume=False,
        savefig=f"{symbol.replace('/', '')}.png"
    )

def send_alert(symbol, signal_type, breakout=None):
    chart_file = f"{symbol.replace('/', '')}.png"
    caption = f"🔔 Signal: {signal_type}\nSymbol: {symbol}"
    if breakout:
        caption += f"\n🚀 Breakout: {breakout.replace('_', ' ').title()}"
    with open(chart_file, 'rb') as photo:
        bot.send_photo(chat_id=TELEGRAM_CHAT_ID, photo=photo, caption=caption)

def run_signal_scan():
    for item in symbols:
        symbol, exchange = item["symbol"], item["exchange"]
        try:
            df = fetch_data(symbol, exchange)
            demand, supply = detect_zones(df)
            buy, sell = triple_confirmation(df)
            breakout = check_price_breakout(df, demand, supply)
            plot_chart(df, symbol)

            if buy:
                send_alert(symbol, "BUY", breakout)
            elif sell:
                send_alert(symbol, "SELL", breakout)

            print(f"[✅] {symbol} scanned.")
        except Exception as e:
            print(f"[❌] {symbol} error: {e}")

# Scheduler setup
scheduler = BackgroundScheduler(timezone=pytz.utc)
scheduler.add_job(run_signal_scan, 'interval', minutes=15)
scheduler.start()

# Manual run once at startup
run_signal_scan()
