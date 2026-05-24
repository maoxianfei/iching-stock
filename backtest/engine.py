"""
回测系统 — 筛选引擎

流程：
  1. 获取全A股股票列表（通过 akshare 或 mootdx）
  2. 粗筛：遍历所有股票，调用 strategy.pre_filter()
  3. 精筛：对候选股并发拉取历史K线，调用 strategy.analyze()
  4. 汇总策略判定结果

数据来源：
  - 股票列表：akshare stock_info_a_code_name（通用，无需 token）
  - K线数据：core/data_fetcher.py fetch_klines（mootdx TCP）
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import pandas as pd
from tqdm import tqdm

from backtest.strategy_base import BaseStrategy, ScreenResult
from core.config import MAX_WORKERS

# ═══════════════════════════════════════════
# 股票列表获取
# ═══════════════════════════════════════════

def _get_stock_list() -> pd.DataFrame:
    """
    获取全A股股票列表。
    优先使用 akshare（无需 token，覆盖全市场），
    若不可用则尝试 mootdx 或通过 core/models 的腾讯接口补充。
    """
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        return df
    except Exception as e:
        print(f"  [警告] akshare 获取股票列表失败: {e}")
        print("  [提示] 请安装 akshare: pip install akshare")
        # 回退：返回空 DataFrame，由调用方处理
        return pd.DataFrame()


def _get_realtime_quotes() -> Optional[pd.DataFrame]:
    """
    尝试获取实时行情快照（东方财富 push2 API）。
    成功则返回 DataFrame，失败返回 None（触发降级模式）。
    """
    try:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        })
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "5000",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",  # 全A股
            "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124,f1,f13",
        }
        all_rows = []
        page = 1
        while True:
            params["pn"] = str(page)
            r = session.get(url, params=params, timeout=30)
            data = r.json().get("data", {})
            diff = data.get("diff", [])
            if not diff:
                break
            for item in diff:
                all_rows.append({
                    "code": str(item.get("f12", "")).zfill(6),
                    "name": item.get("f14", ""),
                    "price": float(item.get("f2", 0) or 0),
                    "pct_change": float(item.get("f3", 0) or 0),
                })
            if len(all_rows) >= data.get("total", 0):
                break
            page += 1
        return pd.DataFrame(all_rows) if all_rows else None
    except Exception as e:
        print(f"  [提示] 实时行情不可用: {e}")
        return None


# ═══════════════════════════════════════════
# 快照构建
# ═══════════════════════════════════════════

def _row_to_snapshot(row: pd.Series) -> Dict[str, Any]:
    """将 DataFrame 行转为统一的 dict 快照"""
    return {
        "code":       str(row.get("code", row.get("代码", ""))).zfill(6),
        "name":       str(row.get("name", row.get("名称", ""))),
        "price":      float(row.get("price", row.get("最新价", 0) or 0)),
        "pct_change": float(row.get("pct_change", row.get("涨跌幅", 0) or 0)),
        "volume":     float(row.get("volume", row.get("成交量", 0) or 0)),
        "amount":     float(row.get("amount", row.get("成交额", 0) or 0)),
    }


def _make_fallback_snapshot(code: str, name: str) -> Dict[str, Any]:
    """降级模式：构建最小快照（仅代码+名称，价格字段填 0）"""
    return {
        "code": str(code).zfill(6),
        "name": str(name),
        "price": 0.0,
        "pct_change": 0.0,
        "volume": 0.0,
        "amount": 0.0,
    }


# ═══════════════════════════════════════════
# 单股评估
# ═══════════════════════════════════════════

def _evaluate_one(strategy: BaseStrategy, snapshot: Dict[str, Any]) -> Optional[ScreenResult]:
    """
    对单只候选股进行精筛评估。
    返回 ScreenResult，失败/异常时返回 None。
    """
    code = snapshot["code"]
    name = snapshot.get("name", "")

    # 获取K线（优先用 core/data_fetcher）
    try:
        from core.data_fetcher import fetch_klines
        klines = fetch_klines(code, interval="daily", count=120)
    except Exception as e:
        # 回退：尝试 akshare
        try:
            import akshare as ak
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily", adjust="qfq",
                start_date="20240101", end_date="20260101",
            )
            if df is not None and not df.empty:
                from core.indicators import klines_to_dataframe
                history_df = df
                klines = None
            else:
                return None
        except Exception:
            return None

    if "klines" in dir() and klines:
        # 转换为 DataFrame 供策略使用
        from core.indicators import klines_to_dataframe
        history_df = klines_to_dataframe(klines)
        history_klines = klines
    elif "history_df" in dir() and history_df is not None:
        history_klines = None
    else:
        return None

    if history_df is None or history_df.empty or len(history_df) < strategy.min_history_days:
        return None

    # 调用策略精筛
    try:
        filter_results = strategy.analyze(
            snapshot, history_df=history_df,
            history_klines=history_klines if "history_klines" in dir() else None,
        )
    except Exception:
        # 尝试只传 history_df
        try:
            filter_results = strategy.analyze(snapshot, history=history_df)
        except Exception:
            return None

    passed = strategy.should_pass(filter_results)

    # 提取信号描述
    signal_desc = ""
    for fr in filter_results:
        if "信号" in fr.name and fr.detail:
            signal_desc = fr.detail
            break

    # 价格：若快照价格为 0（降级模式），从 history 补充
    price = snapshot.get("price", 0)
    pct_change = snapshot.get("pct_change", 0)
    if price == 0 and history_df is not None and not history_df.empty:
        close_col = "收盘" if "收盘" in history_df.columns else "close"
        try:
            price = float(history_df.iloc[-1][close_col])
        except Exception:
            pass

    return ScreenResult(
        code=code,
        name=name,
        price=price,
        pct_change=pct_change,
        passed=passed,
        filter_results=filter_results,
        signal_desc=signal_desc,
    )


# ═══════════════════════════════════════════
# 主编排
# ═══════════════════════════════════════════

def run_screen(strategy: BaseStrategy) -> List[ScreenResult]:
    """
    通用筛选引擎：接受任意 BaseStrategy 实例，执行两阶段筛选。

    实时行情获取失败时自动降级：使用静态股票列表 + 跳过粗筛。
    """
    print("=" * 60)
    print(f"iching-stock 回测系统 — 策略: {strategy.name}")
    print(f"  描述: {strategy.description}")
    print("=" * 60)

    # ── 1. 获取股票列表 ─────────

    print("\n[1/3] 获取全A股股票列表 ...")
    t0 = time.time()

    fallback_mode = False
    quotes = _get_realtime_quotes()

    if quotes is not None and not quotes.empty:
        print(f"  获取 {len(quotes)} 只股票实时行情 ({time.time() - t0:.0f}s)")
    else:
        print(f"  [降级] 实时行情不可用，使用静态股票列表...")
        try:
            stock_df = _get_stock_list()
            if stock_df.empty:
                print("  [错误] 股票列表也无法获取")
                return []
            quotes = stock_df
            fallback_mode = True
            print(f"  获取 {len(quotes)} 只股票（静态列表） ({time.time() - t0:.0f}s)")
        except Exception as e:
            print(f"  [错误] 股票列表获取失败: {e}")
            return []

    # ── 2. 粗筛 ─────────

    if not fallback_mode:
        print(f"\n[2/3] 粗筛（{strategy.name}）...")
        candidates = []
        for _, row in quotes.iterrows():
            snap = _row_to_snapshot(row)
            try:
                if strategy.pre_filter(snap):
                    candidates.append(snap)
            except Exception:
                continue
        print(f"  粗筛后候选: {len(candidates)} 只")
    else:
        # 降级模式：构建最小快照，仍然执行 pre_filter
        print(f"\n[2/3] 降级模式粗筛...")
        candidates = []
        for _, row in quotes.iterrows():
            code = str(row.get("code", row.get("代码", ""))).zfill(6)
            name = str(row.get("name", row.get("名称", "")))
            if not code:
                continue
            snap = _make_fallback_snapshot(code, name)
            try:
                if strategy.pre_filter(snap):
                    candidates.append(snap)
            except Exception:
                continue
        print(f"  粗筛后候选: {len(candidates)} 只")

    if not candidates:
        print("  无候选股，结束。")
        return []

    # ── 3. 精筛 ─────────

    stage_label = "3/3" if not fallback_mode else "3/3"
    print(f"\n[{stage_label}] 精筛（{MAX_WORKERS} 线程并发）...")

    results: List[ScreenResult] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_evaluate_one, strategy, snap): snap
            for snap in candidates
        }
        with tqdm(total=len(candidates), desc="  筛选进度", unit="只") as pbar:
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result and result.passed:
                        results.append(result)
                except Exception:
                    pass
                pbar.update(1)

    # 按涨跌幅排序（从低到高）
    results.sort(key=lambda r: r.pct_change)

    t1 = time.time()
    print(f"\n  完成！总耗时 {t1 - t0:.0f}s，通过 {len(results)} 只")

    return results
