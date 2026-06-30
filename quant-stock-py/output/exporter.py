"""
结果导出模块
将选股结果输出为通达信 .blk 板块文件（纯文本格式），
写入当前项目目录，不碰 C 盘。
"""
import os
import shutil
from datetime import datetime
from typing import List

from config import OUTPUT_BLOCK_FILE, BACKUP_OUTPUT


def export_to_blk(stock_codes: List[str],
                  output_path: str = None,
                  backup: bool = None) -> str:
    """
    将选股结果导出为通达信 .blk 板块文件。

    通达信 .blk 格式（新版兼容）：
    - 支持纯文本格式：每行一个 "市场前缀+股票代码"
    - 上海: 1SH + 代码
    - 深圳: 0SZ + 代码

    Args:
        stock_codes: 股票代码列表，如 ['600519', '000001', ...]
        output_path: 输出文件路径，默认使用 config.OUTPUT_BLOCK_FILE
        backup: 是否备份现有文件

    Returns:
        输出文件路径
    """
    from datetime import datetime
    if output_path is None:
        today = datetime.now()
        output_path = os.path.join(os.path.dirname(OUTPUT_BLOCK_FILE), f"{today.day:02d}{today.month:02d}{today.year}个股.blk")
    backup = BACKUP_OUTPUT if backup is None else backup

    # 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # 备份现有文件
    if backup and os.path.isfile(output_path):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{output_path}.{timestamp}.bak"
        shutil.copy2(output_path, backup_path)
        print(f"  已备份原文件: {backup_path}")

    # 生成 .blk 格式内容
    lines = []
    for code in stock_codes:
        code = code.strip()
        if not code.isdigit() or len(code) != 6:
            print(f"  [警告] 跳过无效股票代码: {code}")
            continue

        # 通达信 .blk 格式: 市场前缀(1位)+代码(6位)=7位
        if code.startswith(('0', '3')):
            prefix = '0'    # 深圳主板/创业板
        elif code.startswith(('83', '87', '92')):
            prefix = '2'    # 北交所
        elif code.startswith(('6', '68', '9', '88')):
            prefix = '1'    # 上海主板/科创板/B股/板块指数
        else:
            prefix = '0'    # 默认深圳

        line = prefix + code
        lines.append(line)

    # 写入文件
    with open(output_path, 'w', encoding='gbk') as f:
        f.write('\n'.join(lines))
        f.write('\n')

    print(f"\n  选股结果已导出: {output_path}")
    print(f"  共 {len(lines)} 只股票")

    return output_path


def export_summary(result: dict, output_path: str = None):
    """
    导出选股摘要报告。

    Args:
        result: engine.run() 返回的结果字典
        output_path: 摘要文件路径
    """
    if output_path is None:
        output_dir = os.path.dirname(OUTPUT_BLOCK_FILE)
        output_path = os.path.join(output_dir, '选股报告.txt')

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    lines = [
        "=" * 60,
        f"通达信自定义选股系统 - 选股报告",
        f"生成时间: {timestamp}",
        "=" * 60,
        "",
        f"【选股概况】",
        f"  扫描板块指数: {result.get('total_industries', 0)} 个",
        f"  符合条件板块: {result.get('matched_industries', 0)} 个",
        f"  候选个股:     {result.get('total_candidates', 0)} 只",
        f"  最终入选:     {result.get('total_matched', 0)} 只",
        f"  耗时:         {result.get('duration', 0)} 秒",
        "",
    ]

    if result.get('matched_industry_names'):
        lines.append("【符合条件的板块】")
        for name in result['matched_industry_names']:
            lines.append(f"  - {name}")
        lines.append("")

    if result.get('matched_stocks'):
        lines.append("【最终入选个股】")
        for i, code in enumerate(result['matched_stocks'], 1):
            lines.append(f"  {i:3d}. {code}")
        lines.append("")

    if result.get('errors'):
        lines.append("【错误信息】")
        for err in result['errors']:
            lines.append(f"  - {err}")
        lines.append("")

    lines.append("=" * 60)
    lines.append("注意：本文件由系统自动生成，请将 日期选股.blk 文件")
    lines.append("手动复制到通达信 T0002\\blocknew 目录下使用。")
    lines.append("=" * 60)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"\n选股报告已导出: {output_path}")
    return output_path

def export_industry_blk(industry_codes: List[str],
                        output_path: str = None) -> str:
    """将板块筛选结果导出为通达信 .blk 板块文件。"""
    from datetime import datetime
    today = datetime.now()
    default_name = f"{today.day:02d}{today.month:02d}{today.year}板块.blk"
    output_path = output_path or os.path.join(
        os.path.dirname(OUTPUT_BLOCK_FILE), default_name)
    
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    lines = []
    for code in industry_codes:
        code = code.strip()
        if not code or len(code) != 6:
            continue
        # 88板块指数全部在上海市场
        lines.append('1' + code)
    
    with open(output_path, 'w', encoding='gbk') as f:
        f.write("\n".join(lines) + "\n")
    
    print(f"\n  板块结果已导出: {output_path}")
    print(f"  共 {len(lines)} 个板块指数")
    return output_path


import os
_TDX_ROOT = r"C:\通达信"

def _build_stock_name_map():
    m = {}
    p = os.path.join(_TDX_ROOT, "T0002", "hq_cache", "tdxpkmore.cfg")
    if not os.path.isfile(p): return m
    with open(p, "rb") as f:
        for line in f.read().decode("gbk", errors="ignore").split("\r\n"):
            parts = line.split("|")
            if len(parts)>=3 and parts[0] in ("0","1") and len(parts[1])==6:
                m[parts[1]] = parts[2]
    return m

def _build_stock_concepts_map():
    m = {}
    p = os.path.join(_TDX_ROOT, "T0002", "hq_cache", "specgpext.txt")
    if not os.path.isfile(p): return m
    with open(p, "rb") as f:
        for line in f.read().decode("gbk", errors="ignore").split("\r\n"):
            parts = line.split("|")
            if len(parts)>=3 and parts[0]=="0":
                code = parts[1]; concept = parts[2]
                m.setdefault(code, []).append(concept)
    return m

def export_detailed_result(result: dict, output_path: str = None):
    """输出详细的选股结果到 CSV 文件，方便用 Excel 等工具查看。"""
    import pandas as pd
    from datetime import datetime
    today = datetime.now()
    output_path = output_path or os.path.join(os.path.dirname(OUTPUT_BLOCK_FILE),
        f"{today.day:02d}{today.month:02d}{today.year}选股详情.csv")

    name_map = _build_stock_name_map()
    details = result.get("stock_details", [])

    rows = []
    for d in details:
        code = d["code"]
        p = d["debug"].get("price", {})
        industry_codes = d.get("industry_codes", [])
        rows.append({
            "代码": code,
            "名称": name_map.get(code, ""),
            "收盘": p.get("close", 0),
            "开盘": p.get("open", 0),
            "最高": p.get("high", 0),
            "最低": p.get("low", 0),
            "关联板块(板块指数代码)": " ".join(industry_codes),
        })

    if not rows:
        rows.append({
            "代码": "", "名称": "未命中任何股票",
            "收盘": "", "开盘": "", "最高": "", "最低": "",
            "关联板块(板块指数代码)": "",
        })

    df = pd.DataFrame(rows)
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n  详情报告已导出: {output_path}")
    print(f"  共 {len(rows)} 条记录")
    return output_path
