"""
定时调度 — 交易日检测 + 指定时间触发

用法：
  from backtest.scheduler import run_scheduled
  run_scheduled(strategy_name="ma_convergence")
"""

import time as _time
from datetime import datetime, timedelta

from backtest.strategies import get_strategy
from backtest.engine import run_screen
from backtest.output import print_table, to_excel
from core.config import SCHEDULE_HOUR, SCHEDULE_MINUTE


# ═════════════════════════════════════════
# 交易日判断
# ═════════════════════════════════════════

def is_trade_day() -> bool:
    """
    判断今天是否为 A股交易日。
    优先使用 akshare 交易日历，失败则退回"周一~周五"近似判断。
    """
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        today_str = datetime.now().strftime("%Y-%m-%d")
        return today_str in set(df["trade_date"].astype(str).values)
    except Exception:
        # 退回：周一(0)~周五(4)
        return datetime.now().weekday() < 5


def _wait_until_target(hour: int, minute: int) -> None:
    """阻塞等到今天 target_time，每秒检查一次。"""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if target <= now:
        return  # 已过今日目标时间

    while True:
        now = datetime.now()
        if now.hour == hour and now.minute >= minute:
            break
        remain = int((target - now).total_seconds())
        if remain <= 0:
            break
        _time.sleep(min(60, remain))


# ═════════════════════════════════════════
# 主循环
# ═════════════════════════════════════════

def run_scheduled(strategy_name: str = "ma_convergence") -> None:
    """
    定时模式主循环：
      - 每个交易日等待到 SCHEDULE_HOUR:SCHEDULE_MINUTE 触发筛选
      - 非交易日 sleep 1小时再检查
      - 同一天只执行一次
    """
    print(f"  定时模式启动：每个交易日 {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} 触发")
    print(f"  策略：{strategy_name}")
    print("  按 Ctrl+C 退出\n")

    last_run_date = None

    try:
        while True:
            today = datetime.now().date().isoformat()

            if not is_trade_day():
                print(f"  {today} 非交易日，等待中...")
                _time.sleep(3600)
                continue

            if last_run_date == today:
                # 今天已执行过，sleep 到明天再检查
                _time.sleep(3600)
                continue

            # 等待到触发时间
            _wait_until_target(SCHEDULE_HOUR, SCHEDULE_MINUTE)

            # 再次确认今天仍是交易日（防止跨日）
            if not is_trade_day():
                continue

            print(f"\n  [{datetime.now():%H:%M:%S}] 开始筛选 ...")

            strategy = get_strategy(strategy_name)
            results = run_screen(strategy)

            if results:
                print_table(results)
                to_excel(results)

            last_run_date = today
            print(f"  完成。等待下一个交易日...\n")

    except KeyboardInterrupt:
        print("\n\n  已停止定时任务。")
