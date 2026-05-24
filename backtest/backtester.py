"""
回测核心 — 通用回测引擎

基于指定策略，在历史数据上回放：
  1. 在筛选日（screen_date）对全市场执行策略筛选
  2. 在验证日（verify_date）计算持有收益
  3. 统计胜率、平均收益、最大盈亏等

用法：
  from backtest.backtester import run_backtest
  result = run_backtest(strategy, screen_date="2026-05-14", verify_date="2026-05-15")
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.engine import _get_stock_list
from backtest.strategy_base import BaseStrategy, ScreenResult
from core.data_fetcher import fetch_klines


# ═════════════════════════════════════════
# 工具函数
# ═════════════════════════════════════════

def _date_str_to_obj(date_str: str) -> datetime:
    """支持 YYYY-MM-DD 或 YYYYMMDD 格式"""
    s = date_str.strip()
    if "-" in s and len(s) == 10:
        return datetime.strptime(s, "%Y-%m-%d")
    elif len(s) == 8 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d")
    else:
        raise ValueError(f"无法解析日期: {s}")


def _next_trade_day(date_obj: datetime, direction: int = 1) -> datetime:
    """
    简单交易日推算（跳过周末，不处理节假日）。
    direction=1: 向后找；direction=-1: 向前找。
    """
    d = date_obj
    while True:
        d = d + timedelta(days=direction)
        if d.weekday() < 5:  # 0-4 = 周一至周五
            return d


def _fetch_history_for_backtest(
    code: str,
    screen_date: str,
    days_before: int = 120,
) -> Optional[pd.DataFrame]:
    """
    获取某只股票在筛选日之前的足够历史K线，
    转换为 DataFrame 供策略 analyze() 使用。

    Returns: DataFrame（按日期升序），或 None。
    """
    try:
        klines = fetch_klines(code, interval="daily", count=days_before)
    except Exception:
        return None

    if not klines:
        return None

    # 过滤掉筛选日之后的数据
    screen_dt = _date_str_to_obj(screen_date)
    screen_str = screen_dt.strftime("%Y-%m-%d")

    filtered = [k for k in klines if k.date <= screen_str]
    if not filtered:
        return None

    # 转换为 DataFrame
    from core.indicators import klines_to_dataframe
    df = klines_to_dataframe(filtered)
    return df if not df.empty else None


def _get_price_for_date(code: str, target_date: str) -> Optional[float]:
    """
    获取某只股票在指定日期的收盘价。
    通过 fetch_klines 拉取数据后找到最近交易日。
    """
    try:
        klines = fetch_klines(code, interval="daily", count=250)
    except Exception:
        return None

    target_dt = _date_str_to_obj(target_date)
    target_str = target_dt.strftime("%Y-%m-%d")

    # 找目标日期或之前最近交易日
    for k in reversed(klines):
        if k.date <= target_str:
            return k.close

    return None


# ═════════════════════════════════════════
# 回测引擎
# ═════════════════════════════════════════

def run_backtest(
    strategy: BaseStrategy,
    screen_date: str,
    verify_date: Optional[str] = None,
    sample_size: Optional[int] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    执行一次回测。

    Args:
        strategy: 策略实例（BaseStrategy 子类）
        screen_date: 筛选日（YYYY-MM-DD 或 YYYYMMDD）
        verify_date: 验证日（默认 = 筛选日+1个交易日）
        sample_size: 只抽样前 N 只股票（快速测试用）
        verbose: 是否打印详细过程

    Returns:
        dict: {
            "screen_date": str,
            "verify_date": str,
            "total_screened": int,     # 筛选日实际筛选数量
            "passed": int,              # 通过筛选数量
            "verify_count": int,         # 能获取到验证日价格的数量
            "winners": int,             # 上涨数量
            "losers": int,              # 下跌数量
            "win_rate": float,           # 胜率
            "avg_return": float,         # 平均收益率
            "max_gain": float,          # 最大收益
            "max_loss": float,           # 最大亏损
            "details": List[dict],      # 每只通过股票的明细
        }
    """
    screen_dt = _date_str_to_obj(screen_date)
    screen_date_str = screen_dt.strftime("%Y-%m-%d")

    if verify_date:
        verify_dt = _date_str_to_obj(verify_date)
    else:
        verify_dt = _next_trade_day(screen_dt, direction=1)
    verify_date_str = verify_dt.strftime("%Y-%m-%d")

    if verbose:
        print("=" * 60)
        print(f"  回测：筛选日 {screen_date_str} → 验证日 {verify_date_str}")
        print(f"  策略：{strategy.name}")
        print(f"  描述：{strategy.description}")
        print("=" * 60)

    t0 = time.time()

    # ═══ 1. 获取股票列表 ═══

    if verbose:
        print(f"\n[1/3] 获取股票列表 ...")

    stock_df = _get_stock_list()
    if stock_df.empty:
        if verbose:
            print("  [错误] 无法获取股票列表")
        return _empty_result(screen_date_str, verify_date_str)

    codes = []
    for _, row in stock_df.iterrows():
        code = str(row.get("code", row.get("代码", ""))).zfill(6)
        if code:
            codes.append(code)

    if sample_size:
        codes = codes[:sample_size]
        if verbose:
            print(f"  （抽样模式：前 {len(codes)} 只）")

    if verbose:
        print(f"  共 {len(codes)} 只股票")

    # ═══ 2. 在筛选日执行策略筛选 ═══

    if verbose:
        print(f"\n[2/3] 在 {screen_date_str} 执行策略筛选 ...")

    passed = []
    screened_count = 0

    for i, code in enumerate(codes):
        screened_count += 1

        # 获取筛选日之前的K线
        history_df = _fetch_history_for_backtest(
            code, screen_date_str, days_before=120,
        )
        if history_df is None or history_df.empty:
            continue

        if len(history_df) < strategy.min_history_days:
            continue

        # 构建快照（用最新一条K线模拟当日行情）
        last_row = history_df.iloc[-1]
        snapshot = {
            "code": code,
            "name": "",   # 名称暂时为空，不影响筛选
            "price": float(last_row.get("收盘", last_row.get("close", 0))),
            "pct_change": float(last_row.get("涨跌幅", 0) if "涨跌幅" in history_df.columns else 0),
        }

        # pre_filter
        try:
            if not strategy.pre_filter(snapshot):
                continue
        except Exception:
            continue

        # analyze
        try:
            filter_results = strategy.analyze(snapshot, history_df)
            passed_flag = strategy.should_pass(filter_results)
        except Exception:
            continue

        if passed_flag:
            passed.append({
                "code": code,
                "name": snapshot["name"],
                "price_at_screen": snapshot["price"],
                "filter_results": filter_results,
            })

        if verbose and (i + 1) % 500 == 0:
            print(f"  已处理 {i + 1}/{len(codes)} ... 通过 {len(passed)} 只")

    if verbose:
        print(f"  筛选完成：共 {screened_count} 只，通过 {len(passed)} 只")

    if not passed:
        if verbose:
            print("\n  （无股票通过筛选，回测结束）")
        return _empty_result(screen_date_str, verify_date_str, screened_count)

    # ═══ 3. 在验证日计算收益 ═══

    if verbose:
        print(f"\n[3/3] 在 {verify_date_str} 计算收益 ...")

    winners = 0
    losers = 0
    returns = []
    details = []

    for i, item in enumerate(passed):
        code = item["code"]
        price_screen = item["price_at_screen"]

        price_verify = _get_price_for_date(code, verify_date_str)
        if price_verify is None:
            continue

        ret = (price_verify - price_screen) / price_screen * 100
        returns.append(ret)

        detail = {
            "code": code,
            "name": item["name"],
            "price_screen": price_screen,
            "price_verify": price_verify,
            "return_pct": round(ret, 2),
        }
        details.append(detail)

        if ret > 0:
            winners += 1
        else:
            losers += 1

        if verbose and (i + 1) % 100 == 0:
            print(f"  已验证 {i + 1}/{len(passed)} ... 当前胜率 {winners/max(winners+losers,1)*100:.1f}%")

    t1 = time.time()

    # ═══ 汇总结果 ═══

    win_rate = winners / max(len(returns), 1) * 100
    avg_ret = sum(returns) / max(len(returns), 1)
    max_gain = max(returns) if returns else 0.0
    max_loss = min(returns) if returns else 0.0

    result = {
        "screen_date": screen_date_str,
        "verify_date": verify_date_str,
        "total_screened": screened_count,
        "passed": len(passed),
        "verify_count": len(returns),
        "winners": winners,
        "losers": losers,
        "win_rate": round(win_rate, 2),
        "avg_return": round(avg_ret, 4),
        "max_gain": round(max_gain, 4),
        "max_loss": round(max_loss, 4),
        "details": details,
    }

    if verbose:
        print(f"\n  {'=' * 40}")
        print(f"  回测结果汇总")
        print(f"  {'=' * 40}")
        print(f"  筛选日：{screen_date_str}  验证日：{verify_date_str}")
        print(f"  筛选数量：{screened_count}  通过：{len(passed)}")
        print(f"  可验证：{len(returns)}")
        print(f"  上涨：{winners}  下跌：{losers}")
        print(f"  胜率：{win_rate:.1f}%")
        print(f"  平均收益：{avg_ret:.2f}%")
        print(f"  最大盈利：{max_gain:.2f}%  最大亏损：{max_loss:.2f}%")
        print(f"  耗时：{t1 - t0:.0f}s")
        print()

        # 打印前20只明细
        print(f"  {'代码':<8} {'买入价':<10} {'验证日价':<10} {'收益':<10}")
        print(f"  {'-' * 40}")
        for d in details[:20]:
            sign = "+" if d["return_pct"] >= 0 else ""
            print(
                f"  {d['code']:<8} {d['price_screen']:<10.2f} "
                f"{d['price_verify']:<10.2f} {sign}{d['return_pct']:.2f}%"
            )
        if len(details) > 20:
            print(f"  ... 还有 {len(details) - 20} 只未显示")

    return result


def _empty_result(screen_date: str, verify_date: str, screened: int = 0) -> dict:
    return {
        "screen_date": screen_date,
        "verify_date": verify_date,
        "total_screened": screened,
        "passed": 0,
        "verify_count": 0,
        "winners": 0,
        "losers": 0,
        "win_rate": 0.0,
        "avg_return": 0.0,
        "max_gain": 0.0,
        "max_loss": 0.0,
        "details": [],
    }


# ═════════════════════════════════════════
# 批量回测（多日期）
# ═════════════════════════════════════════

def run_batch_backtest(
    strategy: BaseStrategy,
    start_date: str,
    end_date: str,
    offset_days: int = 1,    # 验证日距筛选日天数
    sample_size: Optional[int] = None,
    verbose: bool = True,
) -> List[Dict[str, Any]]:
    """
    批量回测：在 [start_date, end_date] 范围内，
    每隔 offset_days 个交易日执行一次回测。

    Returns:
        List[dict]，每个元素是一次回测的结果
    """
    start_dt = _date_str_to_obj(start_date)
    end_dt = _date_str_to_obj(end_date)

    # 生成筛选日列表（简单跳过周末）
    screen_dates = []
    d = start_dt
    while d <= end_dt:
        if d.weekday() < 5:
            screen_dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    if verbose:
        print(f"\n  批量回测：{len(screen_dates)} 个筛选日")
        print(f"  验证日偏移：+{offset_days} 个交易日\n")

    results = []
    for i, sd in enumerate(screen_dates):
        sd_dt = _date_str_to_obj(sd)
        verify_dt = sd_dt
        for _ in range(offset_days):
            verify_dt = _next_trade_day(verify_dt, direction=1)
        verify_str = verify_dt.strftime("%Y-%m-%d")

        r = run_backtest(
            strategy=strategy,
            screen_date=sd,
            verify_date=verify_str,
            sample_size=sample_size,
            verbose=verbose,
        )
        results.append(r)

        if verbose and i < len(screen_dates) - 1:
            print()

    # 汇总
    if verbose and len(results) > 1:
        print(f"\n{'=' * 50}")
        print(f"  批量回测汇总（{len(results)} 次）")
        print(f"{'=' * 50}")
        total_win = sum(r["winners"] for r in results)
        total_verify = sum(r["verify_count"] for r in results)
        avg_win_rate = total_win / max(total_verify, 1) * 100
        avg_ret = sum(r["avg_return"] for r in results) / max(len(results), 1)
        print(f"  总筛选次数：{len(results)}")
        print(f"  总验证样本：{total_verify}")
        print(f"  平均胜率：{avg_win_rate:.1f}%")
        print(f"  平均收益：{avg_ret:.2f}%")

    return results
