"""
通达信公式函数库
实现所有被公式引用的内置函数。

支持的函数列表（按分类）：
行情数据: CLOSE/C, OPEN, HIGH, LOW, VOL/V, AMOUNT
统计函数：MA, EMA, SMA, HHV, LLV, SUM, COUNT, STD
逻辑函数：IF, CROSS, EVERY, EXIST, BETWEEN
引用函数：REF
数学函数：MAX, MIN, ABS, CEILING, FLOOR
"""

import numpy as np
import pandas as pd
from typing import Any, Union


# ============== 基础数据字段别名 ==============

FIELD_ALIASES = {
    'CLOSE': 'close',
    'C': 'close',
    'OPEN': 'open',
    'O': 'open',
    'HIGH': 'high',
    'H': 'high',
    'LOW': 'low',
    'L': 'low',
    'VOL': 'volume',
    'V': 'volume',
    'AMOUNT': 'amount',
    'AMO': 'amount',
}


# ============== 函数注册表 ==============

class FunctionRegistry:
    """
    函数注册表。
    保存所有支持的函数名到实际实现的映射。
    """
    _functions: dict = {}
    
    @classmethod
    def register(cls, name: str, func):
        """注册一个函数"""
        cls._functions[name.upper()] = func
    
    @classmethod
    def get(cls, name: str):
        """获取函数实现"""
        return cls._functions.get(name.upper())
    
    @classmethod
    def has(cls, name: str) -> bool:
        return name.upper() in cls._functions


def register_func(name: str):
    """装饰器：注册函数"""
    def decorator(func):
        FunctionRegistry.register(name, func)
        return func
    return decorator


# ============== 工具函数 ==============

def _to_series(x) -> pd.Series:
    """确保输入是 pd.Series"""
    if isinstance(x, pd.Series):
        return x
    if isinstance(x, np.ndarray):
        if len(x.shape) > 1:
            x = x.flatten()
        return pd.Series(x)
    return pd.Series(x)


def _resolve_field(df: pd.DataFrame, name: str) -> pd.Series:
    """解析字段名，返回对应 Series"""
    name = name.upper()
    if name in FIELD_ALIASES:
        field = FIELD_ALIASES[name]
        if field in df.columns:
            return df[field]
    # 尝试直接作为列名
    if name in df.columns:
        return df[name]
    # 尝试小写
    if name.lower() in df.columns:
        return df[name.lower()]
    raise KeyError(f"未知字段: {name}")


# ============== 内置函数实现 ==============


@register_func('REF')
def func_REF(df: pd.DataFrame, args: list) -> pd.Series:
    """
    REF(X, N) — 引用 N 周期前的 X 值。
    用法: REF(CLOSE, 1) 表示上一周期的收盘价。
    """
    if len(args) != 2:
        raise ValueError("REF 需要2个参数: REF(X, N)")
    x = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    return x.shift(n)


@register_func('MA')
def func_MA(df: pd.DataFrame, args: list) -> pd.Series:
    """
    MA(X, N) — X 的 N 日简单移动平均。
    用法: MA(CLOSE, 5) 表示 5 日均线。
    """
    if len(args) != 2:
        raise ValueError("MA 需要2个参数: MA(X, N)")
    x = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    return x.rolling(window=n, min_periods=1).mean()


@register_func('EMA')
def func_EMA(df: pd.DataFrame, args: list) -> pd.Series:
    """
    EMA(X, N) — X 的 N 日指数移动平均。
    用法: EMA(CLOSE, 12) 表示 12 日指数均线。
    """
    if len(args) != 2:
        raise ValueError("EMA 需要2个参数: EMA(X, N)")
    x = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    return x.ewm(span=n, adjust=False, min_periods=1).mean()


@register_func('SMA')
def func_SMA(df: pd.DataFrame, args: list) -> pd.Series:
    """
    SMA(X, N, M) — 通达信加权移动平均（递归算法）。
    算法: SMA(t) = (X(t)*M + SMA(t-1)*(N-M)) / N
    用法: SMA(VAR1A, 4, 1)
    """
    if len(args) != 3:
        raise ValueError("SMA 需要3个参数: SMA(X, N, M)")
    x = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    m = float(_resolve_n(args[2], df))
    
    result = np.zeros(len(x))
    result[0] = x.iloc[0]
    for i in range(1, len(x)):
        result[i] = (x.iloc[i] * m + result[i-1] * (n - m)) / n
    return pd.Series(result, index=x.index)


@register_func('HHV')
def func_HHV(df: pd.DataFrame, args: list) -> pd.Series:
    """
    HHV(X, N) — N 周期内 X 的最高值。
    用法: HHV(HIGH, 5) 表示 5 日内最高价
    """
    if len(args) != 2:
        raise ValueError("HHV 需要2个参数: HHV(X, N)")
    x = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    return x.rolling(window=n, min_periods=1).max()


@register_func('LLV')
def func_LLV(df: pd.DataFrame, args: list) -> pd.Series:
    """
    LLV(X, N) — N 周期内 X 的最低值。
    用法: LLV(LOW, 5) 表示 5 日内最低价
    """
    if len(args) != 2:
        raise ValueError("LLV 需要2个参数: LLV(X, N)")
    x = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    return x.rolling(window=n, min_periods=1).min()


@register_func('SUM')
def func_SUM(df: pd.DataFrame, args: list) -> pd.Series:
    """
    SUM(X, N) — N 周期内 X 的总和。
    用法: SUM(VOL, 5) 表示 5 日成交量之和
    """
    if len(args) != 2:
        raise ValueError("SUM 需要2个参数: SUM(X, N)")
    x = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    return x.rolling(window=n, min_periods=1).sum()


@register_func('COUNT')
def func_COUNT(df: pd.DataFrame, args: list) -> pd.Series:
    """
    COUNT(COND, N) — N 周期内满足条件的次数。
    用法: COUNT(CLOSE > OPEN, 5) 表示 5 日内收阳的天数
    """
    if len(args) != 2:
        raise ValueError("COUNT 需要2个参数: COUNT(COND, N)")
    cond = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    return cond.rolling(window=n, min_periods=1).sum()


@register_func('EVERY')
def func_EVERY(df: pd.DataFrame, args: list) -> pd.Series:
    """
    EVERY(COND, N) — N 周期内是否一直满足条件。
    用法: EVERY(CLOSE > OPEN, 5) 表示连续 5 日收阳
    """
    if len(args) != 2:
        raise ValueError("EVERY 需要2个参数: EVERY(COND, N)")
    cond = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    return cond.rolling(window=n, min_periods=n).sum() >= n


@register_func('EXIST')
def func_EXIST(df: pd.DataFrame, args: list) -> pd.Series:
    """
    EXIST(COND, N) — N 周期内是否存在满足条件的情况。
    用法: EXIST(CLOSE > OPEN, 5) 表示 5 日内是否存在收阳
    """
    if len(args) != 2:
        raise ValueError("EXIST 需要2个参数: EXIST(COND, N)")
    cond = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    return cond.rolling(window=n, min_periods=1).sum() > 0


@register_func('CROSS')
def func_CROSS(df: pd.DataFrame, args: list) -> pd.Series:
    """
    CROSS(A, B) — A 上穿 B（前一期 A <= B 且本期 A > B）。
    用法: CROSS(MA5, MA20) 表示 5 日均线上穿 20 日均线
    """
    if len(args) != 2:
        raise ValueError("CROSS 需要2个参数: CROSS(A, B)")
    a = _evaluate_arg(df, args[0])
    b = _evaluate_arg(df, args[1])
    return (a > b) & (a.shift(1) <= b.shift(1))


@register_func('MAX')
def func_MAX(df: pd.DataFrame, args: list) -> pd.Series:
    """
    MAX(A, B) — 求 A 和 B 的最大值。
    用法: MAX(OPEN, CLOSE) 表示开盘价和收盘价中较大者
    """
    if len(args) != 2:
        raise ValueError("MAX 需要2个参数: MAX(A, B)")
    a = _evaluate_arg(df, args[0])
    b = _evaluate_arg(df, args[1])
    return np.maximum(a, b)


@register_func('MIN')
def func_MIN(df: pd.DataFrame, args: list) -> pd.Series:
    """
    MIN(A, B) — 求 A 和 B 的最小值。
    用法: MIN(OPEN, CLOSE)
    """
    if len(args) != 2:
        raise ValueError("MIN 需要2个参数: MIN(A, B)")
    a = _evaluate_arg(df, args[0])
    b = _evaluate_arg(df, args[1])
    return np.minimum(a, b)


@register_func('ABS')
def func_ABS(df: pd.DataFrame, args: list) -> pd.Series:
    """
    ABS(X) — X 的绝对值。
    用法: ABS(CLOSE - OPEN)
    """
    if len(args) != 1:
        raise ValueError("ABS 需要1个参数: ABS(X)")
    x = _evaluate_arg(df, args[0])
    return np.abs(x)


@register_func('IF')
def func_IF(df: pd.DataFrame, args: list) -> pd.Series:
    """
    IF(COND, A, B) — 如果 COND 为真则返回 A，否则返回 B。
    用法: IF(CLOSE > OPEN, HIGH, LOW)
    """
    if len(args) != 3:
        raise ValueError("IF 需要3个参数: IF(COND, A, B)")
    cond = _evaluate_arg(df, args[0])
    a = _evaluate_arg(df, args[1])
    b = _evaluate_arg(df, args[2])
    return np.where(cond, a, b)


@register_func('BETWEEN')
def func_BETWEEN(df: pd.DataFrame, args: list) -> pd.Series:
    """
    BETWEEN(X, A, B) — X 是否在 A 和 B 之间（包含边界）。
    用法: BETWEEN(CLOSE, MA5, MA20) 表示收盘价在 5 日和 20 日均线之间
    """
    if len(args) != 3:
        raise ValueError("BETWEEN 需要3个参数: BETWEEN(X, A, B)")
    x = _evaluate_arg(df, args[0])
    a = _evaluate_arg(df, args[1])
    b = _evaluate_arg(df, args[2])
    return (x >= np.minimum(a, b)) & (x <= np.maximum(a, b))


@register_func('STD')
def func_STD(df: pd.DataFrame, args: list) -> pd.Series:
    """
    STD(X, N) — N 周期内 X 的标准差。
    用法: STD(CLOSE, 20)
    """
    if len(args) != 2:
        raise ValueError("STD 需要2个参数: STD(X, N)")
    x = _evaluate_arg(df, args[0])
    n = int(_resolve_n(args[1], df))
    return x.rolling(window=n, min_periods=1).std(ddof=0)


@register_func('CEILING')
def func_CEILING(df: pd.DataFrame, args: list) -> pd.Series:
    """CEILING(X) — 向上取整。"""
    if len(args) != 1:
        raise ValueError("CEILING 需要1个参数: CEILING(X)")
    x = _evaluate_arg(df, args[0])
    return np.ceil(x)


@register_func('FLOOR')
def func_FLOOR(df: pd.DataFrame, args: list) -> pd.Series:
    """FLOOR(X) — 向下取整。"""
    if len(args) != 1:
        raise ValueError("FLOOR 需要1个参数: FLOOR(X)")
    x = _evaluate_arg(df, args[0])
    return np.floor(x)


# ============== 辅助函数 ==============

def _evaluate_arg(df: pd.DataFrame, arg) -> pd.Series:
    """
    评估公式参数，返回 Series。
    arg 可以是 AST 节点、数字、字符串等。
    """
    from formula.parser import Number, Identifier, BinOp, UnaryOp, FuncCall
    
    if isinstance(arg, (int, float)):
        return pd.Series(np.full(len(df), float(arg)), index=df.index)
    
    if isinstance(arg, Number):
        return pd.Series(np.full(len(df), arg.value), index=df.index)
    
    if isinstance(arg, Identifier):
        name = arg.name.upper()
        # 先检查是不是行情字段
        if name in FIELD_ALIASES:
            field = FIELD_ALIASES[name]
            if field in df.columns:
                return df[field]
        # 再检查是不是已计算的变量（存储在 df 列中）
        if name in df.columns:
            return df[name]
        # 如果是数字字符串
        try:
            val = float(name)
            return pd.Series(np.full(len(df), val), index=df.index)
        except ValueError:
            pass
        raise KeyError(f"未知标识符: {arg.name}")
    
    if isinstance(arg, BinOp):
        return _eval_binop(df, arg)
    
    if isinstance(arg, UnaryOp):
        x = _evaluate_arg(df, arg.operand)
        if arg.op == '-':
            return -x
        
    if isinstance(arg, FuncCall):
        return _eval_funcall(df, arg)
    
    raise ValueError(f"无法评估的参数类型: {type(arg)}")


def _eval_binop(df: pd.DataFrame, node) -> pd.Series:
    """评估二元运算"""
    left = _evaluate_arg(df, node.left)
    right = _evaluate_arg(df, node.right)
    
    op = node.op
    if op == '+':
        return left + right
    elif op == '-':
        return left - right
    elif op == '*':
        return left * right
    elif op == '/':
        # 防止除零
        return left / right.replace(0, np.nan)
    elif op == '>':
        return left > right
    elif op == '<':
        return left < right
    elif op == '>=':
        return left >= right
    elif op == '<=':
        return left <= right
    elif op == '=':
        return left == right
    elif op == '<>':
        return left != right
    elif op == 'AND':
        return left & right
    elif op == 'OR':
        return left | right
    else:
        raise ValueError(f"未知运算符: {op}")


def _eval_funcall(df: pd.DataFrame, node) -> pd.Series:
    """评估函数调用"""
    func = FunctionRegistry.get(node.name)
    if func is None:
        raise ValueError(f"不支持的函数: {node.name}")
    return func(df, node.args)


def _resolve_n(arg, df: pd.DataFrame) -> float:
    """解析参数为数字"""
    from formula.parser import Number
    if isinstance(arg, Number):
        return arg.value
    if isinstance(arg, (int, float)):
        return float(arg)
    # 如果是 AST 节点
    result = _evaluate_arg(df, arg)
    return float(result.iloc[-1] if hasattr(result, 'iloc') else result)


def _resolve_constant(arg) -> float:
    """解析常量值"""
    from formula.parser import Number
    if isinstance(arg, Number):
        return arg.value
    if isinstance(arg, (int, float)):
        return float(arg)
    return float(str(arg))

