"""
通达信自定义板块安装器

把选股结果直接写进通达信 blocknew 目录，并登记到 blocknew.cfg，
这样用户重启通达信客户端后，即可在“自定义板块”中看到选出的板块/个股，
无需再手动复制 .blk 文件。

blocknew.cfg 格式（通达信自定义板块登记表）：
    文件由若干条定长记录拼接而成，每条 384 字节：
      偏移 0   长度 50   板块显示名称   (GBK, \\x00 补齐)
      偏移 50  长度 70   板块标识/文件名 (即 blocknew 下 {id}.blk 的 id，GBK)
      偏移 120 长度 2    板块类型        (uint16 小端，自定义板块取 0)
      偏移 122 长度 262  保留            (\\x00)

{id}.blk 为纯文本：每行 7 个字符 = 市场前缀(1) + 6 位代码，GBK 编码。
    市场前缀：1=上海(含科创板/板块指数)  0=深圳(含创业板)  2=北交所

注意：本模块对 blocknew.cfg 采用“读出全部记录 → 去掉同名旧记录 → 追加新记录 → 写回”，
      写回前会自动备份原文件；按板块名幂等，可安全重复运行。
"""
import os
import shutil
import subprocess
from datetime import datetime
from typing import List, Optional, Tuple

from config import TDX_BLOCK_DIR, TDX_BLOCKNEW_CFG

# 通达信主进程名（用于安装前检测客户端是否在运行）
_TDX_PROCESS_NAME = "TdxW.exe"

# blocknew.cfg 单条记录布局
_CFG_RECORD_SIZE = 384
_CFG_NAME_SIZE = 50      # 板块显示名称
_CFG_ID_SIZE = 70        # 板块标识（.blk 文件名，不含扩展名）
_CFG_TYPE_OFFSET = _CFG_NAME_SIZE + _CFG_ID_SIZE  # 120


def market_prefix(code: str) -> Optional[str]:
    """返回 6 位代码对应的通达信市场前缀；非法代码返回 None。"""
    code = code.strip()
    if not code.isdigit() or len(code) != 6:
        return None
    if code.startswith('88'):
        return '1'    # 板块指数（沪市）
    if code.startswith(('83', '87', '92', '43')):
        return '2'    # 北交所
    if code.startswith(('6', '9')):
        return '1'    # 上海主板/科创板/B股
    if code.startswith(('0', '3')):
        return '0'    # 深圳主板/创业板
    return '0'        # 兜底深圳


def write_blk_file(blk_path: str, codes: List[str]) -> int:
    """把代码列表写成通达信 .blk 文本（市场前缀+代码，每行一只）。返回有效行数。"""
    lines = []
    for code in codes:
        prefix = market_prefix(code)
        if prefix is None:
            continue
        lines.append(prefix + code.strip())
    os.makedirs(os.path.dirname(blk_path), exist_ok=True)
    with open(blk_path, 'w', encoding='gbk') as f:
        f.write('\n'.join(lines))
        if lines:
            f.write('\n')
    return len(lines)


def _gbk_field(text: str, size: int) -> bytes:
    """把字符串编码为定长 GBK 字节字段，超长按字节截断，不足 \\x00 补齐。"""
    raw = text.encode('gbk', errors='ignore')[:size]
    # 避免在多字节字符中间截断导致末尾半个汉字
    while raw:
        try:
            raw.decode('gbk')
            break
        except UnicodeDecodeError:
            raw = raw[:-1]
    return raw + b'\x00' * (size - len(raw))


def _build_cfg_record(block_name: str, blk_id: str, block_type: int = 0) -> bytes:
    """构造一条 384 字节的 blocknew.cfg 记录。"""
    rec = bytearray(_CFG_RECORD_SIZE)
    rec[0:_CFG_NAME_SIZE] = _gbk_field(block_name, _CFG_NAME_SIZE)
    rec[_CFG_NAME_SIZE:_CFG_NAME_SIZE + _CFG_ID_SIZE] = _gbk_field(blk_id, _CFG_ID_SIZE)
    rec[_CFG_TYPE_OFFSET] = block_type & 0xFF
    rec[_CFG_TYPE_OFFSET + 1] = (block_type >> 8) & 0xFF
    return bytes(rec)


def _parse_cfg_record(rec: bytes) -> Tuple[str, str]:
    """从一条记录中解析出 (板块名, 板块标识)。"""
    name = rec[0:_CFG_NAME_SIZE].split(b'\x00', 1)[0].decode('gbk', errors='ignore').strip()
    blk_id = rec[_CFG_NAME_SIZE:_CFG_NAME_SIZE + _CFG_ID_SIZE].split(b'\x00', 1)[0].decode('gbk', errors='ignore').strip()
    return name, blk_id


def _read_cfg_records(cfg_path: str) -> List[bytes]:
    """读取 blocknew.cfg，返回 384 字节记录列表（文件不存在则空列表）。"""
    if not os.path.isfile(cfg_path):
        return []
    with open(cfg_path, 'rb') as f:
        data = f.read()
    n = len(data) // _CFG_RECORD_SIZE
    return [data[i * _CFG_RECORD_SIZE:(i + 1) * _CFG_RECORD_SIZE] for i in range(n)]


def _backup(path: str) -> Optional[str]:
    """备份文件，返回备份路径。"""
    if not os.path.isfile(path):
        return None
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = f"{path}.{ts}.bak"
    shutil.copy2(path, bak)
    return bak


def update_blocknew_cfg(entries: List[Tuple[str, str]],
                        cfg_path: str = None,
                        block_type: int = 0) -> bool:
    """
    把若干 (板块名, 板块标识) 登记进 blocknew.cfg（读改写 + 备份 + 幂等）。

    同名或同标识的旧记录会被新记录替换，因此可安全重复运行。
    """
    cfg_path = cfg_path or TDX_BLOCKNEW_CFG
    records = _read_cfg_records(cfg_path)

    new_names = {name for name, _ in entries}
    new_ids = {blk_id for _, blk_id in entries}

    # 去掉与本次同名 / 同标识的旧记录
    kept = []
    for rec in records:
        name, blk_id = _parse_cfg_record(rec)
        if name in new_names or blk_id in new_ids:
            continue
        kept.append(rec)

    for name, blk_id in entries:
        kept.append(_build_cfg_record(name, blk_id, block_type))

    bak = _backup(cfg_path)
    if bak:
        print(f"  已备份 blocknew.cfg -> {os.path.basename(bak)}")
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, 'wb') as f:
        f.write(b''.join(kept))
    return True


def is_tdx_running() -> bool:
    """检测通达信主客户端（TdxW.exe）是否正在运行（仅 Windows 有效）。"""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {_TDX_PROCESS_NAME}"],
            capture_output=True, text=True, timeout=5,
        )
        return _TDX_PROCESS_NAME.lower() in out.stdout.lower()
    except Exception:
        # 检测失败时不阻断安装，交由调用方按需处理
        return False


def install_blocks(blocks: List[dict],
                   block_dir: str = None,
                   cfg_path: str = None) -> bool:
    """
    把选股结果安装进通达信 blocknew。

    Args:
        blocks: [{'blk_id': 'XG23062026', 'name': '260623个股', 'codes': [...]}, ...]
                blk_id 建议用 ASCII（作为 .blk 文件名 + cfg 标识），name 为客户端中显示的中文板块名。

    Returns:
        True 安装成功；False 跳过（如 blocknew 目录不存在 —— 通常意味着不在装有通达信的 Windows 上）。

    注意：通达信客户端在启动时把 blocknew.cfg 读入内存，运行期间不会热加载磁盘改动，
          且退出时可能以内存快照覆盖回写。因此安装必须在通达信「完全关闭」时进行，
          否则新板块不会显示。若检测到客户端在运行则中止（可用环境变量
          TDX_ALLOW_RUNNING=1 强制跳过该检查）。
    """
    block_dir = block_dir or TDX_BLOCK_DIR
    cfg_path = cfg_path or TDX_BLOCKNEW_CFG

    if not os.path.isdir(block_dir):
        print(f"\n  [跳过安装] 未找到通达信 blocknew 目录: {block_dir}")
        print(f"             （请确认已安装通达信，或通过环境变量 TDX_ROOT 指定正确路径）")
        return False

    if os.environ.get("TDX_ALLOW_RUNNING") != "1" and is_tdx_running():
        print(f"\n  [中止安装] 检测到通达信客户端（{_TDX_PROCESS_NAME}）正在运行。")
        print(f"             通达信启动时会缓存 blocknew.cfg，运行期间写入的新板块不会显示。")
        print(f"             请：① 完全退出通达信  ② 重新运行本脚本  ③ 再启动通达信查看。")
        print(f"             （如确需在运行时写入，可设置环境变量 TDX_ALLOW_RUNNING=1 跳过此检查）")
        return False

    print(f"\n  安装自定义板块到通达信: {block_dir}")
    entries = []
    for b in blocks:
        blk_id = b['blk_id']
        name = b['name']
        codes = b.get('codes', [])
        blk_path = os.path.join(block_dir, f"{blk_id}.blk")
        n = write_blk_file(blk_path, codes)
        entries.append((name, blk_id))
        print(f"    [OK] {name}  ({blk_id}.blk, {n} 只)")

    update_blocknew_cfg(entries, cfg_path=cfg_path)
    print(f"  已登记 {len(entries)} 个板块到 blocknew.cfg")
    print(f"  >> 请启动通达信客户端（安装已在其关闭时完成），在“自定义板块”中查看。")
    return True
