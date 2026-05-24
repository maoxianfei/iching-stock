"""
统一数据获取层 — 支持 A股 (mootdx) + 美股/港股 (Yahoo Finance)
输出统一 KLine dataclass，支持日线/周线/月线三周期

统一接口:
  fetch_klines(code, interval, count, market)
    - market="auto" → 自动识别市场
    - market="a/hk/us" → 显式指定市场
    - interval="daily/weekly/monthly"
"""

import re
import json
import requests
from datetime import datetime
from collections import OrderedDict
from typing import Optional

from core.models import KLine, detect_market, normalize_symbol, get_stock_name


# ============================================================
# A股数据获取 — mootdx
# ============================================================

def _fetch_a_stock_klines(symbol: str, interval: str, count: int) -> list[KLine]:
    """
    A股 K 线 — 使用 mootdx
    interval: "daily" (日线) / "weekly" (周线) / "monthly" (月线)
    """
    try:
        from mootdx.quotes import Quotes
    except ImportError:
        raise ImportError("请先安装 mootdx: pip install mootdx")

    frequency_map = {"daily": 9, "weekly": 5, "monthly": 6}
    frequency = frequency_map.get(interval)
    if frequency is None:
        raise ValueError(f"A股不支持的周期: {interval}，可选 daily/weekly/monthly")

    client = Quotes.factory(market='std')

    # 确定市场: 6/9开头=上海, 其余=深圳
    if symbol.startswith(("6", "9")):
        market = 1
    else:
        market = 0

    df = client.bars(symbol=symbol, frequency=frequency, offset=count)

    if df is None or df.empty:
        raise RuntimeError(f"mootdx 未返回数据: {symbol}")

    result = []
    for _, row in df.iterrows():
        # mootdx 可能返回 datetime 字符串或 year/month/day 整数列
        dt_str = str(row.get("datetime", ""))
        if dt_str and dt_str != "nan" and len(dt_str) >= 10:
            date_str = str(dt_str)[:10]
        else:
            # 旧版 mootdx 返回 year, month, day 整数列
            y = int(row.get('year', 0))
            m = int(row.get('month', 1))
            d = int(row.get('day', 1))
            date_str = f"{y:04d}-{m:02d}-{d:02d}"

        if not date_str or date_str == "0000-00-00":
            continue

        def _f(key, default=0.0):
            v = row.get(key, default)
            return float(v) if v is not None else default

        result.append(KLine(
            date=date_str,
            open=_f('open'),
            high=_f('high'),
            low=_f('low'),
            close=_f('close'),
            volume=float(_f('vol', 0)),
        ))

    # 按日期升序排列（mootdx 返回的是从近到远）
    result.sort(key=lambda k: k.date)
    return result


# ============================================================
# 美股/港股数据获取 — Yahoo Finance
# ============================================================

def _fetch_yahoo_klines(symbol: str, interval: str, count: int,
                         market: str = "us") -> list[KLine]:
    """
    美股/港股 K 线 — Yahoo Finance chart API
    如果 Yahoo 不可用，回退到新浪(美股)或腾讯(港股)日线聚合
    """
    # 先尝试 Yahoo
    try:
        return _fetch_yahoo_klines_direct(symbol, interval, count, market)
    except Exception as e:
        yahoo_error = str(e)

    # 美股回退: 新浪日线 → 周/月聚合
    if market == "us":
        print(f"      Yahoo 不可用 ({yahoo_error})，使用新浪日线聚合...")
        return _fetch_us_klines_from_sina(symbol, interval, count)

    # 港股回退: 腾讯日线 → 周/月聚合
    if market == "hk":
        print(f"      Yahoo 不可用 ({yahoo_error})，使用腾讯日线聚合...")
        return _fetch_hk_klines_from_tencent(symbol, interval, count)

    raise RuntimeError(f"未知市场 K线获取失败: {yahoo_error}")


def _fetch_yahoo_klines_direct(symbol: str, interval: str, count: int,
                                market: str) -> list[KLine]:
    """Yahoo Finance chart API 直接调用"""
    interval_map = {"daily": "1d", "weekly": "1wk", "monthly": "1mo"}
    yf_interval = interval_map.get(interval)
    if yf_interval is None:
        raise ValueError(f"Yahoo 不支持的周期: {interval}")

    if market == "hk":
        yf_symbol = f"{symbol}.HK"
    else:
        yf_symbol = symbol

    # range 映射 (根据需要的数量近似)
    if count <= 30:
        range_val = "1mo"
    elif count <= 90:
        range_val = "3mo"
    elif count <= 250:
        range_val = "1y"
    elif count <= 500:
        range_val = "2y"
    elif count <= 1250:
        range_val = "5y"
    else:
        range_val = "max"

    if interval == "monthly" and count > 36:
        range_val = "5y"

    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    try:
        session.get("https://fc.yahoo.com", timeout=15)
    except Exception:
        session.get("https://finance.yahoo.com", timeout=15)

    # 尝试获取 crumb
    try:
        crumb_r = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=15)
        crumb_r.raise_for_status()
        crumb = crumb_r.text.strip()
    except Exception:
        crumb = None

    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{yf_symbol}"
    params = {
        "interval": yf_interval,
        "range": range_val,
        "includePrePost": "false",
    }
    if crumb:
        params["crumb"] = crumb

    r = session.get(url, params=params, timeout=30)
    r.raise_for_status()

    data = r.json()
    chart = data.get("chart", {}).get("result", [{}])[0]
    timestamps = chart.get("timestamp", [])
    quote = chart.get("indicators", {}).get("quote", [{}])[0]

    result = []
    for i, ts in enumerate(timestamps):
        o = quote["open"][i]
        h = quote["high"][i]
        l = quote["low"][i]
        c = quote["close"][i]
        v = quote["volume"][i]

        if c is None:
            continue

        result.append(KLine(
            date=datetime.fromtimestamp(ts).strftime('%Y-%m-%d'),
            open=round(float(o), 2) if o else 0,
            high=round(float(h), 2) if h else 0,
            low=round(float(l), 2) if l else 0,
            close=round(float(c), 2),
            volume=float(v) if v else 0.0,
        ))

    if len(result) > count:
        result = result[-count:]

    return result


# ============================================================
# 港股回退 — 腾讯日线聚合
# ============================================================

def _fetch_hk_klines_from_tencent(symbol: str, interval: str,
                                   count: int) -> list[KLine]:
    """
    港股 K 线 — 腾讯 fqkline 日线 → 周/月聚合
    腾讯格式: [日期, 开盘价, 收盘价, 最高价, 最低价, 成交量]
    """
    daily_count = count * 25 if interval == "monthly" else count * 7
    daily_count = max(daily_count, 500)
    daily_count = min(daily_count, 720)  # 腾讯最多返回720条

    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"hk{symbol},day,,,{daily_count},qfq"}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    if data.get("code") != 0:
        raise RuntimeError(f"腾讯港股K线返回错误: {data.get('msg', 'unknown')}")

    klines = data.get("data", {}).get(f"hk{symbol}", {}).get("day", [])
    if not klines:
        raise RuntimeError(f"腾讯港股未返回日线数据: {symbol}")

    daily_klines = []
    for item in klines:
        # 腾讯格式: [date, open, close, high, low, volume]
        daily_klines.append(KLine(
            date=item[0],
            open=float(item[1]),
            high=float(item[3]),
            low=float(item[4]),
            close=float(item[2]),
            volume=float(item[5]),
        ))

    if not daily_klines:
        raise RuntimeError(f"腾讯港股解析后无有效数据: {symbol}")

    daily_klines.sort(key=lambda k: k.date)

    if interval == "daily":
        return daily_klines[-count:]
    elif interval == "weekly":
        return _aggregate_to_weekly(daily_klines)[-count:]
    else:
        return _aggregate_to_monthly(daily_klines)[-count:]


# ============================================================
# 美股回退 — 新浪日线聚合
# ============================================================

def _fetch_us_klines_from_sina(symbol: str, interval: str,
                                count: int) -> list[KLine]:
    """
    美股 K 线 — 新浪日线 → 周/月聚合
    """
    # 获取足够多的日线数据用于聚合
    daily_count = count * 25 if interval == "monthly" else count * 7
    daily_count = max(daily_count, 500)

    url = "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var/US_MinKService.getDailyK"
    params = {"symbol": symbol.upper(), "num": daily_count}
    r = requests.get(url, params=params, headers={
        "Referer": "https://finance.sina.com.cn/"
    }, timeout=30)

    m = re.search(r'\((\[.+\])\)', r.text)
    if not m:
        raise RuntimeError(f"新浪美股日线数据解析失败: {symbol}")

    items = json.loads(m.group(1))
    daily_klines = []
    for item in items:
        daily_klines.append(KLine(
            date=item.get("d", ""),
            open=float(item.get("o", 0)),
            high=float(item.get("h", 0)),
            low=float(item.get("l", 0)),
            close=float(item.get("c", 0)),
            volume=float(item.get("v", 0)),
        ))

    if not daily_klines:
        raise RuntimeError(f"新浪美股未返回日线数据: {symbol}")

    daily_klines.sort(key=lambda k: k.date)

    if interval == "daily":
        return daily_klines[-count:]
    elif interval == "weekly":
        return _aggregate_to_weekly(daily_klines)[-count:]
    else:
        return _aggregate_to_monthly(daily_klines)[-count:]


# ============================================================
# 日线 → 周线/月线聚合
# ============================================================

def _aggregate_to_weekly(daily: list[KLine]) -> list[KLine]:
    """日线 → 周线聚合"""
    weeks = OrderedDict()

    for k in daily:
        dt = datetime.strptime(k.date, '%Y-%m-%d')
        iso = dt.isocalendar()
        week_key = f"{iso[0]}-W{iso[1]:02d}"

        if week_key not in weeks:
            weeks[week_key] = []
        weeks[week_key].append(k)

    result = []
    for week_key, bars in weeks.items():
        result.append(KLine(
            date=bars[0].date,                     # 周一日期
            open=bars[0].open,                      # 周一开盘
            high=max(b.high for b in bars),         # 周最高
            low=min(b.low for b in bars),           # 周最低
            close=bars[-1].close,                   # 周五收盘
            volume=sum(b.volume for b in bars),     # 周总成交量
        ))

    return result


def _aggregate_to_monthly(daily: list[KLine]) -> list[KLine]:
    """日线 → 月线聚合"""
    months = OrderedDict()

    for k in daily:
        month_key = k.date[:7]  # YYYY-MM
        if month_key not in months:
            months[month_key] = []
        months[month_key].append(k)

    result = []
    for month_key, bars in months.items():
        result.append(KLine(
            date=bars[-1].date,
            open=bars[0].open,
            high=max(b.high for b in bars),
            low=min(b.low for b in bars),
            close=bars[-1].close,
            volume=sum(b.volume for b in bars),
        ))

    return result


# ============================================================
# 统一入口
# ============================================================

def fetch_klines(
    code: str,
    interval: str = "monthly",
    count: int = 24,
    market: str = "auto",
) -> list[KLine]:
    """
    统一 K 线获取入口

    Args:
        code: 股票代码 (600519 / AAPL / 00700)
        interval: 周期 ("daily" / "weekly" / "monthly")
        count: 获取数量（默认 24）
        market: 市场类型 ("auto" 自动识别 / "a" A股 / "hk" 港股 / "us" 美股)

    Returns:
        list[KLine]: 按日期升序排列
    """
    if market == "auto":
        symbol, detected_market = normalize_symbol(code)
        # normalize_symbol 返回 "a"/"hk"/"us"
    else:
        symbol = code.strip().upper()
        if market == "hk":
            symbol = symbol.replace('.HK', '').zfill(5)
        detected_market = market

    # 内部市场标识映射
    market_map = {"a": "a", "hk": "hk", "us": "us",
                  "a_stock": "a", "hk_stock": "hk", "us_stock": "us"}
    mkt = market_map.get(detected_market, detected_market)

    if mkt == "a":
        klines = _fetch_a_stock_klines(symbol, interval, count)
    elif mkt in ("hk", "us"):
        klines = _fetch_yahoo_klines(symbol, interval, count, mkt)
    else:
        raise ValueError(f"不支持的市场: {detected_market}")

    if not klines:
        raise RuntimeError(f"未能获取到数据: {symbol} ({mkt})")

    return klines
