"""
易经选股策略 — 基于连续日K线阴阳形态序列匹配。

默认形态：阳阴阳阴阴阴阳（7连阴阳节奏）

用户可传入自定义 pattern 字符串，格式如 '阳阴阳阴阴阴阳'。
"""

from typing import Dict, Any, List, Optional

import pandas as pd

from backtest.strategy_base import BaseStrategy, FilterResult
from core.indicators import candle_pattern_match


class YijingStrategy(BaseStrategy):
    """
    易经选股：连续N天日K线形态精确匹配。

      strict_recent=True（默认）: 只看最近连续N天，精确匹配
      strict_recent=False       : 回溯60天滑动窗口搜索

      fuzzy=True                 : 模糊匹配（十字星'平'视为通配）
      start_date / end_date      : 限制K线数据的时间范围（YYYYMMDD）
                                 传入后历史K线只取此区间
    """

    def __init__(
        self,
        pattern: str = "阳阴阳阴阴阴阳",
        strict_recent: bool = True,
        fuzzy: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        super().__init__(name="易经选股")
        self.pattern = pattern
        self.strict_recent = strict_recent
        self.fuzzy = fuzzy
        self.start_date = start_date
        self.end_date = end_date

    @property
    def min_history_days(self) -> int:
        base = len(self.pattern) + 2
        return base if self.strict_recent else base + 60

    @property
    def description(self) -> str:
        mode = "最近连续" if self.strict_recent else "回溯60天滑动"
        match = "模糊" if self.fuzzy else "严格"
        desc = f"易经选股（{mode}+{match}匹配）：K线形态={self.pattern}"
        if self.start_date or self.end_date:
            rng = f"{self.start_date or '...'}~{self.end_date or '...'}"
            desc += f"，时间范围={rng}"
        return desc

    # ── 粗筛 ─────────

    def pre_filter(self, snapshot: Dict[str, Any]) -> bool:
        # 粗筛不过滤，全部流入精筛做形态匹配
        return True

    # ── 精筛 ─────────

    def analyze(
        self,
        snapshot: Dict[str, Any],
        history_df: Optional[pd.DataFrame] = None,
        history_klines: Optional[list] = None,
    ) -> List[FilterResult]:
        """
        精筛：K线形态匹配。
        支持两种历史数据输入（自动选择或转换）：
          - history_df: pandas DataFrame
          - history_klines: List[KLine]
        """
        source = history_df

        # 若未传入 DataFrame，尝试用 KLine 列表转换
        if source is None and history_klines is not None:
            from core.indicators import klines_to_dataframe
            source = klines_to_dataframe(history_klines)

        if source is None or (isinstance(source, pd.DataFrame) and source.empty):
            return [FilterResult("K线形态", False, "无历史K线数据")]

        # 如果设置了时间范围，先对 source 做切片
        if self.start_date or self.end_date:
            if isinstance(source, pd.DataFrame):
                mask = pd.Series(True, index=source.index)
                if self.start_date:
                    # start_date 格式 YYYYMMDD → YYYY-MM-DD
                    sd = f"{self.start_date[:4]}-{self.start_date[4:6]}-{self.start_date[6:8]}"
                    mask &= (source["日期"] >= sd)
                if self.end_date:
                    ed = f"{self.end_date[:4]}-{self.end_date[4:6]}-{self.end_date[6:8]}"
                    mask &= (source["日期"] <= ed)
                source = source[mask].reset_index(drop=True)
            elif isinstance(source, list):
                sd = self.start_date
                ed = self.end_date
                source = [
                    k for k in source
                    if (not sd or k.date >= sd) and (not ed or k.date <= ed)
                ]

        max_offset = 0 if self.strict_recent else 60
        ok, desc = candle_pattern_match(
            source, self.pattern, fuzzy=self.fuzzy, max_offset=max_offset,
        )
        return [FilterResult("K线形态", ok, desc)]
