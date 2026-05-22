"""
统一数据获取层 — 支持 A股 (mootdx) + 美股/港股 (Yahoo Finance)
输出统一 KLine dataclass
"""

import re
import requests
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ============================================================
# 数据结构
# ============================================================

@dataclass
class KLine:
    """统一 K 线数据结构"""
    date: str          # "YYYY-MM-DD"
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    @property
    def is_yang(self) -> bool:
        """阳线：收盘 >= 开盘"""
        return self.close >= self.open


# ============================================================
# 市场识别
# ============================================================

def detect_market(code: str) -> str:
    """
    根据代码格式自动识别市场
    - "600519" / "000001" / "300750" → "a_stock"
    - "AAPL" / "TSLA" / "BABA" → "us_stock"
    - "00700" / "09988" / "01810" → "hk_stock"
    """
    code = code.strip().upper()

    # A股：6位纯数字
    if re.match(r'^\d{6}$', code):
        return "a_stock"

    # 港股：5位数字（也可能带.HK后缀）
    if re.match(r'^\d{5}$', code):
        return "hk_stock"
    if code.endswith('.HK'):
        return "hk_stock"

    # 美股：纯字母，2-5个字符
    if re.match(r'^[A-Z]{1,5}$', code):
        return "us_stock"

    raise ValueError(f"无法识别股票代码市场: {code}")


def normalize_symbol(code: str) -> tuple[str, str]:
    """
    标准化股票代码，返回 (原始代码, 市场类型)
    """
    market = detect_market(code)
    symbol = code.strip().upper()

    if market == "hk_stock":
        # 去掉 .HK 后缀
        symbol = symbol.replace('.HK', '')
        # 补齐5位
        symbol = symbol.zfill(5)

    return symbol, market


# ============================================================
# A股数据获取 — mootdx
# ============================================================

def _fetch_a_stock_klines(symbol: str, interval: str, count: int) -> list[KLine]:
    """
    A股 K 线 — 使用 mootdx
    interval: "weekly" → category=5, "monthly" → category=6
    """
    try:
        from mootdx.quotes import Quotes
    except ImportError:
        raise ImportError("请先安装 mootdx: pip install mootdx")

    frequency_map = {"weekly": 5, "monthly": 6}
    frequency = frequency_map.get(interval)
    if frequency is None:
        raise ValueError(f"A股不支持的周期: {interval}，可选 weekly/monthly")

    client = Quotes.factory(market='std')
    df = client.bars(symbol=symbol, frequency=frequency, offset=count)

    if df is None or df.empty:
        raise RuntimeError(f"mootdx 未返回数据: {symbol}")

    result = []
    for _, row in df.iterrows():
        # mootdx 月线/周线返回 year, month, day 整数列，直接构造日期
        y = int(row.get('year', 0))
        m = int(row.get('month', 1))
        d = int(row.get('day', 1))
        date_str = f"{y:04d}-{m:02d}-{d:02d}"

        # 获取价格字段
        def _f(key, default=0.0):
            v = row.get(key, default)
            return float(v) if v is not None else default

        result.append(KLine(
            date=date_str,
            open=_f('open'),
            high=_f('high'),
            low=_f('low'),
            close=_f('close'),
            volume=int(_f('vol', 0)),
        ))

    # 按日期升序排列（mootdx 返回的是从近到远）
    result.sort(key=lambda k: k.date)
    return result


# ============================================================
# 美股/港股数据获取 — Yahoo Finance
# ============================================================

def _fetch_yahoo_klines(symbol: str, interval: str, count: int,
                         market: str = "us_stock") -> list[KLine]:
    """
    美股/港股 K 线 — Yahoo Finance chart API
    如果 Yahoo 不可用，美股回退到新浪日线聚合
    """
    # 先尝试 Yahoo
    try:
        return _fetch_yahoo_klines_direct(symbol, interval, count, market)
    except Exception as e:
        yahoo_error = str(e)

    # 美股回退: 新浪日线 → 周/月聚合
    if market == "us_stock":
        print(f"      Yahoo 不可用 ({yahoo_error})，使用新浪日线聚合...")
        return _fetch_us_klines_from_sina(symbol, interval, count)

    # 港股回退: 腾讯日线 → 周/月聚合
    if market == "hk_stock":
        print(f"      Yahoo 不可用 ({yahoo_error})，使用腾讯日线聚合...")
        return _fetch_hk_klines_from_tencent(symbol, interval, count)

    raise RuntimeError(
        f"未知市场 K线获取失败: {yahoo_error}"
    )


def _fetch_yahoo_klines_direct(symbol: str, interval: str, count: int,
                                market: str) -> list[KLine]:
    """Yahoo Finance chart API 直接调用"""
    interval_map = {"weekly": "1wk", "monthly": "1mo"}
    yf_interval = interval_map.get(interval)
    if yf_interval is None:
        raise ValueError(f"Yahoo 不支持的周期: {interval}")

    if market == "hk_stock":
        yf_symbol = f"{symbol}.HK"
    else:
        yf_symbol = symbol

    range_val = "5y" if (interval == "monthly" and count > 36) else "3y"

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
            volume=int(v) if v else 0,
        ))

    if len(result) > count:
        result = result[-count:]

    return result


def _fetch_hk_klines_from_tencent(symbol: str, interval: str,
                                   count: int) -> list[KLine]:
    """
    港股 K 线 — 腾讯 fqkline 日线 → 周/月聚合
    interval: "weekly" → 聚合为周线, "monthly" → 聚合为月线
    腾讯格式: [日期, 开盘价, 收盘价, 最高价, 最低价, 成交量]
    """
    import json

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
            volume=int(float(item[5])),
        ))

    if not daily_klines:
        raise RuntimeError(f"腾讯港股解析后无有效数据: {symbol}")

    daily_klines.sort(key=lambda k: k.date)

    if interval == "weekly":
        return _aggregate_to_weekly(daily_klines)[-count:]
    else:
        return _aggregate_to_monthly(daily_klines)[-count:]


def _fetch_us_klines_from_sina(symbol: str, interval: str,
                                count: int) -> list[KLine]:
    """
    美股 K 线 — 新浪日线 → 周/月聚合
    interval: "weekly" → 聚合为周线, "monthly" → 聚合为月线
    """
    import json

    # 获取足够多的日线数据用于聚合
    # 月线: count根月线 → 约 count*21 个交易日 → 取 count*25 根日线保证足够
    daily_count = count * 25 if interval == "monthly" else count * 7
    # 至少取 500 根日线 (约2年)
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
            volume=int(item.get("v", 0)),
        ))

    if not daily_klines:
        raise RuntimeError(f"新浪美股未返回日线数据: {symbol}")

    # 按日期排序
    daily_klines.sort(key=lambda k: k.date)

    # 聚合为周线/月线
    if interval == "weekly":
        return _aggregate_to_weekly(daily_klines)[-count:]
    else:
        return _aggregate_to_monthly(daily_klines)[-count:]


def _aggregate_to_weekly(daily: list[KLine]) -> list[KLine]:
    """日线 → 周线聚合"""
    from collections import OrderedDict
    weeks = OrderedDict()

    for k in daily:
        # 获取 ISO 周编号 (year-week)
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
    from collections import OrderedDict
    months = OrderedDict()

    for k in daily:
        month_key = k.date[:7]  # YYYY-MM
        if month_key not in months:
            months[month_key] = []
        months[month_key].append(k)

    result = []
    for month_key, bars in months.items():
        # 取最后一个交易日作为月线日期
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

def fetch_klines(symbol: str, interval: str = "monthly",
                 count: int = 24) -> list[KLine]:
    """
    统一 K 线获取入口

    Args:
        symbol: 股票代码 (600519 / AAPL / 00700)
        interval: 周期 ("weekly" / "monthly")
        count: 获取数量（默认 24，即 24 根月线或周线）

    Returns:
        list[KLine]: 按日期升序排列
    """
    symbol, market = normalize_symbol(symbol)

    if market == "a_stock":
        klines = _fetch_a_stock_klines(symbol, interval, count)
    else:
        klines = _fetch_yahoo_klines(symbol, interval, count, market)

    if not klines:
        raise RuntimeError(f"未能获取到数据: {symbol} ({market})")

    return klines


# ============================================================
# 获取股票名称（用于报告标题）
# ============================================================

def get_stock_name(symbol: str, market: str = "") -> str:
    """尝试获取股票中文名称"""
    if not market:
        _, market = normalize_symbol(symbol)

    try:
        if market == "a_stock":
            # 使用腾讯行情接口获取A股名称
            # 上海: 600/601/603/605/688, 深圳: 000/001/002/003/300/301
            if symbol.startswith(('6', '68')):
                prefix = "sh"
            else:
                prefix = "sz"
            url = f"https://qt.gtimg.cn/q={prefix}{symbol}"
            r = requests.get(url, timeout=10)
            r.encoding = "gbk"
            # 格式: v_sh600519="1~贵州茅台~..."
            m = re.search(r'"([^"]+)"', r.text)
            if m:
                parts = m.group(1).split("~")
                if len(parts) > 1 and parts[1]:
                    return parts[1]
        elif market == "us_stock":
            # 使用新浪获取中文名
            url = f"https://hq.sinajs.cn/list=gb_{symbol.lower()}"
            r = requests.get(url, headers={
                "Referer": "https://finance.sina.com.cn/",
                "User-Agent": "Mozilla/5.0",
            }, timeout=10)
            r.encoding = "gbk"
            m = re.search(r'"(.+?)"', r.text)
            if m:
                return m.group(1).split(",")[0]
        elif market == "hk_stock":
            # 使用腾讯获取中文名
            url = f"https://qt.gtimg.cn/q=r_hk{symbol}"
            r = requests.get(url, timeout=10)
            r.encoding = "gbk"
            m = re.search(r'"(.+?)"', r.text)
            if m:
                return m.group(1).split("~")[1]
    except Exception:
        pass

    return symbol
