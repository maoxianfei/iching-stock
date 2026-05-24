"""
回测系统 CLI 入口

用法：
  python backtest/runner.py screen --strategy ma_convergence
  python backtest/runner.py backtest --strategy yijing --screen-date 20260514 --verify-date 20260515
  python backtest/runner.py batch --strategy ma_convergence --start 20260501 --end 20260531
  python backtest/runner.py strategy-list
"""

import argparse
import sys
import os

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def cmd_screen(args) -> None:
    """执行实时筛选"""
    from backtest.strategies import get_strategy
    import backtest.output as output

    strategy = get_strategy(args.strategy, **_strategy_kwargs(args))
    from backtest.engine import run_screen
    results = run_screen(strategy)

    if results:
        output.print_table(results, limit=args.limit)
        if args.export:
            path = output.to_excel(results)
            print(f"  文件已保存: {path}")
    else:
        print("\n  （无股票通过筛选）")


def cmd_backtest(args) -> None:
    """执行单次回测"""
    from backtest.strategies import get_strategy
    from backtest.backtester import run_backtest

    strategy = get_strategy(args.strategy, **_strategy_kwargs(args))

    screen_date = _normalize_date(args.screen_date)
    verify_date = _normalize_date(args.verify_date) if args.verify_date else None

    result = run_backtest(
        strategy=strategy,
        screen_date=screen_date,
        verify_date=verify_date,
        sample_size=args.sample,
        verbose=True,
    )


def cmd_batch(args) -> None:
    """执行批量回测"""
    from backtest.strategies import get_strategy
    from backtest.backtester import run_batch_backtest

    strategy = get_strategy(args.strategy, **_strategy_kwargs(args))

    result = run_batch_backtest(
        strategy=strategy,
        start_date=_normalize_date(args.start),
        end_date=_normalize_date(args.end),
        offset_days=args.offset,
        sample_size=args.sample,
        verbose=True,
    )


def cmd_strategy_list(args) -> None:
    """列出所有可用策略"""
    from backtest.strategies import list_strategies

    print("\n  可用策略：")
    print("  " + "-" * 40)
    strategies = list_strategies()
    for name, desc in strategies.items():
        print(f"  {name}")
        print(f"    {desc}")
    print()


def _strategy_kwargs(args) -> dict:
    """从 CLI args 中提取策略构造参数"""
    kwargs = {}
    if hasattr(args, "pattern") and args.pattern:
        kwargs["pattern"] = args.pattern
    if hasattr(args, "fuzzy") and args.fuzzy:
        kwargs["fuzzy"] = True
    if hasattr(args, "no_strict") and args.no_strict:
        kwargs["strict_recent"] = False
    return kwargs


def _normalize_date(s: str) -> str:
    """支持 YYYY-MM-DD 或 YYYYMMDD"""
    s = s.strip()
    if "-" in s and len(s) == 10:
        return s
    elif len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    else:
        raise ValueError(f"无法解析日期: {s}")


# ═════════════════════════════════════
# CLI 参数解析
# ═════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="iching-stock 回测系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # ── screen 命令 ─────────

    p_screen = subparsers.add_parser("screen", help="执行实时筛选")
    p_screen.add_argument("--strategy", default="ma_convergence",
                          choices=["ma_convergence", "yijing"],
                          help="策略名称")
    p_screen.add_argument("--pattern", default="阳阴阳阴阴阴阳",
                          help="易经策略K线形态（默认：阳阴阳阴阴阴阳）")
    p_screen.add_argument("--fuzzy", action="store_true",
                          help="易经策略模糊匹配")
    p_screen.add_argument("--no-strict", action="store_true",
                          help="易经策略关闭严格模式（回溯60天）")
    p_screen.add_argument("--limit", type=int, default=30,
                          help="控制台显示前N条（默认30）")
    p_screen.add_argument("--export", action="store_true",
                          help="导出Excel")
    p_screen.set_defaults(func=cmd_screen)

    # ── backtest 命令 ─────────

    p_bt = subparsers.add_parser("backtest", help="执行单次回测")
    p_bt.add_argument("--strategy", default="ma_convergence",
                      choices=["ma_convergence", "yijing"])
    p_bt.add_argument("--screen-date", required=True,
                       help="筛选日（YYYY-MM-DD 或 YYYYMMDD）")
    p_bt.add_argument("--verify-date", default=None,
                       help="验证日（默认=筛选日+1个交易日）")
    p_bt.add_argument("--pattern", default="阳阴阳阴阴阴阳")
    p_bt.add_argument("--fuzzy", action="store_true")
    p_bt.add_argument("--no-strict", action="store_true")
    p_bt.add_argument("--sample", type=int, default=None,
                       help="只抽样前N只股票（快速测试）")
    p_bt.set_defaults(func=cmd_backtest)

    # ── batch 命令 ─────────

    p_batch = subparsers.add_parser("batch", help="批量回测")
    p_batch.add_argument("--strategy", default="ma_convergence",
                        choices=["ma_convergence", "yijing"])
    p_batch.add_argument("--start", required=True,
                         help="开始日期")
    p_batch.add_argument("--end", required=True,
                         help="结束日期")
    p_batch.add_argument("--offset", type=int, default=1,
                         help="验证日距筛选日交易日数（默认1）")
    p_batch.add_argument("--pattern", default="阳阴阳阴阴阴阳")
    p_batch.add_argument("--fuzzy", action="store_true")
    p_batch.add_argument("--no-strict", action="store_true")
    p_batch.add_argument("--sample", type=int, default=None)
    p_batch.set_defaults(func=cmd_batch)

    # ── strategy-list 命令 ─────────

    p_list = subparsers.add_parser("strategy-list", help="列出所有策略")
    p_list.set_defaults(func=cmd_strategy_list)

    # ── 解析并执行 ─────────

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
