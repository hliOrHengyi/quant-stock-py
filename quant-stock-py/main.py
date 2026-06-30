#!/usr/bin/env python
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
# -*- coding: utf-8 -*-
"""
通达信自定义选股系统 — 命令行入口

用法:
    python main.py                      # 执行完整选股流程
    python main.py --no-industry         # 跳过板块筛选，直接运行个股筛选
    python main.py --no-stock            # 只做板块筛选
    python main.py --list-stocks         # 只列出候选个股
    python main.py --test-stock 600519   # 测试单只股票是否满足个股条件
    python main.py --test-industry 881319 # 测试单个板块指数是否满足板块条件
    python main.py --verbose             # 详细输出模式
"""
import argparse
import os
import sys

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    INDUSTRY_SELECT_FILE, STOCK_SELECT_FILE, OUTPUT_BLOCK_FILE
)
from formula.parser import parse_file as parse_formula_file
from formula.evaluator import Evaluator, FormulaError
from data.reader import (
    read_stock_daily, scan_industry_indices
)
from formula.engine import SelectionEngine
from output.exporter import export_to_blk, export_summary, export_industry_blk, export_detailed_result


def parse_args():
    parser = argparse.ArgumentParser(
        description='通达信自定义选股系统 — 基于通达信本地数据的 Python 选股工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                    # 执行完整选股流程
  python main.py --list-industries  # 列出所有板块指数
  python main.py --test-stock 600519  # 测试单只股票
        """
    )

    parser.add_argument(
        '--industry-formula', '-if',
        default=INDUSTRY_SELECT_FILE,
        help=f'板块选择公式文件路径 (默认: {INDUSTRY_SELECT_FILE})'
    )
    parser.add_argument(
        '--stock-formula', '-sf',
        default=STOCK_SELECT_FILE,
        help=f'个股选择公式文件路径 (默认: {STOCK_SELECT_FILE})'
    )
    parser.add_argument(
        '--output', '-o',
        default=None,
        help=f'输出 .blk 文件路径 (默认: {OUTPUT_BLOCK_FILE})'
    )
    parser.add_argument(
        '--no-industry', action='store_true',
        help='跳过板块筛选，直接运行个股筛选（对全市场个股执行个股公式）'
    )
    parser.add_argument(
        '--no-stock', action='store_true',
        help='只做板块筛选，不执行个股筛选'
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true', default=True,
        help='详细输出模式 (默认开启)'
    )
    parser.add_argument(
        '--quiet', '-q', action='store_true',
        help='静默模式，仅输出最终结果'
    )
    parser.add_argument(
        '--list-industries', action='store_true',
        help='列出所有板块指数'
    )
    parser.add_argument(
        '--test-industry', type=str, metavar='CODE',
        help='测试单个板块指数代码是否满足板块条件，如 881319'
    )
    parser.add_argument(
        '--test-stock', type=str, metavar='CODE',
        help='测试单只股票代码是否满足个股条件，如 600519'
    )
    parser.add_argument(
        '--no-export', action='store_true',
        help='不导出 .blk 文件'
    )
    parser.add_argument(
        '--no-report', action='store_true',
        help='不导出选股报告'
    )

    return parser.parse_args()


def list_industries():
    """列出所有板块指数"""
    print("=" * 60)
    print("通达信板块指数列表")
    print("=" * 60)
    
    indices = scan_industry_indices()
    if not indices:
        print("未找到板块指数数据。请确认通达信数据目录是否正确。")
        return
    
    print(f"共 {len(indices)} 个板块指数:")
    print("-" * 60)
    for i, idx in enumerate(indices, 1):
        print(f"  {i:3d}. {idx['code']} ({idx['exchange']})")


def test_single_industry(code: str, formula_file: str, verbose: bool):
    """测试单个板块指数"""
    if not os.path.isfile(formula_file):
        print(f"[错误] 板块公式文件不存在: {formula_file}")
        return
    
    ast = parse_formula_file(formula_file)
    print(f"公式解析完成: {len(ast.statements)} 条语句")
    
    df = read_stock_daily(code)
    if df is None:
        print(f"[结果] 板块指数 {code}: 数据不存在")
        return
    
    print(f"数据: {len(df)} 条日线记录 ({df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()})")
    
    evaluator = Evaluator(df)
    result = evaluator.evaluate(ast)
    
    print(f"[结果] 板块指数 {code}: {'[OK] 符合条件' if result else '[NO] 不符合条件'}")


def test_single_stock(code: str, formula_file: str, verbose: bool):
    """测试单只个股"""
    if not os.path.isfile(formula_file):
        print(f"[错误] 个股公式文件不存在: {formula_file}")
        return
    
    ast = parse_formula_file(formula_file)
    print(f"公式解析完成: {len(ast.statements)} 条语句")
    
    df = read_stock_daily(code)
    if df is None:
        print(f"[结果] 股票 {code}: 数据不存在")
        return
    
    print(f"数据: {len(df)} 条日线记录 ({df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()})")
    
    evaluator = Evaluator(df)
    result = evaluator.evaluate(ast)
    
    print(f"[结果] 股票 {code}: {'[OK] 符合条件' if result else '[NO] 不符合条件'}")


def main():
    args = parse_args()
    
    verbose = args.verbose or not args.quiet
    
    # 特殊模式：列出板块指数
    if args.list_industries:
        list_industries()
        return
    
    # 特殊模式：测试单个板块指数
    if args.test_industry:
        test_single_industry(args.test_industry, args.industry_formula, verbose)
        return
    
    # 特殊模式：测试单只股票
    if args.test_stock:
        test_single_stock(args.test_stock, args.stock_formula, verbose)
        return
    
    # 正常选股模式
    print("=" * 60)
    print("  通达信自定义选股系统")
    print("=" * 60)
    print()
    
    if args.no_industry and args.no_stock:
        print("[错误] --no-industry 和 --no-stock 不能同时使用")
        sys.exit(1)
    
    # 创建引擎
    engine = SelectionEngine(
        industry_formula_file=args.industry_formula,
        stock_formula_file=args.stock_formula,
        verbose=verbose,
        skip_industry=args.no_industry,
        skip_stock=args.no_stock,
    )
    # 运行选股
    result = engine.run()
    
    # 输出结果
    print()
    print("=" * 60)
    print("选股完成")
    print("=" * 60)
    print(f"  板块指数:   {result['total_industries']} 个")
    print(f"  符合板块:   {result['matched_industries']} 个")
    print(f"  候选个股:   {result['total_candidates']} 只")
    print(f"  最终入选:   {result['total_matched']} 只")
    print(f"  耗时:       {result['duration']} 秒")
    
    if result['errors']:
        print(f"  错误数:     {len(result['errors'])}")
        for err in result['errors'][:5]:
            print(f"    - {err}")
        if len(result['errors']) > 5:
            print(f"    ... (共 {len(result['errors'])} 个错误)")
    
    # 导出
    if result['matched_stocks'] and not args.no_export:
        export_to_blk(result['matched_stocks'], args.output)
    if result.get('matched_industry_codes') and len(result['matched_industry_codes']) > 0 and not args.no_export:
        export_industry_blk(result['matched_industry_codes'])

    if not args.no_report:
        export_summary(result)
        export_detailed_result(result)

    print()
    print("提示：请将生成的 日期选股.blk 文件手动复制到通达信")
    print("      T0002\\blocknew 目录下，即可在通达信中查看选股结果。")
    print()


if __name__ == '__main__':
    main()
