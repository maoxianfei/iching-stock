"""
K线 → 卦象 核心映射引擎
==========================
将任意时间周期的K线序列通过6根滑动窗口映射为易经六十四卦。
支持指定目标卦象的命中检测和连续卦象序列检测。

核心规则:
  - close >= open → 阳爻(1), 否则 → 阴爻(0)
  - 最旧K线 = 上爻(第6爻), 最新K线 = 初爻(第1爻)
  - 6根K线 = 1个卦象, N根K线 → N-5个卦象

本模块为共享核心算法，可被所有子系统调用。
"""

from dataclasses import dataclass, field
from typing import Optional

from core.models import KLine
from core.hexagram_db import (
    Hexagram, get_hexagram, get_hexagram_info,
    TRIGRAM_NAMES, TRIGRAM_ELEMENTS,
)


# ============================================================
# 数据类
# ============================================================

@dataclass
class HexagramResult:
    """单个卦象结果"""
    window_index: int          # 窗口序号 (从1开始)
    start_date: str            # 窗口最旧K线日期
    end_date: str              # 窗口最新K线日期
    yao_bits: int              # 0~63, 爻位编码 (bit0=初爻)
    hexagram_name: str         # 卦名 (如 "火地晋")
    upper_trigram: str         # 上卦名
    lower_trigram: str         # 下卦名
    yao_sequence: list[bool]   # [上爻, 五爻, 四爻, 三爻, 二爻, 初爻], True=阳
    is_target: bool = False    # 是否命中目标卦象


@dataclass
class SequenceMatch:
    """连续卦象序列命中结果"""
    start_index: int          # 序列起始窗口序号 (从1开始)
    start_date: str           # 序列第一卦的起始日期
    end_date: str             # 序列最后一卦的结束日期
    pattern: list[int]        # 期望的 yao_bits 序列
    actual: list[int]         # 实际的 yao_bits 序列
    hexagram_names: list[str] # 对应的卦名序列
    yao_sequences: list[str]  # 对应的爻序列


# ============================================================
# 工具函数
# ============================================================

def yao_bits_to_sequence(yao_bits: int) -> list[bool]:
    """
    将 yao_bits 转为 [上爻, 五爻, 四爻, 三爻, 二爻, 初爻] 的阴阳序列
    """
    seq = []
    for pos in range(6, 0, -1):  # 从位6(上爻)到位1(初爻)
        seq.append(bool(yao_bits & (1 << (pos - 1))))
    return seq


def format_yao_sequence(seq: list[bool]) -> str:
    """格式化爻序列为可读字符串, 如 '阳阴阳阴阴阳'"""
    return "".join("阳" if s else "阴" for s in seq)


# ============================================================
# 核心映射: K线 → 卦象
# ============================================================

def klines_to_hexagrams(
    klines: list[KLine],
    target_yao_bits: Optional[list[int]] = None,
) -> list[HexagramResult]:
    """
    N 根 K 线 → N-5 个卦象结果

    Args:
        klines: 按时间升序排列的K线列表 (至少6根)
        target_yao_bits: 目标卦象的 yao_bits 列表, 用于命中标记

    Returns:
        卦象结果列表, 每项包含窗口信息、卦名、爻序列等
    """
    if len(klines) < 6:
        raise ValueError(f"至少需要 6 根 K 线，当前: {len(klines)}")

    if target_yao_bits is None:
        target_yao_bits = []

    target_set = set(target_yao_bits)
    results = []

    for i in range(len(klines) - 5):
        window = klines[i : i + 6]   # 升序: [0]=最旧, [5]=最新

        yao_bits = 0
        yao_seq = []                  # 从上爻到初爻
        for j, kline in enumerate(window):
            position = 6 - j          # j=0→6(上爻), j=5→1(初爻)
            if kline.is_yang:
                yao_bits |= (1 << (position - 1))
            yao_seq.append(kline.is_yang)

        name, upper, lower = get_hexagram_info(yao_bits)

        results.append(HexagramResult(
            window_index=i + 1,
            start_date=window[0].date,
            end_date=window[-1].date,
            yao_bits=yao_bits,
            hexagram_name=name,
            upper_trigram=upper,
            lower_trigram=lower,
            yao_sequence=yao_seq,
            is_target=yao_bits in target_set,
        ))

    return results


# ============================================================
# 序列检测: 连续卦象模式匹配
# ============================================================

def detect_hexagram_sequences(
    klines: list[KLine],
    patterns: list[list[int]],
) -> list[SequenceMatch]:
    """
    在K线滑动窗口卦象中检测连续卦象序列。

    例如: patterns=[[40, 17]] 表示检测 火地晋(40) → 水雷屯(17) 紧挨出现。
    当窗口[i]的卦象=40 且 窗口[i+1]的卦象=17 时命中。

    Args:
        klines: 按时间升序排列的K线列表
        patterns: 多个序列模式, 每个模式是一个 yao_bits 列表

    Returns:
        所有命中的 SequenceMatch 列表
    """
    if len(klines) < 7:
        raise ValueError(f"序列检测至少需要 7 根K线 (6根→卦象1 + 滑动1根→卦象2)，当前: {len(klines)}")

    results = klines_to_hexagrams(klines)
    num_windows = len(results)  # N-5 个窗口

    matches = []

    for pattern in patterns:
        pattern_len = len(pattern)
        if pattern_len < 2:
            continue

        for i in range(num_windows - pattern_len + 1):
            match = True
            for offset in range(pattern_len):
                if results[i + offset].yao_bits != pattern[offset]:
                    match = False
                    break

            if match:
                matches.append(SequenceMatch(
                    start_index=results[i].window_index,
                    start_date=results[i].start_date,
                    end_date=results[i + pattern_len - 1].end_date,
                    pattern=pattern,
                    actual=[results[i + off].yao_bits for off in range(pattern_len)],
                    hexagram_names=[results[i + off].hexagram_name for off in range(pattern_len)],
                    yao_sequences=[format_yao_sequence(results[i + off].yao_sequence)
                                   for off in range(pattern_len)],
                ))

    return matches


# ============================================================
# 便捷查找
# ============================================================

def find_matches(
    klines: list[KLine],
    target_yao_bits: list[int],
    period_name: str = "日线",
) -> dict:
    """
    在K线序列中查找匹配目标卦象的窗口

    Args:
        klines: K线列表
        target_yao_bits: 目标卦象 yao_bits 列表
        period_name: 周期名称 (如 "日线", "周线", "月线")

    Returns:
        {
            "period": str,
            "total_klines": int,
            "total_hexagrams": int,
            "targets": [{"name": str, "yao_bits": int}, ...],
            "matches": [HexagramResult, ...],
            "latest": HexagramResult,
            "latest_matches": bool,
            "all_results": [HexagramResult, ...],
        }
    """
    results = klines_to_hexagrams(klines, target_yao_bits)

    matches = [r for r in results if r.is_target]
    latest = results[-1] if results else None

    target_info = []
    for bits in target_yao_bits:
        name, _, _ = get_hexagram_info(bits)
        target_info.append({"name": name, "yao_bits": bits})

    return {
        "period": period_name,
        "total_klines": len(klines),
        "total_hexagrams": len(results),
        "targets": target_info,
        "matches": matches,
        "latest": latest,
        "latest_matches": latest.is_target if latest else False,
        "all_results": results,
    }
