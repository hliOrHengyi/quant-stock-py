"""
通达信公式执行引擎 (Evaluator)

将解析后的 AST 在 DataFrame 数据上执行，返回选股结果。

执行流程：
1. 顺序执行所有赋值语句，将中间变量计算结果存入 DataFrame
2. 执行 XG 语句（选股信号），获取最终布尔结果
3. 返回最后一行的布尔值（True = 符合条件）
"""
import pandas as pd
import numpy as np
from typing import Optional

from formula.parser import (
    Program, AssignStmt, XGStmt, ExprStmt,
    Number, Identifier, BinOp, UnaryOp, FuncCall,
    ASTNode
)
from formula.functions import (
    FunctionRegistry, FIELD_ALIASES,
    _evaluate_arg, _eval_binop, _eval_funcall
)


class FormulaError(Exception):
    """公式执行错误"""
    pass


class Evaluator:
    """
    公式执行器。
    
    用法:
        evaluator = Evaluator(df)
        result = evaluator.evaluate(ast)
        # result 为 True/False，表示该股票是否满足条件
    """
    
    def __init__(self, df: pd.DataFrame):
        """
        初始化执行器。
        
        Args:
            df: 包含股票/指数日线数据的 DataFrame
                 必须包含列: date, open, high, low, close, volume, amount
        """
        self.df = df.copy()
        # 确保数值类型
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors='coerce')
        
        # 存储中间变量（大写）
        self._variables = {}
        
        # 预计算行情字段别名
        self._init_field_aliases()
    
    def _init_field_aliases(self):
        """为行情字段创建大写别名列"""
        for alias, field in FIELD_ALIASES.items():
            if field in self.df.columns:
                self.df[alias] = self.df[field]
    
    def evaluate(self, ast: Program) -> bool:
        """
        执行完整的公式 AST，返回选股结果。
        
        Returns:
            True 表示该股票/指数满足条件
            False 表示不满足
        """
        xg_result = None
        
        for stmt in ast.statements:
            if isinstance(stmt, AssignStmt):
                self._exec_assign(stmt)
            elif isinstance(stmt, XGStmt):
                xg_result = self._exec_xg(stmt)
            elif isinstance(stmt, ExprStmt):
                self._exec_expr(stmt)
        
        if xg_result is None:
            raise FormulaError("公式中未找到 XG 选股信号输出语句")
        
        # 取最后一行的结果
        last_val = xg_result.iloc[-1] if hasattr(xg_result, 'iloc') else xg_result
        
        # 处理 NaN
        if pd.isna(last_val):
            return False
        
        return bool(last_val)
    

    def evaluate_debug(self, ast: Program) -> dict:
        """执行公式并返回详细分析"""
        xg_result = None
        for stmt in ast.statements:
            if isinstance(stmt, AssignStmt):
                self._exec_assign(stmt)
            elif isinstance(stmt, XGStmt):
                xg_result = self._exec_xg(stmt)
            elif isinstance(stmt, ExprStmt):
                self._exec_expr(stmt)
        if xg_result is None:
            raise FormulaError("\u516c\u5f0f\u4e2d\u672a\u627e\u5230 XG \u9009\u80a1\u4fe1\u53f7\u8f93\u51fa\u8bed\u53e5")
        last_val = xg_result.iloc[-1]
        result = False if pd.isna(last_val) else bool(last_val)
        variables = {}
        for col in self.df.columns:
            if col.isupper() and col not in FIELD_ALIASES:
                try:
                    v = self.df[col].iloc[-1]
                    if isinstance(v, (int, float, np.integer, np.floating)):
                        variables[col] = round(float(v), 4)
                    elif isinstance(v, np.bool_):
                        variables[col] = bool(v)
                    else:
                        variables[col] = str(v)
                except:
                    pass
        xg_details = []
        for stmt in ast.statements:
            if isinstance(stmt, XGStmt):
                xg_details.append(self._debug_expr(stmt.expr))
        return {"result": result, "variables": variables, "xg_details": xg_details,
                "price": {"close": float(self.df["close"].iloc[-1]),
                          "open": float(self.df["open"].iloc[-1]),
                          "high": float(self.df["high"].iloc[-1]),
                          "low": float(self.df["low"].iloc[-1]),
                          "volume": int(self.df["volume"].iloc[-1]),
                          "amount": float(self.df["amount"].iloc[-1])}}

    def _debug_expr(self, node) -> dict:
        if isinstance(node, BinOp):
            if node.op.upper() == "AND":
                # Flatten AND chain
                conditions = []
                def collect(n):
                    if isinstance(n, BinOp) and n.op.upper() == "AND":
                        collect(n.left)
                        collect(n.right)
                    else:
                        conditions.append(n)
                collect(node)
                items = []
                for c in conditions:
                    val = self._eval_node(c).iloc[-1] if hasattr(self._eval_node(c), "iloc") else self._eval_node(c)
                    name = c.name if isinstance(c, Identifier) else str(c)
                    val_str = f"{float(val):.2f}" if hasattr(val, "__float__") else str(val)
                    items.append(f"{name}={val_str}")
                return {"type": "and_chain", "conditions": items, "result": True}
            else:
                left_val = self._eval_node(node.left).iloc[-1] if hasattr(self._eval_node(node.left), "iloc") else self._eval_node(node.left)
                right_val = self._eval_node(node.right).iloc[-1] if hasattr(self._eval_node(node.right), "iloc") else self._eval_node(node.right)
                left_name = node.left.name if isinstance(node.left, Identifier) else str(node.left)
                right_name = node.right.name if isinstance(node.right, Identifier) else str(node.right)
                return {"type": "binop", "op": node.op, "left": left_name, "right": right_name,
                        "left_val": float(left_val) if hasattr(left_val,"__float__") else str(left_val),
                        "right_val": float(right_val) if hasattr(right_val,"__float__") else str(right_val),
                        "result": bool(left_val) if node.op.upper() in ("AND","OR") else bool(float(left_val))}
        if isinstance(node, Identifier):
            val = self._eval_node(node).iloc[-1]
            return {"type": "ident", "name": node.name, "value": float(val) if hasattr(val,"__float__") else str(val)}
        return {"type": "other", "str": str(node)}

    def evaluate_series(self, ast: Program) -> pd.Series:
        """
        执行完整的公式 AST，返回完整的信号 Series。
        用于调试和分析。
        """
        xg_result = None
        
        for stmt in ast.statements:
            if isinstance(stmt, AssignStmt):
                self._exec_assign(stmt)
            elif isinstance(stmt, XGStmt):
                xg_result = self._exec_xg(stmt)
            elif isinstance(stmt, ExprStmt):
                self._exec_expr(stmt)
        
        if xg_result is None:
            raise FormulaError("公式中未找到 XG 选股信号输出语句")
        
        return xg_result.fillna(False).astype(bool)
    
    def _exec_assign(self, stmt: AssignStmt):
        """执行赋值语句: VAR := EXPR"""
        name = stmt.name
        # 计算表达式值
        value = self._eval_node(stmt.value)
        
        # 存入 DataFrame（大写列名）
        col_name = name.upper()
        self.df[col_name] = value
    
    def _exec_xg(self, stmt: XGStmt) -> pd.Series:
        """执行选股信号输出: XG: EXPR"""
        return self._eval_node(stmt.expr)
    
    def _exec_expr(self, stmt: ExprStmt):
        """执行独立表达式（不存储结果）"""
        self._eval_node(stmt.expr)
    
    def _eval_node(self, node) -> pd.Series:
        """
        评估一个 AST 节点，返回 Series。
        使用 functions.py 中的评估逻辑，但扩展支持已存储的变量。
        """
        if isinstance(node, Number):
            return pd.Series(np.full(len(self.df), node.value), index=self.df.index)
        
        if isinstance(node, Identifier):
            name = node.name.upper()
            # 先检查字段别名
            if name in FIELD_ALIASES:
                field = FIELD_ALIASES[name]
                if field in self.df.columns:
                    return self.df[field]
            # 检查是否已存储在 DataFrame 中（变量或字段）
            if name in self.df.columns:
                return self.df[name]
            # 尝试小写
            if name.lower() in self.df.columns:
                return self.df[name.lower()]
            # 尝试解析为数字
            try:
                val = float(name)
                return pd.Series(np.full(len(self.df), val), index=self.df.index)
            except ValueError:
                pass
            raise FormulaError(f"未知变量/字段: {node.name}")
        
        if isinstance(node, BinOp):
            return self._eval_binop(node)
        
        if isinstance(node, UnaryOp):
            x = self._eval_node(node.operand)
            if node.op == '-':
                return -x
            raise FormulaError(f"未知一元运算符: {node.op}")
        
        if isinstance(node, FuncCall):
            return self._eval_funcall(node)
        
        raise FormulaError(f"无法评估的节点类型: {type(node)}")
    
    def _eval_binop(self, node: BinOp) -> pd.Series:
        """评估二元运算"""
        left = self._eval_node(node.left)
        right = self._eval_node(node.right)
        
        op = node.op
        if op == '+':
            return left + right
        elif op == '-':
            return left - right
        elif op == '*':
            return left * right
        elif op == '/':
            # 防止除零
            right_safe = right.replace(0, np.nan)
            return left / right_safe
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
        elif op.upper() == 'AND':
            return left & right
        elif op.upper() == 'OR':
            return left | right
        else:
            raise FormulaError(f"未知运算符: {op}")
    
    def _eval_funcall(self, node: FuncCall) -> pd.Series:
        """评估函数调用"""
        func = FunctionRegistry.get(node.name)
        if func is None:
            raise FormulaError(f"不支持的函数: {node.name}")
        
        # 将 AST 参数节点转换为函数可接受的参数
        # 函数接收 (df, args_list)，其中 args_list 中的元素是 AST 节点
        return func(self.df, node.args)
    
    def get_variable_names(self) -> list:
        """获取所有已计算变量的名称"""
        cols = [c for c in self.df.columns if c.isupper() and c not in FIELD_ALIASES]
        return cols
