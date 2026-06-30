"""
通达信日线数据 (.day) 解析器
从 C:\通达信\vipdoc/sh/lday 和 sz/lday 读取日线数据。
格式：每个文件 32 字节一条记录
  offset  size  field
  0       4     日期 (YYYYMMDD 整数)
  4       4     开盘价 * 100 (int)
  8       4     最高价 * 100 (int)
  12      4     最低价 * 100 (int)
  16      4     收盘价 * 100 (int)
  20      4     成交额 (float)
  24      4     成交量 (int)
  28      4     保留
"""
import os
import struct
import glob
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config
from config import TDX_LDAY_SH, TDX_LDAY_SZ, MIN_DAYS


# ============== 数据源分发（通达信 / tushare） ==============
# tushare 后端按需懒加载，确保 Windows(通达信)端无需安装 pyarrow。

def read_stock_daily(stock_code: str):
    """读单只股票/指数日线，按当前数据源分发。"""
    if config.active_data_source() == "tushare":
        from data import tushare_source
        return tushare_source.read_stock_daily(stock_code)
    return _tdx_read_stock_daily(stock_code)


def scan_industry_indices():
    """扫描板块指数，按当前数据源分发。"""
    if config.active_data_source() == "tushare":
        from data import tushare_source
        return tushare_source.scan_industry_indices()
    return _tdx_scan_industry_indices()


def scan_all_stocks():
    """扫描全市场个股，按当前数据源分发。"""
    if config.active_data_source() == "tushare":
        from data import tushare_source
        return tushare_source.scan_all_stocks()
    return _tdx_scan_all_stocks()


def _parse_day_file(filepath: str) -> Optional[pd.DataFrame]:
    """
    解析单个 .day 文件，返回带日期索引的 DataFrame。
    格式：小端序，每条 32 字节。
    """
    record_size = 32
    records = []

    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except (IOError, OSError) as e:
        print(f"  [警告] 无法读取 {filepath}: {e}")
        return None

    if len(data) % record_size != 0:
        print(f"  [警告] {filepath} 文件大小异常 ({len(data)} bytes)，跳过")
        return None

    record_count = len(data) // record_size
    if record_count < MIN_DAYS:
        # 数据太少，不可用
        return None

    fmt = '<IIIIIIfI'  # 小端: 日期, 开盘, 最高, 最低, 收盘, 成交额(float), 成交量, 保留
    for i in range(record_count):
        offset = i * record_size
        raw = data[offset:offset + record_size]
        (
            date_int,
            open_p, high_p, low_p, close_p,
            amount_f,
            volume,
            _reserved
        ) = struct.unpack(fmt, raw)

        records.append({
            'date': date_int,
            'open': open_p / 100.0,
            'high': high_p / 100.0,
            'low': low_p / 100.0,
            'close': close_p / 100.0,
            'amount': amount_f,
            'volume': volume,
        })

    df = pd.DataFrame(records)
    # 将日期整数转为 datetime
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df.sort_values('date', inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def _stock_code_from_filename(filename: str) -> str:
    """
    从文件名提取股票代码。
    sh600519.day -> 600519
    sz000001.day -> 000001
    """
    basename = os.path.splitext(os.path.basename(filename))[0]
    # 去掉前缀字母，保留数字部分
    code = ''.join(ch for ch in basename if ch.isdigit())
    return code


def _exchange_from_filename(filename: str) -> str:
    """从文件名提取交易所: sh / sz"""
    basename = os.path.splitext(os.path.basename(filename))[0]
    return basename[:2]


def _tdx_read_stock_daily(stock_code: str) -> Optional[pd.DataFrame]:
    """
    读取指定股票/板块指数的日线数据（通达信 .day）。
    自动在 sh 和 sz 目录中查找。

    Args:
        stock_code: 6 位股票代码，如 '600519', '881319'

    Returns:
        包含 date, open, high, low, close, volume, amount 的 DataFrame，
        按日期升序排列。
        如果找不到则返回 None。
    """
    for lday_dir in [TDX_LDAY_SH, TDX_LDAY_SZ]:
        if not os.path.isdir(lday_dir):
            continue
        # 遍历目录下所有文件，匹配代码
        pattern = os.path.join(lday_dir, f'*{stock_code}.day')
        matches = glob.glob(pattern)
        if matches:
            return _parse_day_file(matches[0])

    print(f"  [警告] 未找到股票 {stock_code} 的日线数据")
    return None


def _tdx_scan_industry_indices() -> List[Dict]:
    """
    扫描所有行业板块指数（88 开头的指数）。
    返回列表，每项包含 {'code': '881319', 'exchange': 'sh'}。

    通达信行业板块指数代码为 88 开头的 6 位数字，
    存储在 sh/lday 或 sz/lday 目录中。
    """
    indices = []
    for lday_dir, exchange in [(TDX_LDAY_SH, 'sh'), (TDX_LDAY_SZ, 'sz')]:
        if not os.path.isdir(lday_dir):
            continue
        for fname in os.listdir(lday_dir):
            if not fname.endswith('.day'):
                continue
            code = _stock_code_from_filename(fname)
            if code.startswith('88') and len(code) == 6:
                indices.append({
                    'code': code,
                    'exchange': exchange,
                    'filepath': os.path.join(lday_dir, fname),
                })
    return indices


def _tdx_scan_all_stocks() -> List[Dict]:
    """
    扫描所有非指数股票（非 88/99/90 开头的代码）。
    返回列表，每项包含 {'code': '600519', 'exchange': 'sh'}。
    """
    stocks = []
    for lday_dir, exchange in [(TDX_LDAY_SH, 'sh'), (TDX_LDAY_SZ, 'sz')]:
        if not os.path.isdir(lday_dir):
            continue
        for fname in os.listdir(lday_dir):
            if not fname.endswith('.day'):
                continue
            code = _stock_code_from_filename(fname)
            # 排除指数类（88板块指数, 99/90等）
            if code.startswith(('88', '99', '90', '00')):
                if code.startswith('000') or code.startswith('001'):
                    pass  # 000001 等是股票
                elif len(code) != 6:
                    continue
                elif code.startswith(('880', '881', '882', '883', '884', '885', '886', '887', '888', '889')):
                    continue  # 板块指数
            if code.startswith('9') and len(code) == 6:
                continue  # B 股
            stocks.append({
                'code': code,
                'exchange': exchange,
                'filepath': os.path.join(lday_dir, fname),
            })
    return stocks


def read_batch_daily(stock_codes: List[str],
                     max_workers: int = 4) -> Dict[str, Optional[pd.DataFrame]]:
    """
    批量读取多个股票的日线数据。

    Args:
        stock_codes: 股票代码列表
        max_workers: 并行线程数（目前串行，后续可优化）

    Returns:
        { code: DataFrame or None }
    """
    result = {}
    for code in stock_codes:
        result[code] = read_stock_daily(code)
    return result
