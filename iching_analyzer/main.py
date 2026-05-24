"""
易经个股模块 — CLI 入口
基于六十四卦的股票行情单股深度分析 + HTML报告生成

用法:
    python main.py analyze 600519                    # A股，默认月线24周期
    python main.py analyze 600519 -i weekly -n 30    # A股周线，30周期
    python main.py analyze AAPL -i monthly -n 24     # 美股月线
    python main.py analyze 00700 -i weekly -n 50     # 港股周线
    python main.py analyze 600519 -o my_report.html # 指定输出路径
"""

import sys
import os

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import argparse
import webbrowser
from datetime import datetime

from core.models import normalize_symbol, get_stock_name
from core.data_fetcher import fetch_klines
from iching_analyzer.gua_calculator import run_analysis
from iching_analyzer.report_generator import generate_html


def run(symbol: str, interval: str = "monthly", count: int = 24, output: str = None):
    """
    运行个股卦象分析

    Args:
        symbol: 股票代码
        interval: 周期 (weekly/monthly)
        count: K线数量
        output: 输出文件路径
    """
    if count < 6:
        print("错误: K线数量至少需要 6 根才能生成卦象")
        return

    # Step 1: 获取数据
    print(f"\n{'='*60}")
    print(f"  K线卦象分析系统 — 易经个股模块")
    print(f"{'='*60}")
    print(f"  股票代码: {symbol}")
    print(f"  周期: {'周线' if interval == 'weekly' else '月线'}")
    print(f"  K线数量: {count}")
    print(f"{'='*60}\n")

    sym, market = normalize_symbol(symbol)
    market_names = {"a": "A股", "us": "美股", "hk": "港股"}
    market_name = market_names.get(market, market)
    print(f"[1/4] 获取股票信息...")
    stock_name = get_stock_name(sym, market)
    print(f"      市场: {market_name} | 名称: {stock_name}")

    print(f"[2/4] 获取K线数据...")
    try:
        klines = fetch_klines(sym, interval, count)
    except Exception as e:
        print(f"      错误: {e}")
        return

    print(f"      成功获取 {len(klines)} 根K线")
    print(f"      日期范围: {klines[0].date} ~ {klines[-1].date}")

    if len(klines) < 6:
        print("      错误: K线数量不足 6 根，无法生成卦象")
        return

    # Step 2: 计算卦象
    print(f"[3/4] 计算卦象...")
    try:
        analysis = run_analysis(klines, sym, stock_name, interval)
    except Exception as e:
        print(f"      错误: {e}")
        return

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
        return

    # 确定输出路径
    if output:
        output_path = output
    else:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{sym}_{interval}_{ts}.html"
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
