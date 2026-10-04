"""Shared Kraken pair names, paths and fixed collection boundaries."""
import gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/kraken'
OUT = ROOT / 'data/prices'
START = 1483315200  # 2017-01-02 00:00 UTC
BOUNDARY = 1782864000  # 2026-07-01 00:00 UTC
END = 1790985600  # 2026-10-03 00:00 UTC, exclusive
PAIRS = {
    'XMR': ('XMRUSD', 'XXMRZUSD'),
    'BTC': ('XBTUSD', 'XXBTZUSD'),
    'ZEC': ('ZECUSD', 'XZECZUSD'),
    'LTC': ('LTCUSD', 'XLTCZUSD'),
}

def coin_symbol(value):
    value = value.upper().replace('/', '')
    if value.endswith('USD'):
        value = value[:-3]
    if value == 'XBT':
        value = 'BTC'
    if value not in PAIRS:
        raise ValueError(f'Unsupported pair: {value}')
    return value

def trade_dir(coin):
    return RAW / 'trades' if coin == 'XMR' else RAW / 'trades' / coin.lower()

def validation_dir(coin):
    return RAW / 'validation' if coin == 'XMR' else RAW / 'validation' / coin.lower()

def archive_path(coin):
    path = RAW / f'{PAIRS[coin][0]}_1.csv'
    return path if path.exists() else path.with_suffix('.csv.gz')

def open_text(path):
    return gzip.open(path, 'rt', encoding='utf-8', newline='') if str(path).endswith('.gz') else Path(path).open(encoding='utf-8', newline='')

def minute_path(coin):
    return OUT / f'{coin.lower()}_usd_1m.csv.gz'

def volume_column(coin):
    return f'volume_{coin.lower()}'

def minute_columns(coin):
    return ['timestamp_unix', 'timestamp_utc', 'open_usd', 'high_usd', 'low_usd', 'close_usd', volume_column(coin), 'trade_count', 'source']
