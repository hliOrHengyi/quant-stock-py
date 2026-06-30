"""测试词法分析和语法分析"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from formula.tokenizer import tokenize, tokenize_file
from formula.parser import parse, parse_file

# 测试简单的公式
test1 = "M1:=14; M2:=28;"
print("=" * 60)
print("测试1: 基础公式")
print("-" * 60)
tokens = tokenize(test1)
for t in tokens:
    print(f"  {t}")

ast = parse(test1)
print(f"\nAST: {ast}")
for stmt in ast.statements:
    print(f"  {stmt}")

# 测试个股选股公式文件
print("\n" + "=" * 60)
print("测试2: 个股选股公式")
print("-" * 60)
try:
    tokens = tokenize_file('个股选股.txt')
    print(f"Token 数量: {len(tokens)}")
    for t in tokens[:30]:
        print(f"  {t}")
    if len(tokens) > 30:
        print(f"  ... (共 {len(tokens)} 个 token)")

    ast = parse_file('个股选股.txt')
    print(f"\nAST: {ast}")
    for stmt in ast.statements:
        print(f"  {stmt}")
except Exception as e:
    print(f"[错误] {e}")
    import traceback
    traceback.print_exc()

# 测试板块选择公式文件
print("\n" + "=" * 60)
print("测试3: 板块选择公式")
print("-" * 60)
try:
    tokens = tokenize_file('板块选择.txt')
    print(f"Token 数量: {len(tokens)}")
    for t in tokens[:20]:
        print(f"  {t}")

    ast = parse_file('板块选择.txt')
    print(f"\nAST: {ast}")
    for stmt in ast.statements:
        print(f"  {stmt}")
except Exception as e:
    print(f"[错误] {e}")
    import traceback
    traceback.print_exc()