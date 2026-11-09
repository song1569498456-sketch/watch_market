import json
BASE = r"D:\ds-arb-test\watch_market\evidence\BNB03\live-20261109T141903Z\raw"
d = json.load(open(BASE + r"\loops.json", encoding="utf-8"))
USDC = "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"
USDT = "0x55d398326f99059ff775485246999027b3197955"
DAI = "0x1af3f329e8be154074d8769d1ffa4ee058b1dbc3"
BUSD = "0xe9e7cea3dedca5984780bafc599bd69add087d56"
P = {k: {kk: (vv.lower() if isinstance(vv, str) and vv.startswith("0x") else vv) for kk, vv in v.items()} for k, v in d["pairs"].items()}
def dirs(st, t_in, t_out):
    t0 = (st.get("token0") or "").lower(); t1 = (st.get("token1") or "").lower()
    if t0 == t_in and t1 == t_out: return st.get("reserve0"), st.get("reserve1")
    if t0 == t_out and t1 == t_in: return st.get("reserve1"), st.get("reserve0")
    return None, None
def q(amount, r_in, r_out):
    if not amount or not r_in or not r_out: return 0
    ain = amount * 9975
    return (ain * r_out) // (r_in * 10000 + ain)
loops = []
for amt in [10**18, 10*10**18, 100*10**18, 1000*10**18]:
    p1, p2, p3 = P["USDC/USDT"], P["USDT/DAI"], P["DAI/USDC"]
    r1i, r1o = dirs(p1, USDC, USDT); b = q(amt, r1i, r1o)
    r2i, r2o = dirs(p2, USDT, DAI); c = q(b, r2i, r2o)
    r3i, r3o = dirs(p3, DAI, USDC); e = q(c, r3i, r3o)
    loops.append({"loop": "USDC->USDT->DAI->USDC", "amount_in_usdc": amt/1e18, "leg1_usdt": b/1e18,
                  "leg2_dai": c/1e18, "leg3_usdc": e/1e18, "net_usdc": (e-amt)/1e18,
                  "net_bps": ((e-amt)/amt*10000)})
    r3i2, r3o2 = dirs(p3, USDC, DAI); f = q(amt, r3i2, r3o2)
    r2i2, r2o2 = dirs(p2, DAI, USDT); g = q(f, r2i2, r2o2)
    r1i2, r1o2 = dirs(p1, USDT, USDC); h = q(g, r1i2, r1o2)
    loops.append({"loop": "USDC->DAI->USDT->USDC", "amount_in_usdc": amt/1e18, "leg1_dai": f/1e18,
                  "leg2_usdt": g/1e18, "leg3_usdc": h/1e18, "net_usdc": (h-amt)/1e18,
                  "net_bps": ((h-amt)/amt*10000)})
d["loops"] = loops
d["computational_correction"] = "上一轮 pairs.py 的比较用了 checksum 常量与链上小写地址比较失败导致 0 输出；本文件用 lowercased 地址重算（无新网络请求）。"
json.dump(d, open(BASE + r"\loops.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(loops, ensure_ascii=False, indent=1))
