"""
iching-stock — 统一前端 Dashboard
==================================
Flask + SSE 实时进度推送，一站式调用三大子系统。
启动: python webui/app.py → http://localhost:5000
"""

import sys
import os
import io
import json
import threading
import queue
import time
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, render_template, request, Response, jsonify, send_from_directory

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24).hex()

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ═══════════════════════════════════════════
# 64 卦名字映射 (binary index 0-63)
# ═══════════════════════════════════════════

HEXAGRAM_NAMES = [
    "坤为地","地雷复","地水师","地泽临","地山谦","地火明夷","地风升","地天泰",
    "雷地豫","震为雷","雷水解","雷泽归妹","雷山小过","雷火丰","雷风恒","雷天大壮",
    "水地比","水雷屯","坎为水","水泽节","水山蹇","水火既济","水风井","水天需",
    "泽地萃","泽雷随","泽水困","兑为泽","泽山咸","泽火革","泽风大过","泽天夬",
    "山地剥","山雷颐","山水蒙","山泽损","艮为山","山火贲","山风蛊","山天大畜",
    "火地晋","火雷噬嗑","火水未济","火泽睽","火山旅","离为火","火风鼎","火天大有",
    "风地观","风雷益","风水涣","风泽中孚","风山渐","风火家人","巽为风","风天小畜",
    "天地否","天雷无妄","天水讼","天泽履","天山遁","天火同人","天风姤","乾为天",
]


def pattern_to_hexagram_index(pattern: str) -> int:
    """将 K线形态如 "阳阴阳阴阴阴阳" 转为 yao_bits (0-63)"""
    bits = 0
    for i, ch in enumerate(pattern):
        if ch == "阳":
            bits |= (1 << (5 - i))  # [0]=上爻, [5]=初爻
    return bits


# ═══════════════════════════════════════════
# 内存股票池（扫描→筛选 工作流）
# ═══════════════════════════════════════════

_pool_lock = threading.Lock()
_stock_pool = {
    "stocks": [],          # list[{code,name,hexagrams,close,vol_ma120_ratio,...}]
    "selected_hexagrams": [],  # [yao_bits, ...]
    "scan_time": None,     # ISO datetime
    "total_scanned": 0,
    "ma60_passed": 0,
    "pool_size": 0,
}


# ═══════════════════════════════════════════
# SSE 基础设施
# ═══════════════════════════════════════════

class _QueueWriter(io.TextIOBase):
    """将 stdout 输出逐行推送到队列，供 SSE 实时消费"""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self._q = q
        self._buf = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            stripped = line.strip()
            if stripped:
                self._q.put(stripped)
        return len(s)

    def flush(self) -> None:
        if self._buf.strip():
            self._q.put(self._buf.strip())
            self._buf = ""


def _stream_task(task_fn, *args, **kwargs):
    """
    SSE 流式执行器。
    在后台线程运行 task_fn，捕获 stdout 并通过 SSE 推送；
    task_fn 的返回值会作为 [RESULT] 事件发送。
    """
    q: queue.Queue = queue.Queue()
    result_holder = {"result": None, "error": None, "done": threading.Event()}

    def _worker():
        old_stdout = sys.stdout
        sys.stdout = _QueueWriter(q)
        try:
            result_holder["result"] = task_fn(*args, **kwargs)
        except Exception as exc:
            result_holder["error"] = str(exc)
            traceback.print_exc()
        finally:
            sys.stdout = old_stdout
            result_holder["done"].set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    def _generate():
        while not result_holder["done"].is_set() or not q.empty():
            try:
                line = q.get(timeout=0.2)
                yield f"data: {line}\n\n"
            except queue.Empty:
                continue

        while not q.empty():
            try:
                line = q.get_nowait()
                yield f"data: {line}\n\n"
            except queue.Empty:
                break

        if result_holder["error"]:
            yield f"data: [ERROR] {result_holder['error']}\n\n"
        else:
            yield "data: [DONE]\n\n"

        r = result_holder["result"]
        if r is not None:
            try:
                payload = json.dumps(r, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                payload = json.dumps({"raw": str(r)}, ensure_ascii=False)
            yield f"data: [RESULT] {payload}\n\n"

    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════
# 首页 & 静态
# ═══════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/reports/<path:filename>")
def serve_report(filename):
    return send_from_directory(OUTPUT_DIR, filename)


# ═══════════════════════════════════════════
# Tab 1: 卦象分析
# ═══════════════════════════════════════════

@app.route("/api/analyzer/run", methods=["POST"])
def api_analyzer_run():
    data = request.get_json(force=True, silent=True) or {}
    symbol = str(data.get("symbol", "")).strip()
    interval = str(data.get("interval", "monthly")).strip()
    count = int(data.get("count", 24))

    if not symbol:
        return jsonify({"error": "请填写股票代码"}), 400
    if count < 6:
        return jsonify({"error": "K线数量至少需要 6 根"}), 400

    before_files = set(os.listdir(OUTPUT_DIR)) if os.path.isdir(OUTPUT_DIR) else set()

    def _run():
        from iching_analyzer.main import run as analyzer_run
        analyzer_run(symbol, interval, count)
        after_files = set(os.listdir(OUTPUT_DIR))
        new_files = after_files - before_files
        report = None
        for f in sorted(new_files, reverse=True):
            if f.endswith(".html") and symbol in f:
                report = f
                break
        return {"report": report, "symbol": symbol, "interval": interval}

    return _stream_task(_run)


# ═══════════════════════════════════════════
# Tab 2: 卦象筛选 — 旧版单次扫描
# ═══════════════════════════════════════════

@app.route("/api/screener/run", methods=["POST"])
def api_screener_run():
    data = request.get_json(force=True, silent=True) or {}
    mode = str(data.get("mode", "market")).strip()
    code = str(data.get("code", "")).strip()
    days = int(data.get("days", 365))
    pattern = str(data.get("pattern", "阳阴阳阴阴阴阳")).strip()
    fuzzy = bool(data.get("fuzzy", False))
    no_strict = bool(data.get("no_strict", False))

    if mode == "single":
        if not code:
            return jsonify({"error": "单股模式需要填写股票代码"}), 400

        def _run():
            from hexagram_screener.main import scan_single
            results = scan_single(code, "a", pattern=pattern, fuzzy=fuzzy,
                                  strict_recent=not no_strict)
            return {"mode": "single", "code": code, "pattern": pattern,
                    "results": results}
    else:
        def _run():
            from hexagram_screener.main import scan_market
            summary = scan_market(time_filter_days=days, export=False,
                                  pattern=pattern, fuzzy=fuzzy,
                                  strict_recent=not no_strict)
            return {
                "mode": "market",
                "total_stocks": summary.total_stocks,
                "ma60_passed": summary.ma60_passed,
                "ma60_failed": summary.ma60_failed,
                "ma60_errors": summary.ma60_errors,
                "signal_count": summary.signal_count,
                "signal_stocks": summary.signal_stocks,
                "time_filter_days": summary.time_filter_days,
                "elapsed_seconds": round(summary.elapsed_seconds, 1),
                "pattern": pattern,
            }

    return _stream_task(_run)


# ═══════════════════════════════════════════
# Tab 2: 卦象筛选 — 新版三阶段工作流
# ═══════════════════════════════════════════

@app.route("/api/screener/hexagrams", methods=["GET"])
def api_screener_hexagrams():
    """返回 64 卦名称列表 [{index, name}, ...]"""
    return jsonify([
        {"index": i, "name": HEXAGRAM_NAMES[i]} for i in range(64)
    ])


@app.route("/api/screener/pool_status", methods=["GET"])
def api_screener_pool_status():
    """返回当前股票池状态"""
    with _pool_lock:
        return jsonify({
            "pool_size": len(_stock_pool["stocks"]),
            "selected_hexagrams": _stock_pool["selected_hexagrams"],
            "scan_time": _stock_pool["scan_time"],
            "total_scanned": _stock_pool["total_scanned"],
            "ma60_passed": _stock_pool["ma60_passed"],
        })


@app.route("/api/screener/scan", methods=["POST"])
def api_screener_scan():
    """
    全市场卦象扫描 → 入池
    接收选定的 hexagram indices (yao_bits 列表)
    对全市场A股进行 MA60 过滤 + 卦象命中检测，命中股票存入内存池
    """
    data = request.get_json(force=True, silent=True) or {}
    hexagram_indices = data.get("hexagrams", [])  # [yao_bits, ...]
    days = int(data.get("days", 365))
    daily = bool(data.get("daily", True))
    weekly = bool(data.get("weekly", True))
    monthly = bool(data.get("monthly", True))

    if not hexagram_indices:
        return jsonify({"error": "请至少选择一个卦象"}), 400

    hex_set = set(hexagram_indices)

    def _run():
        from core.data_fetcher import fetch_klines
        from core.models import KLine
        from hexagram_screener.screener import (
            get_a_share_list, fetch_and_filter_ma60, calculate_ma,
        )

        periods = []
        if daily: periods.append("daily")
        if weekly: periods.append("weekly")
        if monthly: periods.append("monthly")

        print("=" * 60)
        print("  卦象扫描入池")
        print(f"  目标卦象: {', '.join(HEXAGRAM_NAMES[i] for i in hexagram_indices)}")
        print(f"  扫描周期: {', '.join(periods)}")
        print("=" * 60)

        # Step 1: 获取全市场股票
        print("\n[1/4] 获取全市场A股列表...")
        stock_list = get_a_share_list()
        print(f"  全市场A股: {len(stock_list)} 只")

        # Step 2: MA60 周线过滤（并发 10 线程）
        print(f"\n[2/4] MA60周线过滤...")
        ma_passed = []
        done = 0
        total = len(stock_list)

        def _ma_filter(item):
            code, name, market = item
            return fetch_and_filter_ma60(code, name, market)

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_ma_filter, s): s for s in stock_list}
            for future in as_completed(futures):
                r = future.result()
                done += 1
                if r.above_ma:
                    ma_passed.append(r)
                if done % 200 == 0:
                    print(f"  MA60: {done}/{total} (通过 {len(ma_passed)})")

        print(f"  MA60通过: {len(ma_passed)} / {total}")

        # Step 3: 卦象扫描（日/周/月线）
        print(f"\n[3/4] 卦象命中扫描 (待扫 {len(ma_passed)} 只)...")
        period_counts = {"daily": 200, "weekly": 120, "monthly": 60}
        period_labels = {"daily": "日线", "weekly": "周线", "monthly": "月线"}

        pool_stocks = []
        scanned = 0

        def _scan_stock(stock):
            """扫描单只股票所有周期，返回 StockInfo dict 或 None"""
            stock_info = {
                "code": stock.code,
                "name": stock.name,
                "close": stock.close,
                "ma60": stock.ma60,
                "hexagrams_found": set(),
                "daily_signal": False,
                "weekly_signal": False,
                "monthly_signal": False,
                "vol_ma120_ratio": None,
                "vol_ma60_ratio": None,
            }
            any_hit = False

            for period in periods:
                try:
                    count = period_counts.get(period, 120)
                    klines = fetch_klines(stock.code, interval=period, count=count, market="a")
                    if not klines or len(klines) < 7:
                        continue

                    # 卦象检测
                    for i in range(len(klines) - 5):
                        window = klines[i:i+6]
                        yao_bits = 0
                        for j, kline in enumerate(window):
                            position = 6 - j
                            if kline.is_yang:
                                yao_bits |= (1 << (position - 1))
                        if yao_bits in hex_set:
                            name = HEXAGRAM_NAMES[yao_bits]
                            stock_info["hexagrams_found"].add(name)
                            any_hit = True
                            if period == "daily":
                                stock_info["daily_signal"] = True
                            elif period == "weekly":
                                stock_info["weekly_signal"] = True
                            elif period == "monthly":
                                stock_info["monthly_signal"] = True

                    # 日线成交量分析（只在日线周期做）
                    if period == "daily" and len(klines) >= 120:
                        last_vol = klines[-1].volume
                        ma120_vol = calculate_ma_volume(klines, 120)
                        ma60_vol = calculate_ma_volume(klines, 60)
                        if ma120_vol and ma120_vol > 0:
                            stock_info["vol_ma120_ratio"] = round(last_vol / ma120_vol, 2)
                        if ma60_vol and ma60_vol > 0:
                            stock_info["vol_ma60_ratio"] = round(last_vol / ma60_vol, 2)

                except Exception:
                    pass

            return stock_info if any_hit else None

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(_scan_stock, s): s for s in ma_passed}
            for future in as_completed(futures):
                result = future.result()
                scanned += 1
                if result:
                    result["hexagrams_found"] = sorted(result["hexagrams_found"])
                    pool_stocks.append(result)
                if scanned % 100 == 0:
                    print(f"  卦象扫描: {scanned}/{len(ma_passed)} (命中 {len(pool_stocks)})")

        print(f"  扫描完成: 命中 {len(pool_stocks)} 只")

        # Step 4: 存入内存池
        with _pool_lock:
            _stock_pool["stocks"] = pool_stocks
            _stock_pool["selected_hexagrams"] = hexagram_indices
            _stock_pool["scan_time"] = datetime.now().isoformat(timespec="seconds")
            _stock_pool["total_scanned"] = len(stock_list)
            _stock_pool["ma60_passed"] = len(ma_passed)
            _stock_pool["pool_size"] = len(pool_stocks)

        return {
            "pool_size": len(pool_stocks),
            "total_scanned": len(stock_list),
            "ma60_passed": len(ma_passed),
            "hexagrams": [HEXAGRAM_NAMES[i] for i in hexagram_indices],
            "stocks": pool_stocks[:200],  # 前端最多展示 200
        }

    return _stream_task(_run)


def calculate_ma_volume(klines, period: int):
    """计算成交量均线"""
    if len(klines) < period:
        return None
    vol_list = [k.volume for k in klines[-period:]]
    return sum(vol_list) / period


@app.route("/api/screener/filter", methods=["POST"])
def api_screener_filter():
    """
    对股票池应用组合条件过滤
    条件（可多选，AND 逻辑）：
      - vol_ge_ma120: 成交量 >= 120日均量
      - vol_ge_ma60:  成交量 >= 60日均量
      - signal_daily:  日线级别卦象信号
      - signal_weekly: 周线级别卦象信号
      - signal_monthly: 月线级别卦象信号
    """
    data = request.get_json(force=True, silent=True) or {}
    conditions = {
        "vol_ge_ma120": bool(data.get("vol_ge_ma120", False)),
        "vol_ge_ma60": bool(data.get("vol_ge_ma60", False)),
        "signal_daily": bool(data.get("signal_daily", False)),
        "signal_weekly": bool(data.get("signal_weekly", False)),
        "signal_monthly": bool(data.get("signal_monthly", False)),
    }

    # 如果没选任何条件，返回全部
    active = [k for k, v in conditions.items() if v]
    if not active:
        active = ["无过滤条件"]

    with _pool_lock:
        pool = list(_stock_pool["stocks"])
        hex_list = [_stock_pool["selected_hexagrams"]]

    filtered = []
    for s in pool:
        if conditions["vol_ge_ma120"]:
            if s["vol_ma120_ratio"] is None or s["vol_ma120_ratio"] < 1.0:
                continue
        if conditions["vol_ge_ma60"]:
            if s["vol_ma60_ratio"] is None or s["vol_ma60_ratio"] < 1.0:
                continue
        if conditions["signal_daily"] and not s["daily_signal"]:
            continue
        if conditions["signal_weekly"] and not s["weekly_signal"]:
            continue
        if conditions["signal_monthly"] and not s["monthly_signal"]:
            continue
        filtered.append(s)

    return jsonify({
        "total_in_pool": len(pool),
        "filtered": len(filtered),
        "conditions": active,
        "results": filtered[:200],
    })


# ═══════════════════════════════════════════
# Tab 3: 策略回测
# ═══════════════════════════════════════════

@app.route("/api/backtest/strategies", methods=["GET"])
def api_backtest_strategies():
    from backtest.strategies import list_strategies
    return jsonify(list_strategies())


def _backtest_result_to_dict(r: dict) -> dict:
    return {
        "screen_date": r.get("screen_date", ""),
        "verify_date": r.get("verify_date", ""),
        "total_screened": r.get("total_screened", 0),
        "passed": r.get("passed", 0),
        "verify_count": r.get("verify_count", 0),
        "winners": r.get("winners", 0),
        "losers": r.get("losers", 0),
        "win_rate": r.get("win_rate", 0),
        "avg_return": r.get("avg_return", 0),
        "max_gain": r.get("max_gain", 0),
        "max_loss": r.get("max_loss", 0),
        "details": r.get("details", [])[:50],
    }


@app.route("/api/backtest/screen", methods=["POST"])
def api_backtest_screen():
    data = request.get_json(force=True, silent=True) or {}
    strategy_name = str(data.get("strategy", "ma_convergence")).strip()

    def _run():
        from backtest.strategies import get_strategy
        from backtest.engine import run_screen
        strategy = get_strategy(strategy_name)
        results = run_screen(strategy)
        serialized = []
        for r in results:
            serialized.append({
                "code": r.code, "name": r.name,
                "price": r.price, "pct_change": r.pct_change,
                "signal_desc": r.signal_desc,
                "filters": [{"name": fr.name, "passed": fr.passed,
                             "detail": fr.detail} for fr in r.filter_results],
            })
        try:
            from backtest.output import to_excel
            excel_path = to_excel(results)
        except Exception:
            excel_path = ""
        return {
            "count": len(results),
            "results": serialized[:100],
            "excel": os.path.basename(excel_path) if excel_path else "",
        }

    return _stream_task(_run)


@app.route("/api/backtest/backtest", methods=["POST"])
def api_backtest_backtest():
    data = request.get_json(force=True, silent=True) or {}
    strategy_name = str(data.get("strategy", "ma_convergence")).strip()
    screen_date = str(data.get("screen_date", "")).strip()
    verify_date = str(data.get("verify_date", "")).strip() or None
    sample = int(data.get("sample", 0)) or None

    if not screen_date:
        return jsonify({"error": "请选择筛选日期"}), 400

    def _run():
        from backtest.strategies import get_strategy
        from backtest.backtester import run_backtest
        strategy = get_strategy(strategy_name)
        result = run_backtest(strategy=strategy, screen_date=screen_date,
                              verify_date=verify_date, sample_size=sample,
                              verbose=True)
        return _backtest_result_to_dict(result)

    return _stream_task(_run)


@app.route("/api/backtest/batch", methods=["POST"])
def api_backtest_batch():
    data = request.get_json(force=True, silent=True) or {}
    strategy_name = str(data.get("strategy", "ma_convergence")).strip()
    start_date = str(data.get("start_date", "")).strip()
    end_date = str(data.get("end_date", "")).strip()
    offset = int(data.get("offset", 1))
    sample = int(data.get("sample", 0)) or None

    if not start_date or not end_date:
        return jsonify({"error": "请选择起止日期"}), 400

    def _run():
        from backtest.strategies import get_strategy
        from backtest.backtester import run_batch_backtest
        strategy = get_strategy(strategy_name)
        results = run_batch_backtest(strategy=strategy, start_date=start_date,
                                     end_date=end_date, offset_days=offset,
                                     sample_size=sample, verbose=True)
        return {
            "total_days": len(results),
            "summary": {
                "total_verify": sum(r.get("verify_count", 0) for r in results),
                "total_winners": sum(r.get("winners", 0) for r in results),
                "avg_win_rate": round(
                    sum(r.get("winners", 0) for r in results)
                    / max(sum(r.get("verify_count", 0) for r in results), 1) * 100, 1,
                ),
                "avg_return": round(
                    sum(r.get("avg_return", 0) for r in results)
                    / max(len(results), 1), 2,
                ),
            },
            "details": [_backtest_result_to_dict(r) for r in results],
        }

    return _stream_task(_run)


# ═══════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 55)
    print("  大股票系统 Dashboard")
    print("  http://localhost:5000")
    print("=" * 55)
    print()
    print("  子系统：")
    print("    Tab 1 — 卦象分析 (iching_analyzer)")
    print("    Tab 2 — 卦象筛选 (hexagram_screener)")
    print("    Tab 3 — 策略回测 (backtest)")
    print()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
