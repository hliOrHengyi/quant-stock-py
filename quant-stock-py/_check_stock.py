import sys
sys.path.insert(0,"D:/Code/quant-stock-py")
from data.block_reader import _get_infoharbor_mapping

m=_get_infoharbor_mapping()
print(f"共有 {len(m)} 个板块指数有成分股")
print(f"880646 (复合铜箔): {m.get('880646',[]) }")
print(f"880646 成分股数: {len(m.get('880646',[]))}")
print(f"301217 在其中: {'301217' in m.get('880646',[])}")

# Show first 5 indices
for i,code in enumerate(sorted(m.keys())[:5]):
    print(f"  {code}: {len(m[code])} 只")