#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
个股选股策略 —— 基线回测（事件式 / event-driven）

诚实假设：
  入场：信号触发日(收盘满足 个股选股.txt)的**次日开盘**买入（T+1 open）
  出场：持有 N 个交易日后的**开盘**卖出（T+1+N open）
  成本：买卖合计扣 COST_BPS 基点（佣金+滑点+印花税的粗略合计，默认 30bps）
  剔除：① 名称含 ST 的风险股  ② 次日为“一字板”(最高=最低)无法成交的入场
  基准：同一入场日、同一持有期，**全市场等权前向收益**（“随机买一只”基线），
        据此算策略的**超额收益**（成本对冲，超额与成本无关）。

只用 tushare 数据湖（全历史）。按股票 fork 并行，父进程建一次面板写时复制共享。

用法：
  python backtest.py                       # 默认 2018-01-01~2026-06-30, 持有5/10日
  python backtest.py --start 2020-01-01 --holds 5,10,20 --cost-bps 30
"""
import os
import re
import glob
import time
import argparse
import multiprocessing as mp

import numpy as np
import pandas as pd

import config
from data import tushare_source as ts
from formula.parser import parse_file
from formula.evaluator import Evaluator

# ---- fork 子进程共享的只读全局（父进程建好，fork 继承，不 pickle）----
_PANEL = None       # {code: df(date,open,high,low,close,volume,amount)}
_NAME = None        # {code: name}
_AST = None         # 个股公式 AST
_START = None       # np.datetime64 信号起
_END = None         # np.datetime64 信号止
_HOLDS = None       # [5, 10]
_COST = 0.0         # 单边合计成本(小数)


def _file_date(path: str) -> int:
    m = re.search(r"(\d{8})", os.path.basename(path))
    return int(m.group(1)) if m else 0


def _load_panel(start_load: int, end: int) -> dict:
    """读 [start_load, end] 区间内的按日 parquet，建 {code: 日线} 面板。"""
    pattern = os.path.join(config.TUSHARE_LAKE_DIR,
                           "asset_class=stock", "dataset=daily",
                           "freq=1d", "year=*", "month=*", "*.parquet")
    files = [f for f in sorted(glob.glob(pattern))
             if start_load <= _file_date(f) <= end]
    cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
    df = ts._read_many(files, cols)
    return ts._build_panel(df), len(files)


def _backtest_one(code):
    """对单只股票回测，返回成交记录列表 [(N, 入场日, code, 净收益), ...]。"""
    df = _PANEL.get(code)
    if df is None or len(df) < 130:
        return []
    if "ST" in _NAME.get(code, "").upper():
        return []
    try:
        sig = Evaluator(df).evaluate_series(_AST).values
    except Exception:
        return []

    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    dts = df["date"].values
    n = len(df)
    out = []
    for i in np.nonzero(sig)[0]:
        if dts[i] < _START or dts[i] > _END:
            continue
        e = i + 1                       # 次日入场
        if e >= n or h[e] == l[e] or o[e] <= 0:
            continue                    # 一字板/无法成交/异常价
        for N in _HOLDS:
            x = e + N                   # 持有 N 日后开盘卖
            if x >= n:
                continue
            ret = o[x] / o[e] - 1.0 - _COST
            out.append((N, str(dts[i])[:10], code, ret))
    return out


def _market_baseline(panel: dict, holds: list, cost: float) -> dict:
    """各 N 的“全市场等权前向收益”按日均值：{N: Series(index=信号日, 净收益)}。"""
    base = {}
    for N in holds:
        parts = []
        for df in panel.values():
            o = df["open"]
            fwd = o.shift(-1 - N) / o.shift(-1) - 1.0 - cost   # 与策略同口径(扣同样成本)
            parts.append(pd.DataFrame({"date": df["date"].values, "r": fwd.values}))
        allf = pd.concat(parts, ignore_index=True).dropna()
        base[N] = allf.groupby("date")["r"].mean()
    return base


def _fmt_pct(x):
    return f"{x*100:+.2f}%"


def _report(trades_df: pd.DataFrame, baseline: dict, holds: list, args):
    print("\n" + "=" * 72)
    print(f"  个股选股策略 — 基线回测报告")
    print(f"  信号区间 {args.start} ~ {args.end} | 入场T+1开盘 持有N日开盘卖 | 成本 {args.cost_bps}bps/笔")
    print("=" * 72)

    for N in holds:
        t = trades_df[trades_df["N"] == N]
        if t.empty:
            print(f"\n[持有 {N} 日]  无成交")
            continue
        r = t["ret"].values
        # 配对市场基线（每笔按其入场日对齐到全市场当日前向收益）
        t = t.copy()
        t["base"] = t["date"].map(baseline[N])
        paired = t.dropna(subset=["base"])
        base_mean = paired["base"].mean()
        excess = (paired["ret"] - paired["base"]).mean()

        ann = (1 + r.mean()) ** (244.0 / N) - 1     # 粗略年化(假设连续滚动)
        print(f"\n[持有 {N} 日]  成交 {len(r)} 笔")
        print(f"  胜率(>0)        {np.mean(r > 0)*100:.1f}%")
        print(f"  平均收益/笔     {_fmt_pct(r.mean())}      中位 {_fmt_pct(np.median(r))}")
        print(f"  分位 p25/p75    {_fmt_pct(np.percentile(r,25))} / {_fmt_pct(np.percentile(r,75))}")
        print(f"  最好/最差       {_fmt_pct(r.max())} / {_fmt_pct(r.min())}")
        print(f"  市场基线/笔     {_fmt_pct(base_mean)}  (同期全市场等权前向收益)")
        print(f"  >> 超额/笔      {_fmt_pct(excess)}      (策略 - 市场, 成本已对冲)")
        print(f"  粗略年化        {_fmt_pct(ann)}  (假设满仓连续滚动, 仅供参考)")
        # 逐年
        t = t.copy()
        t["year"] = t["date"].str.slice(0, 4)
        by = t.groupby("year")["ret"].agg(["count", "mean"])
        print("  逐年(笔数/均收益):  " +
              "  ".join(f"{y}:{int(row['count'])}/{row['mean']*100:+.1f}%"
                        for y, row in by.iterrows()))


def main():
    ap = argparse.ArgumentParser(description="个股选股策略基线回测")
    ap.add_argument("--start", default="2018-01-01", help="信号起始日")
    ap.add_argument("--end", default="2026-06-30", help="信号结束日")
    ap.add_argument("--holds", default="5,10", help="持有交易日数(逗号分隔)")
    ap.add_argument("--cost-bps", type=float, default=30, help="每笔买卖合计成本(基点), 默认30")
    ap.add_argument("--jobs", type=int, default=None, help="并行进程数(默认 cpu-2)")
    ap.add_argument("--formula", default=None, help="个股公式文件(默认 个股选股.txt)")
    args = ap.parse_args()

    global _PANEL, _NAME, _AST, _START, _END, _HOLDS, _COST
    _HOLDS = [int(x) for x in args.holds.split(",") if x.strip()]
    _COST = args.cost_bps / 10000.0
    _START = np.datetime64(args.start)
    _END = np.datetime64(args.end)
    _AST = parse_file(args.formula or config.STOCK_SELECT_FILE)

    start_load = (int(args.start[:4]) - 1) * 10000 + 101       # 多读一年做指标预热
    end_int = int(args.end.replace("-", ""))

    print(f"[数据源] tushare 数据湖: {config.TUSHARE_LAKE_DIR}")
    print(f"加载面板 {start_load//10000}~{args.end} ...")
    t0 = time.time()
    _PANEL, nfiles = _load_panel(start_load, end_int)
    _NAME = ts.stock_name_map()
    print(f"  面板: {len(_PANEL)} 只股票, {nfiles} 个交易日文件, 耗时 {time.time()-t0:.1f}s")

    jobs = args.jobs or max(1, (os.cpu_count() or 4) - 2)
    codes = list(_PANEL.keys())
    print(f"回测 {len(codes)} 只 (持有 {_HOLDS} 日), {jobs} 进程 ...")
    t0 = time.time()
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
    try:
        ctx = mp.get_context("fork")
    except ValueError:
        ctx = mp.get_context()
    with ctx.Pool(processes=jobs) as pool:
        results = pool.map(_backtest_one, codes, chunksize=max(1, len(codes) // (jobs * 8)))
    trades = [r for sub in results for r in sub]
    print(f"  成交 {len(trades)} 笔, 回测耗时 {time.time()-t0:.1f}s")

    print("计算市场基线 ...")
    baseline = _market_baseline(_PANEL, _HOLDS, _COST)

    trades_df = pd.DataFrame(trades, columns=["N", "date", "code", "ret"])
    _report(trades_df, baseline, _HOLDS, args)


if __name__ == "__main__":
    main()
