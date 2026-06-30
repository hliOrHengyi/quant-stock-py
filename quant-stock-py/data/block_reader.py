"""
通达信板块文件 (.blk) 解析器
从 C:\通达信/T0002\blocknew/ 读取板块及成分股数据。

通达信新版 blocknew 目录使用特定的二进制格式存储板块定义和成分股。
同时支持旧版 block 目录的纯文本格式（每行一个 "市场标志+股票代码"）。
"""
import os
import struct
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import config
from config import TDX_BLOCK_DIR


def read_block_stocks_by_index(index_code: str):
    """读取板块/行业指数的成分股，按当前数据源分发。"""
    if config.active_data_source() == "tushare":
        from data import tushare_source
        return tushare_source.read_block_stocks_by_index(index_code)
    return _tdx_read_block_stocks_by_index(index_code)


# ============== 新版 blocknew 二进制格式解析 ==============

def _read_blk_file_v2(filepath: str) -> Optional[List[str]]:
    """
    解析通达信 blocknew 目录下的 .blk 二进制文件。
    通达信新版 .blk 是二进制格式，结构简单：
    - 文件头: 不定，包含板块名称等信息
    - 数据区: 每 4 字节一个 int32，表示股票代码（不含前缀的数字）
    
    此函数尝试解析二进制格式，如果失败则回退到文本格式。
    """
    if not os.path.isfile(filepath):
        return None
    
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except (IOError, OSError):
        return None
    
    if len(data) == 0:
        return None
    
    # 尝试作为文本格式解析（兼容旧版）
    try:
        text = data.decode('gbk')
        codes = _parse_text_blk(text)
        if codes:
            return codes
    except (UnicodeDecodeError, ValueError):
        pass
    
    # 尝试二进制格式解析
    # 通达信 .blk 二进制格式：跳过头部（板块名等），后面的字节按 int32 解析为股票代码
    # 股票代码用 int32 表示，不含市场前缀
    codes = set()
    
    # 寻找数据起点：跳过非数字区域
    # 通常在文件偏移 0x20 左右开始有规则的 4 字节对齐的股票代码数据
    # 先尝试整个文件按 4 字节对齐扫描
    tail = data
    if len(tail) >= 4:
        # 从各个位置尝试解析
        for start_offset in [0, 4, 8, 12, 16, 20, 24, 28, 32]:
            codes_found = set()
            valid_count = 0
            for i in range(start_offset, len(tail) - 3, 4):
                val = struct.unpack('<i', tail[i:i+4])[0]
                # 沪深 A 股代码范围：1-999999
                if 1 <= val <= 999999:
                    code_str = f'{val:06d}'
                    codes_found.add(code_str)
                    valid_count += 1
                elif val == 0:
                    continue  # 填充位，跳过
                else:
                    # 非股票代码值，可能误判
                    if valid_count < 3:
                        break
            if valid_count >= 3:
                codes.update(codes_found)
    
    if codes:
        return sorted(codes)
    
    # 最后尝试：用所有 6 位数字模式匹配
    import re
    digits = re.findall(rb'\d{6}', data)
    codes = set()
    for d in digits:
        s = d.decode('ascii')
        if s.startswith(('60', '00', '30', '68', '83', '88', '90')):
            codes.add(s)
    if codes:
        return sorted(codes)
    
    return None


def _parse_text_blk(text: str) -> List[str]:
    """
    解析纯文本格式的 .blk 文件。
    通达信旧版格式：
    - 每行一个股票，格式如 "1SH600000" 或 "0SZ000001"
    - 首字符 1=上海 0=深圳
    - 或者直接是 6 位纯数字代码
    """
    codes = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 尝试匹配 "1SH600000" 或 "0SZ000001" 格式
        if len(line) >= 8 and line[0] in ('0', '1'):
            code_part = line[3:] if line[3:].isdigit() else line[-6:]
            if len(code_part) == 6 and code_part.isdigit():
                codes.append(code_part)
                continue
        # 尝试纯 6 位数字
        if len(line) == 6 and line.isdigit():
            codes.append(line)
            continue
        # 尝试股票名称格式如 "SH600000"
        code_part = line[-6:]
        if len(code_part) == 6 and code_part.isdigit():
            codes.append(code_part)
    return codes


# ============== .dat 板块索引文件解析 ==============

def _read_dat_index(filepath: str) -> Optional[List[Dict]]:
    """
    解析通达信 blocknew 目录下的 .dat 文件（板块索引）。
    .dat 文件包含板块名称到板块代码的映射。
    
    二进制格式：
    - 板块记录结构（可变长度）：
      - 板块ID (4字节 int)
      - 板块名称 (变长 GBK 字符串)
      - 其他元数据
    
    返回列表，每项包含板块名称和可能的内部 ID。
    """
    if not os.path.isfile(filepath):
        return None
    
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except (IOError, OSError):
        return None
    
    if len(data) < 16:
        return None
    
    blocks = []
    
    # 尝试搜索 GBK 中文字符串
    i = 0
    while i < len(data) - 4:
        # 尝试解析名称长度
        if i + 4 <= len(data):
            name_len_bytes = data[i:i+4]
            name_len = struct.unpack('<I', name_len_bytes)[0]
            if 2 <= name_len <= 50 and i + 4 + name_len <= len(data):
                try:
                    name = data[i+4:i+4+name_len].decode('gbk').strip('\x00').strip()
                    if name and any('\u4e00' <= c <= '\u9fff' for c in name):
                        blocks.append({'name': name})
                        i += 4 + name_len
                        continue
                except:
                    pass
        i += 1
    
    return blocks if blocks else None


# ============== 高级 API ==============

def get_industry_blocks() -> Dict[str, List[str]]:
    """
    获取所有行业板块及其成分股。
    
    返回值:
        { '半导体': ['600519', '000001', ...], '银行': [...], ... }
    """
    result = {}
    
    # 首先尝试读取 BKZH.blk 获取板块综合信息
    bkzh_file = os.path.join(TDX_BLOCK_DIR, 'BKZH.blk')
    if os.path.isfile(bkzh_file):
        # BKZH 是板块综合索引，其中包含板块列表
        # 板块成分股存在 CC.blk 中
        pass
    
    # 读取 CC.blk（成分股文件）
    cc_file = os.path.join(TDX_BLOCK_DIR, 'CC.blk')
    if os.path.isfile(cc_file):
        stocks = _read_blk_file_v2(cc_file)
        if stocks:
            result['板块综合'] = stocks
    
    # 从 BKZH.dat 尝试解析板块名称
    bkzh_dat = os.path.join(TDX_BLOCK_DIR, 'BKZH.dat')
    if os.path.isfile(bkzh_dat):
        blocks = _read_dat_index(bkzh_dat)
        if blocks:
            for b in blocks:
                name = b['name']
                # 尝试读取对应的 .blk 文件（如果有的话）
                blk_file = os.path.join(TDX_BLOCK_DIR, f'{name}.blk')
                # 某些板块可能有单独的 blk 文件
                if os.path.isfile(blk_file):
                    codes = _read_blk_file_v2(blk_file)
                    if codes:
                        result[name] = codes
    
    return result


def read_block_stocks(block_name: str) -> Optional[List[str]]:
    """
    根据板块名称读取其成分股。
    
    先在 blocknew 目录中查找对应文件，再尝试解析。
    """
    # 按名称直接找 .blk 文件
    blk_file = os.path.join(TDX_BLOCK_DIR, f'{block_name}.blk')
    if os.path.isfile(blk_file):
        return _read_blk_file_v2(blk_file)
    
    # 尝试在 BKZH.blk 等索引中查找
    for idx_name in ['BKZH', 'CC', 'tjg']:
        idx_file = os.path.join(TDX_BLOCK_DIR, f'{idx_name}.blk')
        if os.path.isfile(idx_file):
            result = _read_blk_file_v2(idx_file)
            if result:
                return result
    
    return None


def list_available_blocks() -> List[str]:
    """列出 blocknew 目录下所有可读取的板块文件名称。"""
    blocks = []
    if not os.path.isdir(TDX_BLOCK_DIR):
        return blocks
    
    for fname in os.listdir(TDX_BLOCK_DIR):
        if fname.endswith('.blk'):
            name = fname[:-4]
            blocks.append(name)
    
    return sorted(blocks)


def get_block_mapping() -> Dict[str, List[str]]:
    """
    获取行业板块代码到其成分股的映射。
    
    通达信行业板块索引代码（如 881319）对应的成分股，
    通过板块文件中的关系映射。
    
    由于 blocknew 目录的二进制格式较复杂，此函数
    会尝试多种策略来建立 板块代码 → 成分股 的映射。
    
    返回值:
        { '881319': ['600519', '000001', ...], '881200': [...], ... }
    """
    mapping = {}

    # 策略1: 尝试读取行业分类的 .blk 文件
    # 行业板块分类文件可能使用行业名称或代码作为文件名
    for fname in os.listdir(TDX_BLOCK_DIR):
        if not fname.endswith('.blk'):
            continue
        filepath = os.path.join(TDX_BLOCK_DIR, fname)
        codes = _read_blk_file_v2(filepath)
        if codes:
            name = fname[:-4]
            mapping[name] = codes

    return mapping



_INFOHARBOR_MAPPING = None

def _get_infoharbor_mapping() -> Dict[str, List[str]]:
    """从 infoharbor_block.dat 解析板块指数→成分股映射 (缓存)"""
    global _INFOHARBOR_MAPPING
    if _INFOHARBOR_MAPPING is not None:
        return _INFOHARBOR_MAPPING
    mapping = {}
    path = os.path.join(os.path.dirname(TDX_BLOCK_DIR), "hq_cache", "infoharbor_block.dat")
    if not os.path.isfile(path):
        _INFOHARBOR_MAPPING = mapping
        return mapping
    with open(path, "rb") as f:
        data = f.read()
    text = data.decode("gbk", errors="ignore")
    sections = text.split("#GN_")
    for section in sections[1:]:
        first_nl = section.find("\n")
        if first_nl <= 0:
            continue
        header = section[:first_nl].strip()
        parts = header.split(",")
        if len(parts) >= 3 and parts[2].startswith("88") and parts[2].isdigit():
            code = parts[2]
            stocks = set()
            for line in section.split("\n")[1:]:
                for item in line.strip().split(","):
                    item = item.strip()
                    if "#" in item:
                        sc = item.split("#")[1]
                        if sc.isdigit() and len(sc) == 6:
                            stocks.add(sc)
            if stocks:
                mapping[code] = sorted(stocks)
    _INFOHARBOR_MAPPING = mapping
    return mapping

def _tdx_read_block_stocks_by_index(index_code: str) -> Optional[List[str]]:
    """
    根据板块指数代码读取成分股（通达信 blocknew）。
    例如 read_block_stocks_by_index('881319') 返回半导体板块成分股。
    
    在通达信中，板块指数 881319 对应的成分股通常存储在
    以板块名命名的 .blk 文件或索引文件中。
    """
    # 策略1: 直查以代码命名的 .blk 文件
    blk_file = os.path.join(TDX_BLOCK_DIR, f"{index_code}.blk")
    if os.path.isfile(blk_file):
        codes = _read_blk_file_v2(blk_file)
        if codes:
            return codes
    
    # 策略2: 从 get_block_mapping() 的 name->stocks 映射做文本匹配
    mapping = get_block_mapping()
    for name, stocks in mapping.items():
        if index_code in name or name in index_code:
            return stocks
    
    # 策略3: 尝试通过 BKZH.dat 中解析出的板块名查找 .blk 文件
    bkzh_dat = os.path.join(TDX_BLOCK_DIR, "BKZH.dat")
    if os.path.isfile(bkzh_dat):
        blocks = _read_dat_index(bkzh_dat)
        if blocks:
            for b in blocks:
                name = b["name"]
                blk_file = os.path.join(TDX_BLOCK_DIR, f"{name}.blk")
                if os.path.isfile(blk_file):
                    codes = _read_blk_file_v2(blk_file)
                    if codes:
                        return codes
    
    # 新策略: 从 infoharbor_block.dat 获取板块成分股（概念板块）
    mapping = _get_infoharbor_mapping()
    if index_code in mapping:
        return mapping[index_code]

    # 策略4: 兜底 — 读取 CC.blk（板块综合成分股）
    cc_file = os.path.join(TDX_BLOCK_DIR, "CC.blk")
    if os.path.isfile(cc_file):
        codes = _read_blk_file_v2(cc_file)
        if codes:
            return codes
    
    return None


