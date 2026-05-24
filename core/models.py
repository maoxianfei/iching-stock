"""
核心数据模型 — K线 + 市场识别
统一 volume 类型为 float，兼容 int 赋值
"""

import re
import requests
from dataclasses import dataclass
from typing import Optional


# ============================================================
# K线数据结构
# ============================================================

@dataclass
class KLine:
    """统一 K 线数据结构"""
    date: str          # "YYYY-MM-DD"
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @property
    def is_yang(self) -> bool:
        """阳线：收盘 >= 开盘"""
        return self.close >= self.open


# ============================================================
# 市场识别
# ============================================================

def detect_market(code: str) -> str:
    """
    根据代码格式自动识别市场
    - "600519" / "000001" / "300750" → "a"
    - "AAPL" / "TSLA" / "BABA" → "us"
    - "00700" / "09988" / "01810" → "hk"
    """
    code = code.strip().upper()

    # A股：6位纯数字
    if re.match(r'^\d{6}$', code):
        return "a"

    # 港股：5位数字（也可能带.HK后缀）
    if re.match(r'^\d{5}$', code):
        return "hk"
    if code.endswith('.HK'):
        return "hk"

    # 美股：纯字母，1-5个字符
    if re.match(r'^[A-Z]{1,5}$', code):
        return "us"

    raise ValueError(f"无法识别股票代码市场: {code}")


def normalize_symbol(code: str) -> tuple[str, str]:
    """
    标准化股票代码，返回 (标准化代码, 市场类型)
    市场类型: "a" / "hk" / "us"
    """
    market = detect_market(code)
    symbol = code.strip().upper()

    if market == "hk":
        # 去掉 .HK 后缀
        symbol = symbol.replace('.HK', '')
        # 补齐5位
        symbol = symbol.zfill(5)

    return symbol, market


def get_stock_name(symbol: str, market: str = "") -> str:
    """尝试获取股票中文名称"""
    if not market:
        _, market = normalize_symbol(symbol)

    try:
        if market == "a":
            # 使用腾讯行情接口获取A股名称
            # 上海: 600/601/603/605/688, 深圳: 000/001/002/003/300/301
            if symbol.startswith(('6', '68')):
                prefix = "sh"
            else:
                prefix = "sz"
            url = f"https://qt.gtimg.cn/q={prefix}{symbol}"
            r = requests.get(url, timeout=10)
            r.encoding = "gbk"
            # 格式: v_sh600519="1~贵州茅台~..."
            m = re.search(r'"([^"]+)"', r.text)
            if m:
                parts = m.group(1).split("~")
                if len(parts) > 1 and parts[1]:
                    return parts[1]
        elif market == "us":
            # 使用新浪获取中文名
            url = f"https://hq.sinajs.cn/list=gb_{symbol.lower()}"
            r = requests.get(url, headers={
                "Referer": "https://finance.sina.com.cn/",
                "User-Agent": "Mozilla/5.0",
            }, timeout=10)
            r.encoding = "gbk"
            m = re.search(r'"(.+?)"', r.text)
            if m:
                return m.group(1).split(",")[0]
        elif market == "hk":
            # 使用腾讯获取中文名
            url = f"https://qt.gtimg.cn/q=r_hk{symbol}"
            r = requests.get(url, timeout=10)
            r.encoding = "gbk"
            m = re.search(r'"(.+?)"', r.text)
            if m:
                return m.group(1).split("~")[1]
    except Exception:
        pass

    return symbol
