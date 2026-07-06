"""
结果导出模块
将选股结果输出为通达信 .blk 板块文件（纯文本格式），
写入当前项目目录，不碰 C 盘。
"""
import os
import shutil
from datetime import datetime
from typing import List

from config import OUTPUT_BLOCK_FILE, BACKUP_OUTPUT, TDX_HQ_CACHE


def _daily_dir() -> str:
    """返回当天输出子目录: dailyresult/ddMMyyyy/"""
    today = datetime.now()
    date_str = f"{today.day:02d}{today.month:02d}{today.year}"
    return os.path.join(os.path.dirname(OUTPUT_BLOCK_FILE), date_str)


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
        output_path = os.path.join(_daily_dir(), f"{today.day:02d}{today.month:02d}{today.year}个股.blk")
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
        output_path = os.path.join(_daily_dir(), '选股报告.txt')

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
    output_path = output_path or os.path.join(_daily_dir(), default_name)
    
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


def _build_stock_name_map():
    m = {}
    p = os.path.join(TDX_HQ_CACHE, "tdxpkmore.cfg")
    if not os.path.isfile(p): return m
    with open(p, "rb") as f:
        for line in f.read().decode("gbk", errors="ignore").split("\r\n"):
            parts = line.split("|")
            if len(parts)>=3 and parts[0] in ("0","1") and len(parts[1])==6:
                m[parts[1]] = parts[2]
    return m

def _active_name_maps():
    """按数据源返回 (股票名映射, 板块名映射)。tushare 用数据湖，通达信用本地缓存。"""
    import config
    if config.active_data_source() == "tushare":
        try:
            from data import tushare_source
            return tushare_source.stock_name_map(), tushare_source.board_name_map()
        except Exception:
            return {}, {}
    return _build_stock_name_map(), {}


def _build_stock_concepts_map():
    m = {}
    p = os.path.join(TDX_HQ_CACHE, "specgpext.txt")
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
    output_path = output_path or os.path.join(_daily_dir(),
        f"{today.day:02d}{today.month:02d}{today.year}选股详情.csv")

    name_map = _build_stock_name_map()
    details = result.get("stock_details", [])

    rows = []
    for d in details:
        code = d["code"]
        p = d.get("price", {})
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


# ============== Excel 选股报告 ==============

def _pct(numerator, denominator) -> str:
    """安全计算百分比字符串。"""
    if not denominator:
        return "-"
    return f"{numerator / denominator * 100:.1f}%"


def _autofit(worksheet):
    """根据内容粗略自适应列宽，并加粗首行表头。"""
    from openpyxl.styles import Font, Alignment
    for col_cells in worksheet.columns:
        max_len = 0
        col_letter = col_cells[0].column_letter
        for cell in col_cells:
            if cell.value is not None:
                # 中文按 2 个宽度估算
                text = str(cell.value)
                width = sum(2 if ord(ch) > 127 else 1 for ch in text)
                max_len = max(max_len, width)
        worksheet.column_dimensions[col_letter].width = min(max_len + 2, 60)
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')
    worksheet.freeze_panes = 'A2'


def export_excel_report(result: dict, output_path: str = None,
                        industry_formula: str = None,
                        stock_formula: str = None):
    """
    导出 Excel 版选股报告（多 sheet）：
      1. 选股概况   —— 漏斗、转化率、参数、耗时
      2. 个股明细   —— 命中个股的价格 + KDJ/量比/砖型图等指标快照
      3. 板块汇总   —— 入选板块、成分股数、命中个股数、命中率
      4. 条件诊断   —— 各子条件在候选池上的通过率（定位瓶颈）

    缺少 openpyxl 时自动降级为 CSV 详情。
    """
    import pandas as pd
    from datetime import datetime

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("\n  [提示] 未安装 openpyxl，无法生成 Excel；改为导出 CSV 详情。")
        print("         安装后即可生成 Excel:  pip install openpyxl")
        return export_detailed_result(result)

    today = datetime.now()
    if output_path is None:
        output_path = os.path.join(_daily_dir(),
            f"{today.day:02d}{today.month:02d}{today.year}选股报告.xlsx")

    name_map, board_name_map = _active_name_maps()
    concept_map = _build_stock_concepts_map()
    details = result.get("stock_details", [])

    # ---------- Sheet 1: 选股概况（漏斗） ----------
    ti = result.get("total_industries", 0)
    mi = result.get("matched_industries", 0)
    tc = result.get("total_candidates", 0)
    tm = result.get("total_matched", 0)
    overview_rows = [
        ("生成时间", today.strftime("%Y-%m-%d %H:%M:%S")),
        ("板块公式", os.path.basename(industry_formula) if industry_formula else "-"),
        ("个股公式", os.path.basename(stock_formula) if stock_formula else "-"),
        ("① 扫描板块指数", ti),
        ("② 符合条件板块", f"{mi}   (板块通过率 {_pct(mi, ti)})"),
        ("③ 候选个股(成分股去重)", tc),
        ("④ 最终入选个股", f"{tm}   (个股通过率 {_pct(tm, tc)})"),
        ("漏斗总转化率", _pct(tm, ti) + "  (入选/板块)"),
        ("耗时(秒)", result.get("duration", 0)),
        ("错误数", len(result.get("errors", []))),
    ]
    df_overview = pd.DataFrame(overview_rows, columns=["项目", "数值"])

    # ---------- Sheet 2: 个股明细 + 命中拆解 ----------
    stock_rows = []
    for d in details:
        code = d["code"]
        v = d.get("variables", {})
        p = d.get("price", {})
        concepts = concept_map.get(code, [])
        stock_rows.append({
            "代码": code,
            "名称": name_map.get(code, ""),
            "收盘": p.get("close"),
            "涨跌幅%": p.get("pct_chg"),
            "量比": p.get("vol_ratio"),
            "开盘": p.get("open"),
            "最高": p.get("high"),
            "最低": p.get("low"),
            "KDJ-J": v.get("J"),
            "KDJ-K": v.get("K"),
            "KDJ-D": v.get("D"),
            "砖型量(VAR6A)": v.get("VAR6A"),
            "所属板块": " ".join(d.get("industry_codes", [])),
            "概念": " ".join(concepts[:5]),
        })
    df_stocks = pd.DataFrame(stock_rows) if stock_rows else pd.DataFrame(
        [{"代码": "", "名称": "未命中任何股票"}])

    # ---------- Sheet 3: 板块汇总 ----------
    matched_codes = result.get("matched_industry_codes", [])
    counts = result.get("industry_stock_counts", {})
    # 反推每个板块命中了几只个股
    hit_by_industry = {}
    for d in details:
        for ic in d.get("industry_codes", []):
            hit_by_industry[ic] = hit_by_industry.get(ic, 0) + 1
    industry_rows = []
    for ic in matched_codes:
        total_members = counts.get(ic, 0)
        hits = hit_by_industry.get(ic, 0)
        industry_rows.append({
            "板块指数代码": ic,
            "名称": board_name_map.get(ic, ""),
            "成分股数": total_members,
            "命中个股数": hits,
            "命中率": _pct(hits, total_members) if total_members else "-",
        })
    industry_rows.sort(key=lambda r: r["命中个股数"], reverse=True)
    df_industry = pd.DataFrame(industry_rows) if industry_rows else pd.DataFrame(
        [{"板块指数代码": "", "名称": "", "成分股数": 0, "命中个股数": 0, "命中率": "-"}])

    # ---------- Sheet 4: 条件诊断 ----------
    diag = result.get("condition_diag", {})
    evaluated = diag.get("evaluated", 0)
    diag_rows = []
    for label, passed in diag.get("rows", []):
        diag_rows.append({
            "子条件": label,
            "通过数": passed,
            "候选数": evaluated,
            "通过率": _pct(passed, evaluated),
            "通过率(数值)": round(passed / evaluated * 100, 1) if evaluated else 0,
        })
    # 通过率升序：最严苛(卡掉最多)的条件排在最前
    diag_rows.sort(key=lambda r: r["通过率(数值)"])
    for r in diag_rows:
        r.pop("通过率(数值)")
    df_diag = pd.DataFrame(diag_rows) if diag_rows else pd.DataFrame(
        [{"子条件": "(无数据，可能跳过了个股筛选)", "通过数": 0, "候选数": 0, "通过率": "-"}])

    # ---------- 写入 Excel ----------
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_overview.to_excel(writer, sheet_name="选股概况", index=False)
        df_stocks.to_excel(writer, sheet_name="个股明细", index=False)
        df_industry.to_excel(writer, sheet_name="板块汇总", index=False)
        df_diag.to_excel(writer, sheet_name="条件诊断", index=False)
        for ws in writer.book.worksheets:
            _autofit(ws)

    print(f"\n  Excel 选股报告已导出: {output_path}")
    print(f"  共 4 个工作表 (选股概况/个股明细/板块汇总/条件诊断)")
    return output_path
