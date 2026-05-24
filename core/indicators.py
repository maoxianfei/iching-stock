"""
技术指标计算 — 同时支持两种输入格式：
  1. pandas DataFrame（来自 akshare / 东方财富）
  2. List[KLine]（iching-stock 统一数据模型）

所有函数为纯函数，不依赖策略级配置（阈值通过参数传入）。
"""

import numpy as np
import pandas as pd
from typing import List, Optional

from core.models import KLine


# ══════════════════════════════════════════
# KLine list → pandas DataFrame 转换
# ══════════════════════════════════════════

def klines_to_dataframe(klines: List[KLine]) -> pd.DataFrame:
    """
    将 iching-stock 的 KLine 列表转换为 pandas DataFrame，
    列名与 a_stock_screener 兼容（中文列名）。
    """
    if not klines:
        return pd.DataFrame()
    data = {
        "日期":   [k.date for k in klines],
        "开盘":   [k.open for k in klines],
        "收盘":   [k.close for k in klines],
        "最高":   [k.high for k in klines],
        "最低":   [k.low for k in klines],
        "成交量": [k.volume for k in klines],
    }
    df = pd.DataFrame(data)
    df["涨跌幅"] = df["收盘"].pct_change() * 100
    return df


# ══════════════════════════════════════════
# 均线计算
# ══════════════════════════════════════════

def calc_ma(series: pd.Series, period: int) -> pd.Series:
    """计算移动均线（简单移动平均）"""
    return series.rolling(window=period).mean()


def calc_ma_from_klines(klines: List[KLine], period: int) -> List[float]:
    """直接从 KLine 列表计算 MA，返回等长列表（前 period-1 个为 None）"""
    closes = [k.close for k in klines]
    result = []
    for i in range(len(closes)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(closes[i - period + 1: i + 1]) / period)
    return result


def calc_ma_deviation(close: float, ma10: float) -> float:
    """
    计算价格偏离 MA10 的百分比。
    Returns: 百分比值，正数=高于均线，负数=低于均线
    """
    if ma10 is None or pd.isna(ma10) or ma10 == 0:
        return float("inf")
    return (close - ma10) / ma10 * 100


def calc_ma_convergence(ma10: float, ma20: float, ma30: float) -> float:
    """
    计算三条均线粘合度。
    Returns: max(三线) / min(三线) - 1，百分比值
    """
    mas = [ma10, ma20, ma30]
    if any(v is None or pd.isna(v) or v == 0 for v in mas):
        return float("inf")
    return (max(mas) / min(mas) - 1) * 100


def is_ma_uptrend(ma_today: float, ma_yesterday: float) -> bool:
    """判断 MA 是否向上（今日 > 昨日）"""
    if ma_yesterday is None or pd.isna(ma_yesterday) or ma_yesterday == 0:
        return False
    return ma_today > ma_yesterday


# ══════════════════════════════════════════
# 板块分类
# ══════════════════════════════════════════

def classify_board(code: str) -> str:
    """
    根据股票代码前缀判断所属板块。
    Returns: 'main', 'chinet', 'star', 'beijing'
    """
    code = str(code).zfill(6)
    if code.startswith("60") or code.startswith("00"):
        return "main"
    elif code.startswith("300") or code.startswith("301"):
        return "chinet"
    elif code.startswith("688"):
        return "star"
    elif code.startswith("8"):
        return "beijing"
    else:
        return "main"  # 默认按主板处理


def get_limit_up_threshold(
    code: str,
    limit_main: float = 9.5,
    limit_chinet: float = 19.5,
    limit_star: float = 19.5,
    limit_beijing: float = 29.5,
) -> float:
    """获取涨停阈值（阈值由调用方传入，不模块级 import config）"""
    board = classify_board(code)
    table = {
        "main": limit_main,
        "chinet": limit_chinet,
        "star": limit_star,
        "beijing": limit_beijing,
    }
    return table[board]


# ══════════════════════════════════════════
# K 线阴阳判断
# ══════════════════════════════════════════

def classify_candle_yinyang_row(row: pd.Series) -> str:
    """
    判断单根日K线的阴阳（输入为 DataFrame 行）。
    规则：收盘 > 开盘 → '阳'；收盘 < 开盘 → '阴'；相等 → '平'
    优先使用中文列名，回退到英文。
    """
    close = None
    open_ = None
    for c in ["收盘", "close"]:
        if c in row.index:
            close = row[c]
            break
    for o in ["开盘", "open"]:
        if o in row.index:
            open_ = row[o]
            break

    if close is None or open_ is None:
        return "?"

    close = float(close)
    open_ = float(open_)
    if close > open_:
        return "阳"
    elif close < open_:
        return "阴"
    else:
        return "平"


def classify_candle_yinyang_kline(k: KLine) -> str:
    """判断单根 KLine dataclass 的阴阳"""
    if k.close > k.open:
        return "阳"
    elif k.close < k.open:
        return "阴"
    else:
        return "平"


def candle_pattern_match(
    source,
    pattern: str,
    fuzzy: bool = False,
    max_offset: int = 60,
) -> tuple:
    """
    滑动窗口检测 K 线阴阳形态匹配。

    支持两种输入：
      - source: pd.DataFrame（中文列名，按日期升序）
      - source: List[KLine]（按日期升序）

    Returns:
        (是否匹配, 描述)
    """
    if isinstance(source, pd.DataFrame):
        return _candle_pattern_match_df(source, pattern, fuzzy, max_offset)
    elif isinstance(source, list) and source and isinstance(source[0], KLine):
        return _candle_pattern_match_klines(source, pattern, fuzzy, max_offset)
    else:
        return False, "不支持的数据格式"


def _candle_pattern_match_df(
    df: pd.DataFrame,
    pattern: str,
    fuzzy: bool = False,
    max_offset: int = 60,
) -> tuple:
    """DataFrame 版形态匹配"""
    if df.empty:
        return False, "无K线数据"

    if len(df) <= 1:
        return False, "无已完成K线"

    completed = df.iloc[:-1]  # 排除今日盘中
    n = len(completed)
    pattern_len = len(pattern)

    if n < pattern_len:
        return False, f"已完成K线不足{pattern_len}天(实际{n}天)"

    # 预计算所有已完成K线的阴阳序列
    candles = "".join(
        classify_candle_yinyang_row(row) for _, row in completed.iterrows()
    )

    max_start = min(n - pattern_len, max_offset)
    for offset in range(0, max_start + 1):
        start = n - pattern_len - offset
        window = candles[start: start + pattern_len]

        if fuzzy:
            ok = all(p == a or a == "平" for p, a in zip(pattern, window))
        else:
            ok = pattern == window

        if ok:
            if offset == 0:
                return True, f"最近{pattern_len}天匹配{pattern}"
            else:
                return True, f"{pattern_len + offset}天前匹配{pattern}"

    # 均不匹配 — 返回最近窗口的形态供诊断
    show_n = min(n, pattern_len + 2)
    recent_show = completed.iloc[-show_n:]
    actual_show = "".join(
        classify_candle_yinyang_row(row) for _, row in recent_show.iterrows()
    )
    return False, f"回溯{max_offset}天内未找到，最近{show_n}天K线为{actual_show}"


def _candle_pattern_match_klines(
    klines: List[KLine],
    pattern: str,
    fuzzy: bool = False,
    max_offset: int = 60,
) -> tuple:
    """KLine 列表版形态匹配"""
    if not klines or len(klines) <= 1:
        return False, "无已完成K线"

    completed = klines[:-1]  # 排除今日
    n = len(completed)
    pattern_len = len(pattern)

    if n < pattern_len:
        return False, f"已完成K线不足{pattern_len}天(实际{n}天)"

    candles = "".join(classify_candle_yinyang_kline(k) for k in completed)

    max_start = min(n - pattern_len, max_offset)
    for offset in range(0, max_start + 1):
        start = n - pattern_len - offset
        window = candles[start: start + pattern_len]

        if fuzzy:
            ok = all(p == a or a == "平" for p, a in zip(pattern, window))
        else:
            ok = pattern == window

        if ok:
            if offset == 0:
                return True, f"最近{pattern_len}天匹配{pattern}"
            else:
                return True, f"{pattern_len + offset}天前匹配{pattern}"

    show_n = min(n, pattern_len + 2)
    recent = completed[-show_n:]
    actual_show = "".join(classify_candle_yinyang_kline(k) for k in recent)
    return False, f"回溯{max_offset}天内未找到，最近{show_n}天K线为{actual_show}"


# ══════════════════════════════════════════
# 涨停检测
# ══════════════════════════════════════════

def has_limit_up(
    source,
    code: str,
    lookback: int,
    limit_main: float = 9.5,
    limit_chinet: float = 19.5,
    limit_star: float = 19.5,
    limit_beijing: float = 29.5,
) -> tuple:
    """
    检测最近 N 个交易日内是否有涨停。
    支持 source: pd.DataFrame 或 List[KLine]
    """
    if isinstance(source, pd.DataFrame):
        return _has_limit_up_df(
            source, code, lookback,
            limit_main, limit_chinet, limit_star, limit_beijing,
        )
    elif isinstance(source, list) and source and isinstance(source[0], KLine):
        return _has_limit_up_klines(
            source, code, lookback,
            limit_main, limit_chinet, limit_star, limit_beijing,
        )
    else:
        return False, "不支持的数据格式"


def _has_limit_up_df(df: pd.DataFrame, code: str, lookback: int,
                      limit_main, limit_chinet, limit_star, limit_beijing) -> tuple:
    if df.empty or len(df) < 2:
        return False, "数据不足"

    threshold = get_limit_up_threshold(code, limit_main, limit_chinet,
                                       limit_star, limit_beijing)

    n = len(df)
    start_idx = max(0, n - 1 - lookback)
    recent = df.iloc[start_idx: n - 1]  # 排除最后一行（今日盘中）
    if recent.empty:
        return False, "无历史数据"

    chg_col = None
    for col in ["涨跌幅", "pct_chg"]:
        if col in recent.columns:
            chg_col = col
            break

    if chg_col is None:
        return False, "缺少涨跌幅字段"

    limit_days = recent[recent[chg_col] >= threshold]

    if not limit_days.empty:
        days_ago = n - 1 - limit_days.index[-1]
        return True, f"{days_ago}天前涨停"

    return False, ""


def _has_limit_up_klines(klines: List[KLine], code: str, lookback: int,
                         limit_main, limit_chinet, limit_star, limit_beijing) -> tuple:
    if not klines or len(klines) < 2:
        return False, "数据不足"

    threshold = get_limit_up_threshold(code, limit_main, limit_chinet,
                                       limit_star, limit_beijing)

    # 需要涨跌幅数据，KLine 本身不含涨跌幅，需要用前一日收盘计算
    n = len(klines)
    completed = klines[:-1]  # 排除今日
    if not completed:
        return False, "无历史数据"

    start_idx = max(0, len(completed) - lookback)
    recent = completed[start_idx:]

    for i, k in enumerate(recent):
        idx_in_all = start_idx + i
        if idx_in_all == 0:
            continue
        prev_close = klines[idx_in_all - 1].close
        if prev_close == 0:
            continue
        pct = (k.close - prev_close) / prev_close * 100
        if pct >= threshold:
            days_ago = len(completed) - (start_idx + i)
            return True, f"{days_ago}天前涨停"

    return False, ""


# ══════════════════════════════════════════
# 爆量检测
# ══════════════════════════════════════════

def has_volume_spike(
    source,
    ratio: float = 2.0,
    avg_period: int = 20,
    lookback: int = 15,
) -> tuple:
    """
    检测最近 N 个交易日内是否有成交量爆量。
    爆量定义：当日成交量 ≥ ratio × 前 avg_period 日均量
    支持 source: pd.DataFrame 或 List[KLine]
    """
    if isinstance(source, pd.DataFrame):
        return _has_volume_spike_df(source, ratio, avg_period, lookback)
    elif isinstance(source, list) and source and isinstance(source[0], KLine):
        return _has_volume_spike_klines(source, ratio, avg_period, lookback)
    else:
        return False, "不支持的数据格式"


def _has_volume_spike_df(df: pd.DataFrame, ratio: float,
                         avg_period: int, lookback: int) -> tuple:
    if df.empty or len(df) < avg_period + lookback:
        return False, "数据不足"

    vol_col = None
    for col in ["成交量", "volume"]:
        if col in df.columns:
            vol_col = col
            break

    if vol_col is None:
        return False, "缺少成交量字段"

    volume = df[vol_col].values
    total = len(volume)

    if total <= 1:
        return False, "数据不足"

    volume_completed = volume[:total - 1]  # 排除最后一天（今日盘中）
    n_completed = len(volume_completed)

    for i in range(avg_period, n_completed):
        avg_vol = volume[i - avg_period:i].mean()
        if avg_vol == 0:
            continue
        if volume[i] >= ratio * avg_vol:
            days_ago = n_completed - i
            if days_ago <= lookback:
                return True, f"{days_ago}天前爆量({volume[i]/avg_vol:.1f}倍)"

    return False, ""


def _has_volume_spike_klines(klines: List[KLine], ratio: float,
                             avg_period: int, lookback: int) -> tuple:
    if not klines or len(klines) < avg_period + lookback:
        return False, "数据不足"

    completed = klines[:-1]  # 排除今日
    if len(completed) < avg_period:
        return False, "数据不足"

    volumes = [k.volume for k in completed]

    for i in range(avg_period, len(volumes)):
        avg_vol = sum(volumes[i - avg_period:i]) / avg_period
        if avg_vol == 0:
            continue
        if volumes[i] >= ratio * avg_vol:
            days_ago = len(volumes) - i
            if days_ago <= lookback:
                return True, f"{days_ago}天前爆量({volumes[i]/avg_vol:.1f}倍)"

    return False, ""


# ══════════════════════════════════════════
# 综合信号
# ══════════════════════════════════════════

def has_signal(
    source,
    code: str,
    lookback: int,
    limit_main: float = 9.5,
    limit_chinet: float = 19.5,
    limit_star: float = 19.5,
    limit_beijing: float = 29.5,
    spike_ratio: float = 2.0,
    spike_period: int = 20,
) -> tuple:
    """综合信号：涨停 或 爆量"""
    limit_up, desc1 = has_limit_up(
        source, code, lookback,
        limit_main, limit_chinet, limit_star, limit_beijing,
    )
    if limit_up:
        return True, desc1

    spike, desc2 = has_volume_spike(
        source, ratio=spike_ratio,
        avg_period=spike_period, lookback=lookback,
    )
    if spike:
        return True, desc2

    return False, ""
