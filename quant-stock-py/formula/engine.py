"""
选股引擎
封装完整的选股流程：板块筛选 → 个股筛选 → 结果输出

流程:
1. 读取板块选择公式 → 扫描所有板块指数 → 筛选候选板块
2. 读取候选板块的成分股 → 去重
3. 读取个股选择公式 → 扫描候选个股 → 筛选最终个股
4. 返回结果列表
"""
import os
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from config import (
    INDUSTRY_SELECT_FILE, STOCK_SELECT_FILE, OUTPUT_BLOCK_FILE,
    BACKUP_OUTPUT, MIN_DAYS
)
from data.reader import (
    read_stock_daily, scan_industry_indices, scan_all_stocks
)
from data.block_reader import (
    read_block_stocks, read_block_stocks_by_index,
    list_available_blocks, get_block_mapping
)
from formula.parser import parse_file as parse_formula_file
from formula.evaluator import Evaluator, FormulaError


class SelectionEngine:
    """
    选股引擎。
    
    用法:
        engine = SelectionEngine()
        result = engine.run()  # 执行完整选股流程
        # result = { 'matched_stocks': [...], 'total_industry': N, 'matched_industry': N, ... }
    """
    
    def __init__(self,
                 industry_formula_file: str = None,
                 stock_formula_file: str = None,
                 verbose: bool = True,
                 skip_industry: bool = False,
                 skip_stock: bool = False):
        self.industry_formula_file = industry_formula_file or INDUSTRY_SELECT_FILE
        self.stock_formula_file = stock_formula_file or STOCK_SELECT_FILE
        self.verbose = verbose
        self._skip_industry = skip_industry
        self._skip_stock = skip_stock
        self._industry_ast = None
        self._stock_ast = None
        self._load_formulas()
    
    def _log(self, msg: str, **kwargs):
        if self.verbose:
            print(msg, **kwargs)
    
    def _load_formulas(self):
        """加载并解析选股公式"""
        self._log("=" * 60)
        self._log("加载选股公式...")
        
        # 板块选择公式
        if os.path.isfile(self.industry_formula_file):
            self._log(f"  板块选择公式: {self.industry_formula_file}")
            self._industry_ast = parse_formula_file(self.industry_formula_file)
            stmt_count = len(self._industry_ast.statements)
            self._log(f"  解析完成: {stmt_count} 条语句")
        else:
            self._log(f"  [警告] 板块选择公式文件不存在: {self.industry_formula_file}")
        
        # 个股选择公式
        if os.path.isfile(self.stock_formula_file):
            self._log(f"  个股选择公式: {self.stock_formula_file}")
            self._stock_ast = parse_formula_file(self.stock_formula_file)
            stmt_count = len(self._stock_ast.statements)
            self._log(f"  解析完成: {stmt_count} 条语句")
        else:
            self._log(f"  [警告] 个股选择公式文件不存在: {self.stock_formula_file}")
        
        self._log("=" * 60)
    
    def run(self) -> Dict:
        """
        执行完整选股流程。
        
        Returns:
            { 
                'matched_stocks': ['600519', '000001', ...], 
                'total_industries': 300,
                'matched_industries': 15,
                'matched_industry_names': ['半导体', '银行', ...],
                'total_candidates': 500,
                'total_matched': 10,
                'duration': 12.5,
                'errors': []
            }
        """
        result = {
            'matched_stocks': [],
            'total_industries': 0,
            'matched_industries': 0,
            'matched_industry_names': [],
            'total_candidates': 0,
            'total_matched': 0,
            'duration': 0,
            'errors': [],
        }
        
        start_time = time.time()
        
        try:
            # Step 1: 板块筛选
            matched_industry_codes = []
            if self._skip_industry:
                self._log("\nStep 1: 板块筛选 [已跳过]")
                self._log("-" * 60)
            else:
                matched_industry_codes = self._filter_industries(result)
                
                if not matched_industry_codes:
                    self._log("\n没有符合条件的板块，选股结束。")
                    result["duration"] = time.time() - start_time
                    return result
            
            # Step 2: 获取候选个股
            if self._skip_industry:
                self._log("\nStep 2: 扫描全部个股（跳过板块筛选）")
                self._log("-" * 60)
                scan_results = scan_all_stocks()
                candidate_stocks = [s["code"] for s in scan_results if "code" in s]
                result["total_industries"] = 0
                result["matched_industries"] = 0
                result["total_candidates"] = len(candidate_stocks)
                self._log(f"  扫描到 {len(candidate_stocks)} 只个股")
            else:
                candidate_stocks = self._get_candidate_stocks(
                    matched_industry_codes, result
                )
            
            if not candidate_stocks:
                self._log("\n候选个股列表为空，选股结束。")
                result["duration"] = time.time() - start_time
                return result
            
            # Step 3: 个股筛选
            if self._skip_stock:
                matched_stocks = candidate_stocks
                self._log("\nStep 3: 个股筛选 [已跳过]")
                self._log(f"  全部 {len(matched_stocks)} 只候选个股作为结果")
            else:
                matched_stocks = self._filter_stocks(candidate_stocks, result)
            
            result["matched_stocks"] = matched_stocks
            result["total_matched"] = len(matched_stocks)
            
        except Exception as e:
            error_msg = f"选股过程出错: {e}"
            self._log(f"\n[错误] {error_msg}")
            result['errors'].append(error_msg)
        
        result['duration'] = round(time.time() - start_time, 2)
        return result
    
    def _filter_industries(self, result: Dict) -> List[str]:
        """
        Step 1: 板块筛选。
        扫描所有板块指数，执行板块选择公式，返回符合条件的板块指数代码列表。
        """
        self._log("\n" + "=" * 60)
        self._log("Step 1: 板块筛选")
        self._log("-" * 60)
        
        if self._industry_ast is None:
            self._log("  [跳过] 未加载板块选择公式")
            return []
        
        # 扫描所有板块指数
        indices = scan_industry_indices()
        result['total_industries'] = len(indices)
        self._log(f"  扫描到 {len(indices)} 个板块指数")
        
        matched_codes = []
        matched_names = []
        
        for i, idx_info in enumerate(indices):
            code = idx_info['code']
            self._log(f"  [{i+1}/{len(indices)}] 检查板块指数 {code}...", end='')
            
            try:
                # 读取板块指数日线数据
                df = read_stock_daily(code)
                if df is None or len(df) < MIN_DAYS:
                    self._log(f" 数据不足，跳过")
                    continue
                
                # 执行板块选择公式
                evaluator = Evaluator(df)
                matched = evaluator.evaluate(self._industry_ast)
                
                if matched:
                    matched_codes.append(code)
                    self._log(f" ✓ 符合条件")
                else:
                    self._log(f" ✗")
            
            except Exception as e:
                self._log(f"  [错误] {e}")
                result['errors'].append(f"板块 {code}: {e}")
        
        # 尝试获取板块名称映射
        # 注：通达信板块指数名称需要通过 .dat 文件解析
        result['matched_industries'] = len(matched_codes)
        result['matched_industry_names'] = matched_names
        result['matched_industry_codes'] = matched_codes
        
        self._log(f"\n  符合条件的板块: {len(matched_codes)} / {len(indices)}")
        for code in matched_codes:
            self._log(f"    - {code}")
        
        return matched_codes
    
    def _get_candidate_stocks(self,
                              industry_codes: List[str],
                              result: Dict) -> List[str]:
        """
        Step 2: 收集候选个股。
        从符合条件的板块中读取所有成分股，去重。
        同时构建 股票→所属板块指数 的映射，供后续详情报告使用。
        如果无法从板块文件获取成分股，则回退到扫描全部个股。
        """
        all_stocks = set()
        stock_industry_map = {}  # stock_code -> [industry_code1, industry_code2, ...]
        industry_stock_counts = {}  # industry_code -> 成分股数（用于板块汇总）

        for code in industry_codes:
            stocks = read_block_stocks_by_index(code)
            if stocks is None:
                self._log(f"  {code}: 未找到成分股信息，跳过")
                industry_stock_counts[code] = 0
                continue

            self._log(f"  {code}: {len(stocks)} 只成分股")
            industry_stock_counts[code] = len(stocks)
            for stock in stocks:
                stock_industry_map.setdefault(stock, []).append(code)
            all_stocks.update(stocks)
        
        # 兜底: 如果无法从板块文件获取任何成分股，回退到扫描所有个股
        if len(all_stocks) == 0:
            self._log("  [兜底] 从板块文件无法获取成分股，改为扫描全部个股...")
            all_stocks_list = scan_all_stocks()
            all_stocks.update(s["code"] for s in all_stocks_list if "code" in s)
            all_stocks.update(s["code"] for s in all_stocks_list if "code" in s)
        
        result["total_candidates"] = len(all_stocks)
        result["stock_industry_map"] = stock_industry_map
        result["industry_stock_counts"] = industry_stock_counts
        self._log(f"\n  去重后候选个股: {len(all_stocks)} 只")
        return sorted(all_stocks)
    def _filter_stocks(self,
                       candidate_stocks: List[str],
                       result: Dict) -> List[str]:
        """
        Step 3: 个股筛选。
        遍历所有候选个股，执行个股选择公式，返回符合条件的个股代码列表。
        """
        self._log("\n" + "=" * 60)
        self._log("Step 3: 个股筛选")
        self._log("-" * 60)
        
        if self._stock_ast is None:
            self._log("  [跳过] 未加载个股选择公式")
            return []

        matched_stocks = []
        total = len(candidate_stocks)

        # 条件诊断：在整个候选池上统计每个子条件的通过数，定位“卡掉最多股票”的瓶颈
        cond_pass = {}      # label -> 通过数
        cond_order = []     # 保持公式中的条件顺序
        evaluated = 0

        for i, code in enumerate(candidate_stocks):
            self._log(f"  [{i+1}/{total}] {code}...", end='')

            try:
                df = read_stock_daily(code)
                if df is None or len(df) < MIN_DAYS:
                    self._log(f" 数据不足，跳过")
                    continue

                evaluator = Evaluator(df)
                info = evaluator.evaluate_full(self._stock_ast)
                evaluated += 1

                for label, ok in info["conditions"]:
                    if label not in cond_pass:
                        cond_pass[label] = 0
                        cond_order.append(label)
                    if ok:
                        cond_pass[label] += 1

                if info["result"]:
                    matched_stocks.append(code)
                    industry_codes = result.get("stock_industry_map", {}).get(code, [])
                    result.setdefault("stock_details", []).append({
                        "code": code,
                        "variables": info["variables"],
                        "price": info["price"],
                        "conditions": info["conditions"],
                        "industry_codes": industry_codes,
                    })
                    self._log(f" ✓ 符合条件")
                else:
                    self._log(f" ✗")

            except Exception as e:
                self._log(f"  [错误] {e}")
                result['errors'].append(f"个股 {code}: {e}")

        result["condition_diag"] = {
            "evaluated": evaluated,
            "rows": [(label, cond_pass[label]) for label in cond_order],
        }

        self._log(f"\n  符合条件的个股: {len(matched_stocks)} / {total}")
        for code in matched_stocks:
            self._log(f"    - {code}")

        return matched_stocks

