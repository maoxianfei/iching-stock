"""
K线卦象分析系统 — CLI 入口

用法:
    python main.py 600519                          # A股，默认月线24周期
    python main.py 600519 -i weekly -n 30          # A股周线，30周期
    python main.py AAPL -i monthly -n 24           # 美股月线
    python main.py 00700 -i weekly -n 50           # 港股周线
    python main.py 600519 -o my_report.html        # 指定输出路径
"""

import argparse
import sys
import os
import webbrowser
from datetime import datetime

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_fetcher import fetch_klines, get_stock_name, detect_market, normalize_symbol
from gua_calculator import run_analysis
from report_generator import generate_html


def main():
    parser = argparse.ArgumentParser(
        description="K线卦象分析系统 — 基于六十四卦的股票行情分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py 600519                  # 茅台，月线，24周期
  python main.py AAPL -i weekly -n 30    # 苹果，周线，30周期
  python main.py 00700 -i monthly -n 36  # 腾讯，月线，36周期
        """

    )
    parser.add_argument("symbol", help="股票代码 (A股6位数字 / 美股字母 / 港股5位数字)")
    parser.add_argument("-i", "--interval", choices=["weekly", "monthly"],
                        default="monthly", help="K线周期 (默认: monthly)")
    parser.add_argument("-n", "--count", type=int, default=24,
                        help="K线数量 (默认: 24, 最小: 6)")
    parser.add_argument("-o", "--output", default=None,
                        help="输出文件路径 (默认: output/<symbol>_<interval>_<timestamp>.html)")

    args = parser.parse_args()

    if args.count < 6:
        print("错误: K线数量至少需要 6 根才能生成卦象")
        sys.exit(1)

    # Step 1: 获取数据
    print(f"\n{'='*60}")
    print(f"  K线卦象分析系统")
    print(f"{'='*60}")
    print(f"  股票代码: {args.symbol}")
    print(f"  周期: {'周线' if args.interval == 'weekly' else '月线'}")
    print(f"  K线数量: {args.count}")
    print(f"{'='*60}\n")

    symbol, market = normalize_symbol(args.symbol)
    market_names = {"a_stock": "A股", "us_stock": "美股", "hk_stock": "港股"}
    market_name = market_names.get(market, market)
    print(f"[1/4] 获取股票信息...")
    stock_name = get_stock_name(symbol, market)
    print(f"      市场: {market_name} | 名称: {stock_name}")

    print(f"[2/4] 获取K线数据...")
    try:
        klines = fetch_klines(symbol, args.interval, args.count)
    except Exception as e:
        print(f"      错误: {e}")
        sys.exit(1)

    print(f"      成功获取 {len(klines)} 根K线")
    print(f"      日期范围: {klines[0].date} ~ {klines[-1].date}")

    if len(klines) < 6:
        print("      错误: K线数量不足 6 根，无法生成卦象")
        sys.exit(1)

    # Step 2: 计算卦象
    print(f"[3/4] 计算卦象...")
    try:
        analysis = run_analysis(klines, symbol, stock_name, args.interval)
    except Exception as e:
        print(f"      错误: {e}")
        sys.exit(1)

    print(f"      生成 {analysis.total_guas} 个卦象")
    print(f"      去重后 {len(analysis.unique_hexagrams)} 种卦象")
    print(f"      看涨比例: {analysis.bullish_ratio:.1%}")

    # 输出卦象序列
    print(f"\n  ┌{'─'*95}┐")
    print(f"  │ {'序号':<4} {'时间范围':<18} {'6个K线周期 (阳/阴)':<48} {'卦名':<10} {'看涨':<8} │")
    print(f"  ├{'─'*95}┤")
    for r in analysis.results:
        stars = "★" * r.hexagram.bullish_level + "☆" * (5 - r.hexagram.bullish_level)
        period_parts = []
        for p in r.periods_with_yao:
            icon = "☰" if p["is_yang"] else "☷"
            period_parts.append(f"{p['label']}{icon}")
        periods_str = " ".join(period_parts)
        print(f"  │ {r.index:<4} {r.date_range:<18} {periods_str:<48} {r.hexagram.name:<10} {stars:<8} │")
    print(f"  └{'─'*95}┘")

    # Step 3: 生成报告
    print(f"\n[4/4] 生成HTML报告...")
    try:
        html = generate_html(analysis)
    except Exception as e:
        print(f"      错误: {e}")
        sys.exit(1)

    # 确定输出路径
    if args.output:
        output_path = args.output
    else:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol}_{args.interval}_{ts}.html"
        output_path = os.path.join(output_dir, filename)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"      报告已保存: {output_path}")
    print(f"      文件大小: {os.path.getsize(output_path) / 1024:.1f} KB")

    # 自动打开浏览器
    abs_path = os.path.abspath(output_path)
    file_url = f"file:///{abs_path.replace(os.sep, '/')}"
    print(f"\n  正在打开浏览器预览...")
    webbrowser.open(file_url)

    print(f"\n{'='*60}")
    print(f"  分析完成！")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
