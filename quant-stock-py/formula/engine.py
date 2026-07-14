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
import multiprocessing as mp
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

import config
from config import (
    INDUSTRY_SELECT_FILE, STOCK_RESEARCH_DIR, OUTPUT_BLOCK_FILE,
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


# ============== 多进程个股筛选 worker ==============
# 设计（遵循“重输入建一次、fork 写时复制共享”）：
#   父进程先把全市场面板建好（tushare）；fork 出的子进程继承该面板（CoW，不重建/不pickle）。
#   每个子进程对分到的股票跑公式，返回结论+逐条件拆解+指标快照，父进程汇总。

_WORKER_AST = None


def _init_stock_worker(ast, data_source):
    """子进程初始化：缓存公式 AST，并固定数据源（兼容 fork/spawn）。"""
    global _WORKER_AST
    _WORKER_AST = ast
    config.DATA_SOURCE = data_source


def _eval_one_stock_with(code, ast):
    """对单只股票执行个股公式，返回 (code, info|None)。info 见 Evaluator.evaluate_full。"""
    try:
        df = read_stock_daily(code)
        if df is None or len(df) < MIN_DAYS:
            return (code, None)
        return (code, Evaluator(df).evaluate_full(ast))
    except Exception as e:  # 单股异常不影响整体
        return (code, {"error": str(e)})


def _eval_one_stock(code):
    """多进程 worker 入口：用子进程缓存的 AST 执行。"""
    return _eval_one_stock_with(code, _WORKER_AST)


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
                 stock_formula_dir: str = None,
                 verbose: bool = True,
                 skip_industry: bool = False,
                 skip_stock: bool = False,
                 jobs: int = None):
        self.industry_formula_file = industry_formula_file or INDUSTRY_SELECT_FILE
        self.stock_formula_dir = stock_formula_dir or STOCK_RESEARCH_DIR
        self.verbose = verbose
        self._skip_industry = skip_industry
        self._skip_stock = skip_stock
        self._jobs = jobs          # None=自动(cpu-2); 1=串行
        self._industry_ast = None
        self._stock_asts = []      # [(name, ast), ...]
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
        
        # 个股选择公式（目录下所有 .txt 文件，每个作为独立公式）
        self._stock_asts = []
        if os.path.isdir(self.stock_formula_dir):
            formula_files = sorted([
                f for f in os.listdir(self.stock_formula_dir)
                if f.endswith(".txt")
            ])
            for fname in formula_files:
                fpath = os.path.join(self.stock_formula_dir, fname)
                name = fname.replace(".txt", "")
                self._log(f"  个股选择公式: {fpath}")
                ast = parse_formula_file(fpath)
                stmt_count = len(ast.statements)
                self._log(f"    -> [{name}] 解析完成: {stmt_count} 条语句")
                self._stock_asts.append((name, ast))
            if not self._stock_asts:
                self._log(f"  [警告] 个股公式目录为空: {self.stock_formula_dir}")
        else:
            self._log(f"  [警告] 个股公式目录不存在: {self.stock_formula_dir}")
        
        self._log("=" * 60)

    def _load_preferred_blocks(self) -> List[str]:
        """
        Load preferred blocks from hliPreferredBlock.txt.
        These blocks are force-added to results regardless of formula.
        """
        pref_file = os.path.join(
            os.path.dirname(self.industry_formula_file),
            "hliPreferredBlock.txt"
        )
        if not os.path.isfile(pref_file):
            return []

        codes = []
        with open(pref_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("{") or line.startswith("#"):
                    continue
                code = ""
                for ch in line:
                    if ch.isdigit():
                        code += ch
                    elif code:
                        break
                if len(code) == 6 and not code.startswith("0"):
                    codes.append(code)

        if codes:
            self._log(f"  个人首选板块: {', '.join(codes)}")
        return codes

    def run(self) -> Dict:
        """
        执行完整选股流程。
        先板块筛选（一个公式），再对每个个股公式分别执行筛选。
        
        Returns:
            {
                'summary': {
                    'total_industries': int,
                    'matched_industries': int,
                    'matched_industry_codes': [...],
                    'total_candidates': int,
                    'duration': float,
                    'errors': [...],
                },
                'formulas': {
                    '公式名1': {
                        'matched_stocks': [...],
                        'total_matched': int,
                        'stock_details': [...],
                        'condition_diag': {...},
                    },
                    '公式名2': {...},
                }
            }
        """
        result = {
            'formulas': {},
            'summary': {
                'total_industries': 0,
                'matched_industries': 0,
                'matched_industry_codes': [],
                'total_candidates': 0,
                'duration': 0,
                'errors': [],
            },
        }
        
        start_time = time.time()
        
        try:
            # Step 1: 板块筛选
            matched_industry_codes = []
            if self._skip_industry:
                self._log("\nStep 1: 板块筛选 [已跳过]")
                self._log("-" * 60)
            else:
                matched_industry_codes = self._filter_industries(result['summary'])
                
                # 合并个人长期看好板块（不论公式是否选中，强制加入）
                preferred = self._load_preferred_blocks()
                if preferred:
                    added = 0
                    for code in preferred:
                        if code not in matched_industry_codes:
                            matched_industry_codes.append(code)
                            added += 1
                    if added:
                        self._log(f"\n  [首选板块] 强制加入 {added} 个个人板块: {', '.join(preferred)}")
                    result["summary"]["preferred_blocks"] = preferred
                    result["summary"]["matched_industries"] = len(matched_industry_codes)
                
                if not matched_industry_codes:
                    self._log("\n没有符合条件的板块，选股结束。")
                    result['summary']['duration'] = round(time.time() - start_time, 2)
                    return result
            
            # Step 2: 获取候选个股
            if self._skip_industry:
                self._log("\nStep 2: 扫描全部个股（跳过板块筛选）")
                self._log("-" * 60)
                scan_results = scan_all_stocks()
                candidate_stocks = [s["code"] for s in scan_results if "code" in s]
                result['summary']['total_industries'] = 0
                result['summary']['matched_industries'] = 0
                result['summary']['total_candidates'] = len(candidate_stocks)
                self._log(f"  扫描到 {len(candidate_stocks)} 只个股")
            else:
                candidate_stocks = self._get_candidate_stocks(
                    matched_industry_codes, result['summary']
                )
            
            if not candidate_stocks:
                self._log("\n候选个股列表为空，选股结束。")
                result['summary']['duration'] = round(time.time() - start_time, 2)
                return result
            
            # Step 3: 个股筛选（每个公式独立运行）
            if self._skip_stock or not self._stock_asts:
                self._log("\nStep 3: 个股筛选 [已跳过或无公式]")
            else:
                for name, ast in self._stock_asts:
                    self._log(f"\n{'=' * 60}")
                    self._log(f"个股筛选 - [{name}]")
                    self._log('-' * 60)
                    
                    formula_result = {}
                    matched = self._filter_stocks(
                        candidate_stocks, formula_result,
                        name=name, stock_ast=ast
                    )
                    formula_result['matched_stocks'] = matched
                    formula_result['total_matched'] = len(matched)
                    result['formulas'][name] = formula_result
            
        except Exception as e:
            error_msg = f"选股过程出错: {e}"
            self._log(f"\n[错误] {error_msg}")
            result['summary']['errors'].append(error_msg)
        
        result['summary']['duration'] = round(time.time() - start_time, 2)
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
        
        result["total_candidates"] = len(all_stocks)
        result["stock_industry_map"] = stock_industry_map
        result["industry_stock_counts"] = industry_stock_counts
        self._log(f"\n  去重后候选个股: {len(all_stocks)} 只")
        return sorted(all_stocks)
    def _filter_stocks(self,
                       candidate_stocks: List[str],
                       result: Dict,
                       name: str = "",
                       stock_ast=None) -> List[str]:
        """
        Step 3: 个股筛选。
        遍历所有候选个股，执行个股选择公式，返回符合条件的个股代码列表。
        """
        total = len(candidate_stocks)
        jobs = self._resolve_jobs(total)

        if jobs > 1:
            self._log(f"  并行筛选 {total} 只候选个股，{jobs} 进程...")
            outcomes = self._eval_stocks_parallel(candidate_stocks, jobs, stock_ast)
        else:
            outcomes = self._eval_stocks_serial(candidate_stocks, stock_ast)

        # 汇总（串行/并行共用）：条件诊断 + 命中明细
        matched_stocks = []
        cond_pass = {}      # label -> 通过数
        cond_order = []     # 保持公式中的条件顺序
        evaluated = 0

        for code, info in outcomes:
            if info is None:
                continue                       # 数据不足，跳过
            if "error" in info:
                result.setdefault('errors', []).append(f"个股 {code}: {info['error']}")
                continue
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

        result["condition_diag"] = {
            "evaluated": evaluated,
            "rows": [(label, cond_pass[label]) for label in cond_order],
        }

        self._log(f"\n  符合条件的个股: {len(matched_stocks)} / {total}")
        for code in matched_stocks:
            self._log(f"    - {code}")

        return matched_stocks

    def _resolve_jobs(self, n: int) -> int:
        """确定并行进程数：显式 jobs 优先，否则 cpu-2；小批量退化为串行。"""
        if n < 50:
            return 1                            # 小批量串行，省去进程开销
        if self._jobs is not None:
            return max(1, self._jobs)
        return max(1, (os.cpu_count() or 4) - 2)

    def _eval_stocks_serial(self, candidate_stocks: List[str], stock_ast=None) -> List[Tuple[str, Optional[Dict]]]:
        """串行执行个股公式（逐只打印进度）。"""
        total = len(candidate_stocks)
        out = []
        for i, code in enumerate(candidate_stocks):
            self._log(f"  [{i+1}/{total}] {code}...", end='')
            code, info = _eval_one_stock_with(code, stock_ast)
            if info is None:
                self._log(" 数据不足，跳过")
            elif "error" in info:
                self._log(f"  [错误] {info['error']}")
            else:
                self._log(" ✓ 符合条件" if info["result"] else " ✗")
            out.append((code, info))
        return out

    def _eval_stocks_parallel(self, candidate_stocks: List[str], jobs: int, stock_ast=None):
        """多进程执行个股公式。tushare 模式下父进程先建面板，fork 写时复制共享。"""
        # 父进程构建一次重输入（全市场面板），供 fork 子进程共享
        if config.active_data_source() == "tushare":
            from data import tushare_source
            tushare_source._load_stock_panel()

        # macOS 下 fork 子进程涉及系统库时需放开 fork 安全限制
        os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
        try:
            ctx = mp.get_context("fork")       # Unix/macOS：写时复制共享面板
        except ValueError:
            ctx = mp.get_context()             # Windows：spawn 回退（各自读 .day）

        chunk = max(1, len(candidate_stocks) // (jobs * 8))
        with ctx.Pool(processes=jobs,
                      initializer=_init_stock_worker,
                      initargs=(stock_ast, config.active_data_source())) as pool:
            return list(pool.imap(_eval_one_stock, candidate_stocks, chunksize=chunk))

