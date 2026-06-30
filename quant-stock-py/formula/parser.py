"""
通达信选股公式语法分析器 (Parser)

将 Token 流转换为 AST（抽象语法树），支持：
- 赋值语句: VAR := EXPR;
- 选股信号: XG: EXPR;
- 函数调用: MA(CLOSE, 5)
- 二元运算: + - * / > < >= <= = AND OR
- 数字和变量引用
- 注释跳过（已在 Tokenizer 中完成）

AST 节点类型:
- Program: 根节点，包含语句列表
- AssignStmt: 赋值语句 (name, value)
- XGStmt: 选股信号输出 (expr)
- BinOp: 二元运算 (left, op, right)
- UnaryOp: 一元运算 (op, operand)
- FuncCall: 函数调用 (name, args)
- Number: 数字常量
- Identifier: 变量引用
"""
from enum import Enum, auto
from typing import List, Optional, Any, Union

from formula.tokenizer import Token, TokenType, Tokenizer, TokenizerError, tokenize


# ============== AST 节点类型 ==============

class ASTNode:
    """AST 基节点"""
    pass


class Program(ASTNode):
    """程序根节点，包含语句列表"""
    def __init__(self, statements: List[ASTNode]):
        self.statements = statements
    
    def __repr__(self):
        return f'Program({len(self.statements)} stmts)'


class AssignStmt(ASTNode):
    """赋值语句: VAR := EXPR"""
    def __init__(self, name: str, value: ASTNode):
        self.name = name
        self.value = value
    
    def __repr__(self):
        return f'Assign({self.name}, {self.value})'


class XGStmt(ASTNode):
    """选股信号输出: XG: EXPR"""
    def __init__(self, expr: ASTNode):
        self.expr = expr
    
    def __repr__(self):
        return f'XG({self.expr})'


class ExprStmt(ASTNode):
    """表达式语句（独立表达式，非赋值）"""
    def __init__(self, expr: ASTNode):
        self.expr = expr
    
    def __repr__(self):
        return f'ExprStmt({self.expr})'


class BinOp(ASTNode):
    """二元运算: left op right"""
    def __init__(self, left: ASTNode, op: str, right: ASTNode):
        self.left = left
        self.op = op
        self.right = right
    
    def __repr__(self):
        return f'BinOp({self.left} {self.op} {self.right})'


class UnaryOp(ASTNode):
    """一元运算: op operand"""
    def __init__(self, op: str, operand: ASTNode):
        self.op = op
        self.operand = operand
    
    def __repr__(self):
        return f'UnaryOp({self.op} {self.operand})'


class FuncCall(ASTNode):
    """函数调用: NAME(ARG1, ARG2, ...)"""
    def __init__(self, name: str, args: List[ASTNode]):
        self.name = name.upper()  # 函数名统一大写
        self.args = args
    
    def __repr__(self):
        return f'Func({self.name}, {self.args})'


class Number(ASTNode):
    """数字常量"""
    def __init__(self, value: float):
        self.value = value
    
    def __repr__(self):
        return f'Num({self.value})'


class Identifier(ASTNode):
    """变量/字段引用"""
    def __init__(self, name: str):
        self.name = name
    
    def __repr__(self):
        return f'Ident({self.name})'


# ============== 解析器 ==============

class ParseError(Exception):
    """语法分析错误"""
    pass


class Parser:
    """
    通达信公式语法分析器。
    使用递归下降解析。

    支持运算符优先级（从低到高）：
    1. AND, OR
    2. 比较: > < >= <= = <>
    3. 加减: + -
    4. 乘除: * /
    5. 一元: -
    6. 函数调用、括号
    """
    
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self._pos = 0
    
    def parse(self) -> Program:
        """解析整个程序，返回 AST。"""
        statements = []
        while self._peek().type != TokenType.EOF:
            stmt = self._parse_statement()
            if stmt is not None:
                statements.append(stmt)
        return Program(statements)
    
    def _parse_statement(self) -> Optional[ASTNode]:
        """
        解析一条语句。
        可能的语句类型：
        - VAR := EXPR ;       (赋值)
        - XG : EXPR ;         (选股信号)
        - EXPR ;              (独立表达式)
        """
        token = self._peek()
        
        # 跳过行末可能导致问题的分号
        if token.type == TokenType.SEMICOLON:
            self._consume()
            return None
        
        # 检测是否是赋值语句：先读取一个标识符，后面如果是 := 则是赋值
        if token.type == TokenType.IDENTIFIER:
            # 向前看两个 token
            if (self._pos + 1 < len(self.tokens) and
                self.tokens[self._pos + 1].type == TokenType.ASSIGN):
                # 赋值语句
                name = self._consume().value
                self._consume()  # :=
                value = self._parse_expr()
                self._expect_semicolon_or_end()
                return AssignStmt(name, value)
        
        # 检测 XG 选股信号
        if token.type == TokenType.XG:
            self._consume()  # XG
            # 后面可能是 : 或 :=
            next_tok = self._peek()
            if next_tok.type in (TokenType.COLON, TokenType.ASSIGN, TokenType.EQ):
                self._consume()  # : 或 := 或 =
            expr = self._parse_expr()
            self._expect_semicolon_or_end()
            return XGStmt(expr)
        
        # 普通表达式语句
        expr = self._parse_expr()
        self._expect_semicolon_or_end()
        return ExprStmt(expr)
    
    def _parse_expr(self) -> ASTNode:
        """表达式入口：处理 AND / OR"""
        left = self._parse_comparison()
        
        while self._peek().type in (TokenType.AND, TokenType.OR):
            op = self._consume().value
            right = self._parse_comparison()
            left = BinOp(left, op.upper(), right)
        
        return left
    
    def _parse_comparison(self) -> ASTNode:
        """处理比较运算符: > < >= <= = <>"""
        left = self._parse_addition()
        
        while self._peek().type in (
            TokenType.GT, TokenType.LT, TokenType.GE,
            TokenType.LE, TokenType.EQ, TokenType.NEQ
        ):
            op = self._consume().value
            right = self._parse_addition()
            left = BinOp(left, op, right)
        
        return left
    
    def _parse_addition(self) -> ASTNode:
        """处理加减: + -"""
        left = self._parse_term()
        
        while self._peek().type in (TokenType.PLUS, TokenType.MINUS):
            op = self._consume().value
            right = self._parse_term()
            left = BinOp(left, op, right)
        
        return left
    
    def _parse_term(self) -> ASTNode:
        """处理乘除: * /"""
        left = self._parse_unary()
        
        while self._peek().type in (TokenType.MUL, TokenType.DIV):
            op = self._consume().value
            right = self._parse_unary()
            left = BinOp(left, op, right)
        
        return left
    
    def _parse_unary(self) -> ASTNode:
        """处理一元运算: -"""
        if self._peek().type == TokenType.MINUS:
            op = self._consume().value
            operand = self._parse_primary()
            return UnaryOp(op, operand)
        return self._parse_primary()
    
    def _parse_primary(self) -> ASTNode:
        """处理基本元素: 数字、标识符、函数调用、括号表达式"""
        token = self._peek()
        
        if token.type == TokenType.NUMBER:
            self._consume()
            return Number(float(token.value))
        
        if token.type == TokenType.IDENTIFIER:
            name = self._consume().value
            # 如果后面是 ( 则是函数调用
            if self._peek().type == TokenType.LPAREN:
                return self._parse_func_call(name)
            # 否则是变量引用
            return Identifier(name)
        
        if token.type == TokenType.LPAREN:
            self._consume()  # (
            expr = self._parse_expr()
            if self._peek().type != TokenType.RPAREN:
                raise ParseError(
                    f"缺少右括号在 {self._peek().line}:{self._peek().col}"
                )
            self._consume()  # )
            return expr
        
        # C 是 CLOSE 的简写，V 是 VOL 的简写
        if token.type == TokenType.XG:
            # XG 在表达式上下文也可作为标识符
            name = self._consume().value
            return Identifier(name)
        
        raise ParseError(
            f"意外的token {token.value!r} 在 {token.line}:{token.col}"
        )
    
    def _parse_func_call(self, name: str) -> FuncCall:
        """解析函数调用: NAME(ARG1, ARG2, ...)"""
        self._consume()  # (
        args = []
        
        while self._peek().type != TokenType.RPAREN:
            if args:
                if self._peek().type != TokenType.COMMA:
                    raise ParseError(
                        f"函数 {name} 参数间缺少逗号"
                    )
                self._consume()  # ,
            
            arg = self._parse_expr()
            args.append(arg)
        
        if self._peek().type != TokenType.RPAREN:
            raise ParseError(f"函数 {name} 缺少右括号")
        self._consume()  # )
        
        return FuncCall(name, args)
    
    def _peek(self) -> Token:
        """查看当前 Token"""
        if self._pos >= len(self.tokens):
            return Token(TokenType.EOF, '', 0, 0)
        return self.tokens[self._pos]
    
    def _consume(self) -> Token:
        """消费当前 Token 并返回"""
        token = self._peek()
        self._pos += 1
        return token
    
    def _expect_semicolon_or_end(self):
        """期望分号或文件结束"""
        if self._peek().type == TokenType.SEMICOLON:
            self._consume()
        elif self._peek().type != TokenType.EOF:
            # 允许没有分号的换行终止
            pass


# ============== 便捷函数 ==============

def parse(text: str) -> Program:
    """便捷函数：直接解析公式文本。"""
    tokens = tokenize(text)
    parser = Parser(tokens)
    return parser.parse()


def parse_file(filepath: str) -> Program:
    """便捷函数：从文件读取并解析公式。"""
    from formula.tokenizer import tokenize_file
    tokens = tokenize_file(filepath)
    parser = Parser(tokens)
    return parser.parse()


# ============== 测试 ==============

if __name__ == '__main__':
    test = """
    M1:=14;
    M2:=28;
    知行短期趋势线:=EMA(EMA(C,10),10);
    知行多空线:=(MA(CLOSE,M1)+MA(CLOSE,M2))/4;
    白线在黄线上:=知行短期趋势线 > 知行多空线;
    XG: 白线在黄线上 AND C1;
    """
    
    ast = parse(test)
    print(ast)
    for stmt in ast.statements:
        print(f'  {stmt}')

