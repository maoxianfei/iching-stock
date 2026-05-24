"""
策略模块初始化 — 策略注册表
"""

from backtest.strategy_base import BaseStrategy, FilterResult, ScreenResult

# 策略注册表：名称 → 策略类
STRATEGY_REGISTRY = {
    "ma_convergence": "backtest.strategies.ma_convergence.MaConvergenceStrategy",
    "yijing":          "backtest.strategies.yijing.YijingStrategy",
}


def get_strategy(name: str, **kwargs) -> BaseStrategy:
    """根据名称实例化策略"""
    entry = STRATEGY_REGISTRY.get(name)
    if entry is None:
        raise ValueError(f"未知策略: {name}，可选: {list(STRATEGY_REGISTRY.keys())}")

    # 支持 "module.path.ClassName" 格式
    import importlib
    module_path, class_name = entry.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(**kwargs)


def list_strategies() -> dict:
    """列出所有已注册策略及其描述"""
    result = {}
    for name in STRATEGY_REGISTRY:
        try:
            strat = get_strategy(name)
            result[name] = strat.description
        except Exception as e:
            result[name] = f"(加载失败: {e})"
    return result
