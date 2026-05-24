"""
MA粘合策略

条件（AND关系）：
  1. pre_filter: 盘中涨跌幅在 [price_drop_min, price_drop_max] 范围内
  2. 最新价在 MA10 ±ma_deviation% 范围内
  3. MA10/MA20/MA30 粘合度 ≤ ma_convergence%
  4. MA10 向上趋势（今日 > 昨日）
  5. signal_lookback 日内涨停或爆量（OR）
"""

from typing import Dict, Any, List, Optional

import pandas as pd

from backtest.strategy_base import BaseStrategy, FilterResult
from core.indicators import (
    calc_ma, calc_ma_deviation, calc_ma_convergence,
    is_ma_uptrend, has_signal,
)


class MaConvergenceStrategy(BaseStrategy):
    """
    MA粘合策略：跌幅区间内 + MA10附近 + MA10/20/30粘合
                + MA10向上 + lookback日内涨停/爆量
    """

    def __init__(
        self,
        price_drop_min: float = -1.5,
        price_drop_max: float = 0.0,
        ma_deviation: float = 2.0,
        ma_convergence: float = 3.0,
        signal_lookback: int = 15,
        limit_main: float = 9.5,
        limit_chinet: float = 19.5,
        limit_star: float = 19.5,
        limit_beijing: float = 29.5,
        spike_ratio: float = 2.0,
        spike_period: int = 20,
    ):
        super().__init__(name="MA粘合策略")
        self.price_drop_min = price_drop_min
        self.price_drop_max = price_drop_max
        self.ma_deviation = ma_deviation
        self.ma_convergence = ma_convergence
        self.signal_lookback = signal_lookback
        self.limit_main = limit_main
        self.limit_chinet = limit_chinet
        self.limit_star = limit_star
        self.limit_beijing = limit_beijing
        self.spike_ratio = spike_ratio
        self.spike_period = spike_period

    @property
    def min_history_days(self) -> int:
        return max(30, self.signal_lookback + self.spike_period)

    @property
    def description(self) -> str:
        return (
            "MA粘合策略："
            f"涨跌幅[{self.price_drop_min}%,{self.price_drop_max}%] + "
            f"MA10偏离≤{self.ma_deviation}% + "
            f"MA10/20/30粘合≤{self.ma_convergence}% + "
            f"MA10向上 + "
            f"{self.signal_lookback}日内涨停/爆量"
        )

    # ── 粗筛 ─────────

    def pre_filter(self, snapshot: Dict[str, Any]) -> bool:
        pct = snapshot.get("pct_change", 0)
        if pct is None:
            return False
        return self.price_drop_min <= pct <= self.price_drop_max

    # ── 精筛 ─────────

    def analyze(
        self,
        snapshot: Dict[str, Any],
        history_df: Optional[pd.DataFrame] = None,
        history_klines: Optional[list] = None,
    ) -> List[FilterResult]:
        """
        精筛：基于历史K线计算5个条件。
        优先使用 history_df（DataFrame格式），
        若传入 history_klines（List[KLine]）则自动转换。
        """
        # 自动转换 KLine → DataFrame
        if history_df is None and history_klines is not None:
            from core.indicators import klines_to_dataframe
            history_df = klines_to_dataframe(history_klines)

        if history_df is None or history_df.empty:
            return [FilterResult("数据", False, "无历史K线数据")]

        code = snapshot.get("code", "")
        price = snapshot.get("price", 0)

        close_col = self._find_col(history_df, ["收盘", "close"])

        # 条件1：MA10 偏离度
        ma10_series = calc_ma(history_df[close_col], 10)
        ma10 = ma10_series.iloc[-1]
        dev = calc_ma_deviation(price, ma10)
        r1 = FilterResult(
            "MA10偏离度",
            abs(dev) <= self.ma_deviation,
            "" if abs(dev) <= self.ma_deviation
            else f"偏离{dev:.2f}% (阈值±{self.ma_deviation}%)",
        )

        # 条件2：MA10/20/30 粘合
        ma20 = calc_ma(history_df[close_col], 20).iloc[-1]
        ma30 = calc_ma(history_df[close_col], 30).iloc[-1]
        conv = calc_ma_convergence(ma10, ma20, ma30)
        r2 = FilterResult(
            "均线粘合度",
            conv <= self.ma_convergence,
            "" if conv <= self.ma_convergence
            else f"粘合度{conv:.2f}% (阈值≤{self.ma_convergence}%)",
        )

        # 条件3：MA10 向上趋势
        if len(ma10_series) >= 2:
            ma10_yesterday = ma10_series.iloc[-2]
        else:
            ma10_yesterday = None
        trending = is_ma_uptrend(ma10, ma10_yesterday)
        r3 = FilterResult(
            "MA10趋势",
            trending,
            "" if trending else "MA10未向上",
        )

        # 条件4：涨停/爆量信号
        signal, desc = has_signal(
            history_df,
            code,
            lookback=self.signal_lookback,
            limit_main=self.limit_main,
            limit_chinet=self.limit_chinet,
            limit_star=self.limit_star,
            limit_beijing=self.limit_beijing,
            spike_ratio=self.spike_ratio,
            spike_period=self.spike_period,
        )
        r4 = FilterResult(
            "涨停/爆量信号",
            signal,
            desc if signal else f"{self.signal_lookback}日内无信号",
        )

        return [r1, r2, r3, r4]

    # ── 工具 ─────────

    @staticmethod
    def _find_col(df: pd.DataFrame, candidates: List[str]) -> str:
        for c in candidates:
            if c in df.columns:
                return c
        raise KeyError(f"历史数据缺少必要列。可用列: {list(df.columns)}")
