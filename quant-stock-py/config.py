"""
全局配置模块
所有路径、参数集中管理，方便用户调整。
注意：系统只读取 C 盘通达信数据，从不写入 C 盘。
"""
import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

# ========== 通达信数据路径（只读） ==========

# 通达信安装根目录
TDX_ROOT = r"C:\通达信"

# 日线数据目录
TDX_LDAY_SH = os.path.join(TDX_ROOT, r"vipdoc\sh\lday")   # 上海股票 + 沪市板块指数
TDX_LDAY_SZ = os.path.join(TDX_ROOT, r"vipdoc\sz\lday")   # 深圳股票 + 深市板块指数

# 板块文件目录（通达信新版板块存储路径）
TDX_BLOCK_DIR = os.path.join(TDX_ROOT, r"T0002\blocknew")

# ========== 选股公式文件路径 ==========

# 默认板块选择公式文件
INDUSTRY_SELECT_FILE = os.path.join(PROJECT_ROOT, "板块选择.txt")

# 默认个股选择公式文件
STOCK_SELECT_FILE = os.path.join(PROJECT_ROOT, "个股选股.txt")

# ========== 输出路径（写入当前项目目录，不碰 C 盘） ==========

# 默认输出板块文件
OUTPUT_BLOCK_FILE = os.path.join(PROJECT_ROOT, "日期选股.blk")

# 是否备份已有的输出文件
BACKUP_OUTPUT = True

# ========== 股票数据参数 ==========

# 日线数据中保留的最少天数（不足则跳过）
MIN_DAYS = 30

# 板块指数代码前缀（通达信行业板块指数以 88 开头）
INDUSTRY_INDEX_PREFIX = "88"