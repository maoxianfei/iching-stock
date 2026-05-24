"""
K线 → 爻 → 卦象 滑动窗口计算引擎 (iching_analyzer 专属)
6根K线为1个卦象，滑动窗口每次前进1根K线
生成 GuaResult/GuaAnalysis 分析模型，用于 HTML 报告渲染
"""

from dataclasses import dataclass, field

from core.models import KLine
from core.hexagram_db import Hexagram, get_hexagram, calc_bullish_ratio


@dataclass
class YaoLine:
    """单根爻线"""
    position: int     # 1-6, 1=初爻(底部)
    is_yang: bool     # True=阳爻, False=阴爻
    kline: KLine      # 对应的K线
    label: str = ""   # 爻名: 初爻/二爻/三爻/四爻/五爻/上爻

    def __post_init__(self):
        names = ["", "初爻", "二爻", "三爻", "四爻", "五爻", "上爻"]
        self.label = names[self.position]


@dataclass
class GuaResult:
    """一个卦象计算结果"""
    index: int              # 序号 (从1开始)
    start_date: str         # 窗口起始日期
    end_date: str           # 窗口结束日期
    hexagram: Hexagram      # 卦象对象
    yao_lines: list[YaoLine]  # 6根爻线

    @property
    def yao_bits(self) -> int:
        """爻位二进制值"""
        bits = 0
        for yao in self.yao_lines:
            if yao.is_yang:
                bits |= (1 << (yao.position - 1))
        return bits

    @property
    def yao_str(self) -> str:
        """爻序列字符串，从上爻到初爻 (阳=—, 阴=- -)"""
        parts = []
        for yao in sorted(self.yao_lines, key=lambda y: y.position, reverse=True):
            parts.append("———" if yao.is_yang else "— —")
        return "\n".join(parts)

    @property
    def period_labels(self) -> list[str]:
        """每根K线对应的周期标签（上爻→初爻，即最旧→最新）"""
        labels = []
        for yao in sorted(self.yao_lines, key=lambda y: y.position, reverse=True):
            date = yao.kline.date
            labels.append(date[:7])  # YYYY-MM
        return labels

    @property
    def periods_with_yao(self) -> list[dict]:
        """每根K线对应的周期 + 阴阳属性（上爻→初爻，供HTML渲染）"""
        result = []
        for yao in sorted(self.yao_lines, key=lambda y: y.position, reverse=True):
            result.append({
                "label": yao.kline.date[:7],
                "is_yang": yao.is_yang,
            })
        return result

    @property
    def date_range(self) -> str:
        """日期范围展示"""
        start = self.start_date[:7]  # YYYY-MM
        end = self.end_date[:7]
        return f"{start} → {end}"

    @property
    def date_range_full(self) -> str:
        """完整日期范围（周线用，精确到日）"""
        return f"{self.start_date} → {self.end_date}"


@dataclass
class GuaAnalysis:
    """完整卦象分析结果"""
    symbol: str                     # 股票代码
    stock_name: str                 # 股票名称
    interval: str                   # 周期 (weekly/monthly)
    interval_label: str             # 周期中文名
    total_klines: int               # K线总数
    total_guas: int                 # 卦象总数
    results: list[GuaResult]        # 所有卦象结果
    unique_hexagrams: list[Hexagram]  # 去重后的卦象列表
    bullish_ratio: float            # 看涨卦象比例
    trend_summary: str              # 趋势总结

    @property
    def start_date(self) -> str:
        return self.results[0].start_date if self.results else ""

    @property
    def end_date(self) -> str:
        return self.results[-1].end_date if self.results else ""


def analyze(klines: list[KLine]) -> list[GuaResult]:
    """
    滑动窗口卦象分析

    6根K线 → 1个卦象，窗口每步前进1根K线
    N根K线 → max(0, N-5) 个卦象

    Args:
        klines: 按日期升序排列的K线列表

    Returns:
        卦象结果列表
    """
    n = len(klines)
    if n < 6:
        raise ValueError(f"K线数量不足: 需要至少6根，实际{n}根")

    results = []
    for i in range(n - 5):  # 滑动窗口
        window = klines[i:i + 6]  # 6根连续K线

        # 构建6根爻线 (最旧K线→上爻, 最新K线→初爻)
        yao_lines = []
        for j, kline in enumerate(window):
            yao_lines.append(YaoLine(
                position=6 - j,     # 6=上爻(最旧), 1=初爻(最新)
                is_yang=kline.is_yang,
                kline=kline,
            ))

        # 计算爻位二进制
        yao_bits = 0
        for yao in yao_lines:
            if yao.is_yang:
                yao_bits |= (1 << (yao.position - 1))

        hexagram = get_hexagram(yao_bits)

        results.append(GuaResult(
            index=i + 1,
            start_date=window[0].date,
            end_date=window[-1].date,
            hexagram=hexagram,
            yao_lines=yao_lines,
        ))

    return results


def run_analysis(klines: list[KLine], symbol: str,
                 stock_name: str, interval: str) -> GuaAnalysis:
    """
    完整卦象分析流程

    Args:
        klines: K线数据
        symbol: 股票代码
        stock_name: 股票名称
        interval: 周期 ("weekly" / "monthly")

    Returns:
        GuaAnalysis 完整分析结果
    """
    interval_labels = {"daily": "日线", "weekly": "周线", "monthly": "月线"}
    interval_label = interval_labels.get(interval, interval)

    results = analyze(klines)

    # 去重卦象
    seen = set()
    unique_hexagrams = []
    for r in results:
        if r.hexagram.index not in seen:
            seen.add(r.hexagram.index)
            unique_hexagrams.append(r.hexagram)

    # 按看涨程度排序
    unique_hexagrams.sort(key=lambda h: -h.bullish_level)

    hex_list = [r.hexagram for r in results]
    bullish_ratio = calc_bullish_ratio(hex_list)

    # 趋势总结
    if bullish_ratio >= 0.6:
        trend_summary = "多头趋势：看涨卦象占比较高，整体偏向积极，适合顺势做多。"
    elif bullish_ratio >= 0.4:
        trend_summary = "震荡格局：多空力量相对均衡，市场处于方向选择阶段，适合观望或轻仓波段操作。"
    else:
        trend_summary = "空头趋势：看跌卦象占比较高，整体偏向谨慎，建议减仓或空仓等待。"

    return GuaAnalysis(
        symbol=symbol,
        stock_name=stock_name,
        interval=interval,
        interval_label=interval_label,
        total_klines=len(klines),
        total_guas=len(results),
        results=results,
        unique_hexagrams=unique_hexagrams,
        bullish_ratio=bullish_ratio,
        trend_summary=trend_summary,
    )
