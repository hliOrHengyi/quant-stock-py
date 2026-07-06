"""
全局配置模块
所有路径、参数集中管理，方便用户调整。
注意：系统只读取通达信日线数据用于选股；写入仅限项目目录与
      通达信 blocknew 板块目录（用于自动安装选股结果）。

【唯一需要修改的全局变量】
    TDX_ROOT —— 通达信安装根目录。
    优先级：环境变量 TDX_ROOT > 本文件默认值。
    例：set TDX_ROOT=D:\通达信  (cmd)
        $env:TDX_ROOT="D:\通达信"  (PowerShell)
"""
import os
import platform
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# ========== 数据源选择（跨平台：Mac 读 tushare / Windows 读通达信） ==========

# 数据源: "auto" | "tdx" | "tushare"
#   auto    —— 按操作系统自动判断：macOS → tushare，Windows/其它 → 通达信
#   tdx     —— 强制读通达信本地 .day 数据
#   tushare —— 强制读 tushare parquet 数据湖
# 可被环境变量 DATA_SOURCE 或命令行 --data-source 覆盖。
DATA_SOURCE = os.environ.get("DATA_SOURCE", "auto")

# tushare 数据湖根目录（lake/ 目录，Hive 分区 parquet）
TUSHARE_LAKE_DIR = os.environ.get(
    "TUSHARE_LAKE_DIR", os.path.expanduser("~/quant-data/lake"))

# tushare 模式下，建面板时回看的交易日文件数（需 >114 以满足 MA(收盘,114)）
TUSHARE_LOOKBACK_DAYS = int(os.environ.get("TUSHARE_LOOKBACK_DAYS", "250"))


def active_data_source() -> str:
    """解析当前生效的数据源（把 auto 落地为 tdx / tushare）。"""
    ds = (DATA_SOURCE or "auto").lower()
    if ds in ("tdx", "tushare"):
        return ds
    return "tushare" if platform.system() == "Darwin" else "tdx"

# ========== 通达信安装根目录（唯一全局变量，可被环境变量覆盖） ==========

# 通达信安装根目录。改这里（或设置环境变量 TDX_ROOT）即可整体切换。
TDX_ROOT = os.environ.get("TDX_ROOT", r"C:\通达信")

# ---------- 以下路径全部由 TDX_ROOT 派生，无需单独修改 ----------

# 日线数据目录（只读）
TDX_LDAY_SH = os.path.join(TDX_ROOT, "vipdoc", "sh", "lday")   # 上海股票 + 沪市板块指数
TDX_LDAY_SZ = os.path.join(TDX_ROOT, "vipdoc", "sz", "lday")   # 深圳股票 + 深市板块指数

# 板块文件目录（通达信新版自定义板块存储路径，选股结果写入此处）
TDX_BLOCK_DIR = os.path.join(TDX_ROOT, "T0002", "blocknew")

# blocknew 板块索引配置文件（自定义板块登记表）
TDX_BLOCKNEW_CFG = os.path.join(TDX_BLOCK_DIR, "blocknew.cfg")

# 行情缓存目录（股票名称 / 概念等元数据）
TDX_HQ_CACHE = os.path.join(TDX_ROOT, "T0002", "hq_cache")

# ========== 选股公式文件路径 ==========

# 默认板块选择公式文件
INDUSTRY_SELECT_FILE = os.path.join(PROJECT_ROOT, "板块选择.txt")

# 默认个股选择公式文件
STOCK_SELECT_FILE = os.path.join(PROJECT_ROOT, "个股选股.txt")

# ========== 输出路径（写入当前项目目录） ==========

# 默认输出板块文件
OUTPUT_BLOCK_FILE = os.path.join(PROJECT_ROOT, "dailyresult", "日期选股.blk")

# 是否备份已有的输出文件
BACKUP_OUTPUT = True

# 是否在选股结束后自动把 .blk 安装进通达信 blocknew（可被命令行 --no-install 关闭）
AUTO_INSTALL_TO_TDX = True

# ========== 股票数据参数 ==========

# 日线数据中保留的最少天数（不足则跳过）
MIN_DAYS = 30

# 板块指数代码前缀（通达信行业板块指数以 88 开头）
INDUSTRY_INDEX_PREFIX = "88"
