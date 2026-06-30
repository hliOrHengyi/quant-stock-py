"""
tushare 数据湖后端（macOS 选股用）

读取本地 tushare parquet 数据湖（默认 ~/quant-data/lake，Hive 分区），
对外提供与通达信后端一致的接口，供 reader / block_reader 分发调用：

    read_stock_daily(code)          单只股票 / 申万行业指数 的日线 DataFrame
    scan_industry_indices()         申万 L1 行业指数列表（充当“板块指数”）
    scan_all_stocks()               全市场股票列表
    read_block_stocks_by_index(c)   某行业指数的成分股

数据湖布局（按交易日分区）：
    stock/daily             每个 parquet = 某一交易日全市场: ts_code,trade_date,open,high,low,close,vol,amount,...
    index/index_member_all  申万成分股: l1/l2/l3_code, ts_code, in_date, out_date

注：该数据湖没有申万行业指数(801xxx)的日线行情，故行业板块指数由其成分股
    **等权合成**（见 _synth_board_series），板块级信号为近似，非官方指数点位。

性能：股票全历史是按日分区的，逐股扫全部文件很慢。这里只读“最近
TUSHARE_LOOKBACK_DAYS 个交易日文件”，在父进程里**一次性**建成
{代码 -> 日线DataFrame} 的面板并缓存，后续按代码取切片为内存查找。
parquet 读取用线程池并行（pyarrow 读取期间释放 GIL）。

价格口径：通达信 .day(lday) 与 tushare daily 均为**不复权**，两边对齐，无需复权。
单位：tushare vol 为手、amount 为千元；个股公式只用到量的相对比较(V>=REF(V,1))
与量比，单位可约掉，不影响布尔判定。
"""
import os
import glob
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import config

# 申万行业指数代码前缀（充当板块指数）：80xxxx(L1/L2)、85xxxx(L3)
_INDEX_PREFIXES = ("80", "85", "88")

# 父进程构建一次、只读共享的缓存
_STOCK_PANEL = None      # {code6: DataFrame(date,open,high,low,close,volume,amount)}
_INDEX_PANEL = None      # {board6: DataFrame}
_MEMBER_MAP = None       # {board6: [stock6, ...]}  申万 L1 成分股


def _lake() -> str:
    return config.TUSHARE_LAKE_DIR


def _recent_daily_files(dataset: str, n: int) -> list:
    """返回某数据集最近 n 个按日分区的 parquet 文件（按文件名日期升序）。"""
    pattern = os.path.join(_lake(), dataset, "freq=1d", "year=*", "month=*", "*.parquet")
    files = sorted(glob.glob(pattern))
    return files[-n:] if n and len(files) > n else files


def _read_many(files: list, columns: list) -> pd.DataFrame:
    """线程池并行读取多个 parquet 并纵向拼接。"""
    if not files:
        return pd.DataFrame(columns=columns)
    workers = min(len(files), (os.cpu_count() or 4))

    def _read(f):
        try:
            return pd.read_parquet(f, columns=columns)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        frames = [d for d in ex.map(_read, files) if d is not None and len(d)]
    if not frames:
        return pd.DataFrame(columns=columns)
    return pd.concat(frames, ignore_index=True)


def _build_panel(df: pd.DataFrame) -> dict:
    """把长表(含 ts_code,trade_date,ohlc,vol,amount)切成 {code6: 按日升序的日线}。"""
    if df.empty:
        return {}
    df = df.rename(columns={"vol": "volume"})
    df["code"] = df["ts_code"].str.slice(0, 6)
    df["date"] = pd.to_datetime(df["trade_date"])
    keep = ["date", "open", "high", "low", "close", "volume", "amount"]
    panel = {}
    for code, g in df.sort_values("date").groupby("code", sort=False):
        panel[code] = g[keep].reset_index(drop=True)
    return panel


def _load_stock_panel() -> dict:
    global _STOCK_PANEL
    if _STOCK_PANEL is None:
        cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
        files = _recent_daily_files("asset_class=stock/dataset=daily", config.TUSHARE_LOOKBACK_DAYS)
        _STOCK_PANEL = _build_panel(_read_many(files, cols))
    return _STOCK_PANEL


def _load_members() -> dict:
    """读申万成分股表，构建 {L1行业指数代码6: [当前成分股6,...]}。"""
    global _MEMBER_MAP
    if _MEMBER_MAP is not None:
        return _MEMBER_MAP
    files = glob.glob(os.path.join(
        _lake(), "asset_class=index", "dataset=index_member_all", "**", "*.parquet"),
        recursive=True)
    mp = {}
    if files:
        m = pd.read_parquet(files[0], columns=["l1_code", "ts_code", "out_date"])
        m = m[m["out_date"].isna()]                       # 仅当前在册成分
        m = m.assign(board=m["l1_code"].str.slice(0, 6),
                     scode=m["ts_code"].str.slice(0, 6))
        mp = {b: sorted(set(g)) for b, g in m.groupby("board")["scode"]}
    _MEMBER_MAP = mp
    return mp


def _synth_board_series(members: list, stock_panel: dict):
    """
    用成分股**等权**合成行业板块指数日线。

    数据湖中没有申万行业指数(801xxx)的日线行情，故由成分股价格合成：
    取成分股每日收益的等权平均，累乘成指数(基点1000)作为 CLOSE。
    板块公式实际信号 XG=COND_MACD AND COND_LINE 只用 CLOSE，故此合成足够；
    open/high/low 由 close 派生，volume/amount 取成分股当日之和。
    注意：这是等权合成代理，并非官方申万行业指数点位，板块级信号为近似。
    """
    closes, vols, amts = {}, {}, {}
    for s in members:
        df = stock_panel.get(s)
        if df is None or len(df) < 2:
            continue
        g = df.set_index("date")
        closes[s] = g["close"]
        vols[s] = g["volume"]
        amts[s] = g["amount"]
    if not closes:
        return None

    close_mat = pd.DataFrame(closes).sort_index()
    eq_ret = close_mat.pct_change(fill_method=None).mean(axis=1)   # 等权日收益(自动跳过缺失成分)
    level = (1.0 + eq_ret.fillna(0.0)).cumprod() * 1000.0

    out = pd.DataFrame({"date": level.index, "close": level.values})
    out["open"] = out["close"].shift(1).fillna(out["close"])
    out["high"] = out[["open", "close"]].max(axis=1)
    out["low"] = out[["open", "close"]].min(axis=1)
    out["volume"] = pd.DataFrame(vols).sort_index().sum(axis=1).reindex(level.index).fillna(0).values
    out["amount"] = pd.DataFrame(amts).sort_index().sum(axis=1).reindex(level.index).fillna(0).values
    return out.reset_index(drop=True)


def _load_index_panel() -> dict:
    """建申万 L1 行业板块指数面板（由成分股等权合成）。"""
    global _INDEX_PANEL
    if _INDEX_PANEL is None:
        members = _load_members()
        sp = _load_stock_panel()
        panel = {}
        for board, mems in members.items():
            s = _synth_board_series(mems, sp)
            if s is not None and len(s) >= config.MIN_DAYS:
                panel[board] = s
        _INDEX_PANEL = panel
    return _INDEX_PANEL


# ---------------- 对外接口（与通达信后端同名同义） ----------------

def read_stock_daily(code: str):
    """读单只股票或申万行业指数的日线 DataFrame；不存在返回 None。"""
    code = str(code).strip()[:6]
    if code[:2] in _INDEX_PREFIXES:
        return _load_index_panel().get(code)
    return _load_stock_panel().get(code)


def scan_industry_indices() -> list:
    """申万 L1 行业指数列表（充当板块指数）。"""
    return [{"code": c, "exchange": "sw"} for c in sorted(_load_index_panel().keys())]


def scan_all_stocks() -> list:
    """全市场股票列表。"""
    return [{"code": c, "exchange": "sh" if c.startswith(("6", "9")) else "sz"}
            for c in sorted(_load_stock_panel().keys())]


def read_block_stocks_by_index(code: str):
    """某行业指数的成分股代码列表；无则返回 None。"""
    code = str(code).strip()[:6]
    return _load_members().get(code)


_NAME_MAP = None
_BOARD_NAME_MAP = None


def _member_file():
    fs = glob.glob(os.path.join(
        _lake(), "asset_class=index", "dataset=index_member_all", "**", "*.parquet"),
        recursive=True)
    return fs[0] if fs else None


def stock_name_map() -> dict:
    """{股票代码6: 名称}，取自申万成分股表（覆盖全部可选个股）。"""
    global _NAME_MAP
    if _NAME_MAP is None:
        _NAME_MAP = {}
        f = _member_file()
        if f:
            d = pd.read_parquet(f, columns=["ts_code", "name"])
            _NAME_MAP = {str(tc)[:6]: nm for tc, nm in zip(d["ts_code"], d["name"])}
    return _NAME_MAP


def board_name_map() -> dict:
    """{行业指数代码6: 申万L1行业名}。"""
    global _BOARD_NAME_MAP
    if _BOARD_NAME_MAP is None:
        _BOARD_NAME_MAP = {}
        f = _member_file()
        if f:
            d = pd.read_parquet(f, columns=["l1_code", "l1_name"]).drop_duplicates()
            _BOARD_NAME_MAP = {str(c)[:6]: n for c, n in zip(d["l1_code"], d["l1_name"])}
    return _BOARD_NAME_MAP
