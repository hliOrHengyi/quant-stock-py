"""
通达信选股公式词法分析器 (Tokenizer)

将通达信公式文本拆分为 Token 流，支持：
- 关键字: AND, OR, XG
- 标识符: 变量名、函数名（支持中文、数字、字母、下划线）
- 数字: 整数、浮点数
- 运算符: + - * / > < >= <= = :=
- 分隔符: ( ) , ; :
- 注释: { ... } (通达信花括号注释)
"""
import re
from enum import Enum, auto
from typing import List, Optional, Tuple


class TokenType(Enum):
    # 关键字
    AND = auto()
    OR = auto()
    XG = auto()       # 选股信号输出标记
    TO = auto()       # 范围运算符 (用于 RANGE 等)
    
    # 标识符
    IDENTIFIER = auto()   # 变量名/函数名
    
    # 数字
    NUMBER = auto()       # 整数或浮点数
    
    # 字符串
    STRING = auto()
    
    # 赋值运算符
    ASSIGN = auto()       # :=
    COLON = auto()        # :
    
    # 算术运算符
    PLUS = auto()         # +
    MINUS = auto()        # -
    MUL = auto()          # *
    DIV = auto()          # /
    
    # 比较运算符
    GT = auto()           # >
    LT = auto()           # <
    GE = auto()           # >=
    LE = auto()           # <=
    EQ = auto()           # =
    NEQ = auto()          # != (通达信中也用 <>)
    
    # 逻辑运算符 (文本形式)
    # AND / OR 作为关键字处理
    
    # 分隔符
    LPAREN = auto()       # (
    RPAREN = auto()       # )
    COMMA = auto()        # ,
    SEMICOLON = auto()    # ;
    
    # 特殊
    EOF = auto()          # 文件结束
    COMMENT = auto()      # 注释（被跳过）
    
    # 函数参数特殊标记
    DOT = auto()          # .


class Token:
    def __init__(self, type_: TokenType, value: str, line: int, col: int):
        self.type = type_
        self.value = value
        self.line = line
        self.col = col
    
    def __repr__(self):
        return f'Token({self.type.name}, {self.value!r}, L{self.line}:{self.col})'


# 正则模式：按优先级排列
TOKEN_PATTERNS = [
    # 注释 { ... }
    (r'\{[^}]*\}', 'COMMENT_SKIP'),
    
    # 赋值 :=
    (r':=', 'ASSIGN'),
    
    # 逻辑关键字 (大小写不敏感)
    (r'\bAND\b', 'AND', re.IGNORECASE),
    (r'\bOR\b', 'OR', re.IGNORECASE),
    (r'\bXG\b', 'XG', re.IGNORECASE),
    (r'\bTO\b', 'TO', re.IGNORECASE),
    
    # 比较运算符（先匹配双字符的）
    (r'>=', 'GE'),
    (r'<=', 'LE'),
    (r'<>', 'NEQ'),
    (r'!=', 'NEQ'),
    (r'=', 'EQ'),
    (r'>', 'GT'),
    (r'<', 'LT'),
    
    # 算术运算符
    (r'\+', 'PLUS'),
    (r'-', 'MINUS'),
    (r'\*', 'MUL'),
    (r'/', 'DIV'),
    
    # 分隔符
    (r'\(', 'LPAREN'),
    (r'\)', 'RPAREN'),
    (r',', 'COMMA'),
    (r';', 'SEMICOLON'),
    (r':', 'COLON'),
    (r'\.', 'DOT'),
    
    # 数字（整数和浮点数）
    (r'\d+\.?\d*', 'NUMBER'),
    
    # 标识符：中文、字母、数字、下划线，不以数字开头
    (r'[_\w\u4e00-\u9fff][\w\u4e00-\u9fff]*', 'IDENTIFIER'),
]


class TokenizerError(Exception):
    """词法分析错误"""
    pass


class Tokenizer:
    """
    通达信公式词法分析器。
    
    用法:
        tokenizer = Tokenizer("MA5:=MA(CLOSE,5);")
        for token in tokenizer.tokenize():
            print(token)
    """
    
    def __init__(self, text: str):
        self.text = text
        self.tokens: List[Token] = []
        self._pos = 0
        self._line = 1
        self._col = 1
    
    def tokenize(self) -> List[Token]:
        """执行词法分析，返回 Token 列表。"""
        self.tokens = []
        self._pos = 0
        self._line = 1
        self._col = 1
        
        while self._pos < len(self.text):
            # 跳过空白符和换行
            char = self.text[self._pos]
            if char in ' \t\r':
                self._pos += 1
                self._col += 1
                continue
            if char == '\n':
                self._pos += 1
                self._line += 1
                self._col = 1
                continue
            
            # 尝试匹配所有模式
            matched = False
            for pattern_info in TOKEN_PATTERNS:
                if len(pattern_info) == 2:
                    pattern, token_type_name = pattern_info
                    flags = 0
                else:
                    pattern, token_type_name, flags = pattern_info
                
                regex = re.compile(pattern, flags)
                m = regex.match(self.text, self._pos)
                if m:
                    matched = True
                    value = m.group(0)
                    
                    if token_type_name == 'COMMENT_SKIP':
                        # 跳过注释
                        self._pos = m.end()
                        # 更新行/列位置
                        self._update_pos(value)
                        break
                    
                    # 创建 Token
                    token_type = TokenType[token_type_name]
                    token = Token(token_type, value, self._line, self._col)
                    self.tokens.append(token)
                    
                    self._pos = m.end()
                    self._update_pos(value)
                    break
            
            if not matched:
                raise TokenizerError(
                    f"无法识别的字符 {char!r} 在 {self._line}:{self._col}"
                )
        
        # 添加 EOF
        self.tokens.append(Token(TokenType.EOF, '', self._line, self._col))
        return self.tokens
    
    def _update_pos(self, text: str):
        """更新行列位置"""
        for ch in text:
            if ch == '\n':
                self._line += 1
                self._col = 1
            else:
                self._col += 1


# ============== 便捷函数 ==============

def tokenize(text: str) -> List[Token]:
    """便捷函数：直接对公式文本进行词法分析。"""
    t = Tokenizer(text)
    return t.tokenize()


def tokenize_file(filepath: str) -> List[Token]:
    """便捷函数：从文件读取公式并进行词法分析。"""
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
    return tokenize(text)


# ============== 测试 ==============

if __name__ == '__main__':
    # 测试你的个股选股公式
    test_formula = """
    M1:=14;
    M2:=28;
    知行短期趋势线:=EMA(EMA(C,10),10);
    知行多空线:=(MA(CLOSE,M1)+MA(CLOSE,M2)+MA(CLOSE,M3)+MA(CLOSE,M4))/4;
    白线在黄线上:=知行短期趋势线 > 知行多空线;
    XG: 昨天绿柱 AND 今天红柱 AND 高度达标;
    """
    
    tokens = tokenize(test_formula)
    for tok in tokens:
        print(tok)
