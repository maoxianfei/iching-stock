"""
策略基类 + 数据结构

所有回测策略继承 BaseStrategy，
实现 pre_filter / analyze / should_pass 接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ══════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════

@dataclass
class FilterResult:
    """单条过滤条件的结果"""
    name: str           # 条件名称，如 "MA10偏离度"
    passed: bool        # 是否通过
    detail: str = ""    # 失败原因描述


@dataclass
class ScreenResult:
    """单只股票筛选结果"""
    code: str
    name: str
    price: float = 0.0
    pct_change: float = 0.0
    passed: bool = False
    filter_results: List[FilterResult] = field(default_factory=list)
    signal_desc: str = ""


# ══════════════════════════════════════════
# 策略基类
# ══════════════════════════════════════════

class BaseStrategy(ABC):
    """
    策略接口（两阶段筛选）

    生命周期：
        engine 创建策略实例
        → 对每只股票调用 pre_filter（粗筛，基于快照，快）
        → 对粗筛通过的股票并发调用 analyze（精筛，基于K线，慢）
        → 调用 should_pass 聚合判定
    """

    def __init__(self, name: str):
        self.name = name

    # ── 粗筛：基于实时快照快速过滤 ─────────

    @abstractmethod
    def pre_filter(self, snapshot: Dict[str, Any]) -> bool:
        """
        粗筛条件。snapshot 是实时行情快照字典，字段包括：
          code, name, price, pct_change,
          volume, amount, turnover, high, low, open, pre_close
        返回 True = 通过粗筛，进入精筛。
        """
        ...

    # ── 精筛：基于历史K线详细判断 ─────────

    @abstractmethod
    def analyze(
        self,
        snapshot: Dict[str, Any],
        history_df: Any = None,           # pd.DataFrame（来自 akshare）
        history_klines: Optional[list] = None,  # List[KLine]（来自 core/data_fetcher）
    ) -> List[FilterResult]:
        """
        精筛条件。返回每条条件的 FilterResult 列表。
        支持两种历史数据输入（至少支持一种）：
          - history_df:     pandas DataFrame
          - history_klines: List[KLine]
        """
        ...

    # ── 聚合判定 ─────────

    def should_pass(self, results: List[FilterResult]) -> bool:
        """默认 AND 逻辑：所有条件通过才判定为 True"""
        return all(r.passed for r in results)

    # ── 元数据 ─────────

    @property
    @abstractmethod
    def min_history_days(self) -> int:
        """最少需要多少条历史K线"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """策略描述文本（用于 CLI 和帮助信息）"""
        ...
