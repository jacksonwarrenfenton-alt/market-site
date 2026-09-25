"""Everything the board knows about one ticker, pre-joined into a lookup index.

The site holds five separate views of the market -- COT positioning, ETF flows,
short interest, subsector relative strength and the TradingView cross-check --
and each is keyed differently. Asking "what does this site say about NVDA"
currently means reading four panels and doing the join in your head. This builds
that join once, server-side, so the page can answer it instantly.

It also FLAGS. A lookup that silently returns three of five datasets looks the
same as one where two genuinely have nothing to say, and those are very
different. Every entry carries what is missing and why.
"""
import pandas as pd, numpy as np, json, os, sys

D = os.path.expanduser("~/pos")


def _f(v, nd=2):
    try:
        v = float(v)
        return None if not np.isfinite(v) else round(v, nd)
    except Exception:
        return None


def build(sub=None):
    sys.path.insert(0, D)
    import universe as U
    idx = {}

    def ent(t):
        return idx.setdefault(t.upper(), {"t": t.upper(), "flags": []})

    # ---- 1. COT futures ------------------------------------------------
    cot_n = 0
    try:
        cb = pd.read_parquet(f"{D}/cot_built.parquet")
        cur = cb.sort_values("date").groupby("cftc_contract_market_code").tail(1)
        for _, r in cur.iterrows():
            code = r["cftc_contract_market_code"]
            tk = (U.PRICE_MAP.get(code) or (None, None))[0]
            if not tk: continue
            e = ent(tk)
            e["cot"] = {
                "name": str(r.get("contract_market_name") or code),
                "asof": str(pd.Timestamp(r["date"]).date()),
                "ls": _f(r.get("ls_pctile52")), "ss": _f(r.get("ss_pctile52")),
                "comm": _f(r.get("comm_pctile52")), "oi": _f(r.get("oi_pctile52")),
            }
            cot_n += 1
    except Exception as e:
        print("cot index failed:", e, flush=True)

    # ---- 2. ETF basket membership + latest flow -------------------------
    flow_n = 0
    try:
        import flows as F
        fl, _ = F.basket_flows()
        last = fl[fl.date == fl.date.max()] if fl is not None and len(fl) else None
        bmap = {}
        if last is not None:
            for _, r in last.iterrows():
                bmap[r["basket"]] = {
                    "pct_1m": _f(r.get("pct_1m")), "z_1m": _f(r.get("z_1m")),
                    "flow_1m": _f(r.get("flow_1m"), 0),
                    "asof": str(pd.Timestamp(fl.date.max()).date()),
                }
        for b, syms in U.ETF_BASKETS.items():
            for s in syms:
                e = ent(s)
                e["etf"] = {"basket": b, **(bmap.get(b) or {})}
                e["etf"]["inverse"] = s in getattr(U, "INVERSE_ETFS", set())
                flow_n += 1
    except Exception as e:
        print("flow index failed:", e, flush=True)

    # ---- 3. Short interest ---------------------------------------------
    si_n = 0
    try:
        p = f"{D}/si_latest.parquet"
        if os.path.exists(p):
            sl = pd.read_parquet(p)
            for _, r in sl.iterrows():
                e = ent(str(r["symbol"]))
                e["si"] = {"si": _f(r.get("si"), 0), "dtc": _f(r.get("dtc")),
                           "pct_chg": _f(r.get("pct_chg")), "chg_z": _f(r.get("chg_z")),
                           "level_z": _f(r.get("level_z")),
                           "settle": str(r.get("settle"))[:10]}
                si_n += 1
    except Exception as e:
        print("si index failed:", e, flush=True)

    # ---- 4. Subsector group membership + the group's own reading --------
    grp_n = 0
    gmeta = {}
    try:
        if sub is not None and len(sub):
            legs = [k for k, _l, _d in getattr(sub, "attrs", {}).get("legs", [])] or []
            for _, r in sub.iterrows():
                gmeta[str(r["name"])] = {
                    "rank": int(r["rank"]), "n": int(r["n"]),
                    "rs_m": _f(r.get("rs_m")), "rs_q": _f(r.get("rs_q")),
                    "rs_rank": int(r["rs_rank"]) if np.isfinite(r.get("rs_rank", np.nan)) else None,
                    "ew_rank": int(r["ew_rank"]) if np.isfinite(r.get("ew_rank", np.nan)) else None,
                    "conf_n": int(r["c_n"]) if np.isfinite(r.get("c_n", np.nan)) else None,
                    "conf_cov": int(r["c_cov"]) if np.isfinite(r.get("c_cov", np.nan)) else None,
                    "conf_dir": int(r["c_dir"]) if np.isfinite(r.get("c_dir", np.nan)) else 0,
                    "spread": _f(r.get("c_spread"), 0),
                    "legs": {k: _f(r.get(f"L_{k}"), 0) for k in
                             ("med", "ew", "short", "long", "thrust", "bread",
                              "flow", "si", "tv")},
                }
        roster = f"{D}/custom176-rosters.txt"
        if os.path.exists(roster):
            for line in open(roster):
                if "|" not in line: continue
                name, syms = line.split("|", 1)
                name = name.strip()
                for s in syms.strip().split(","):
                    s = s.strip().upper()
                    if not s: continue
                    e = ent(s)
                    e.setdefault("groups", []).append(name)
                    grp_n += 1
    except Exception as e:
        print("group index failed:", e, flush=True)

    # ---- 5. flags -------------------------------------------------------
    for t, e in idx.items():
        f = e["flags"]
        has = [k for k in ("cot", "etf", "si", "groups") if e.get(k)]
        if not has:
            f.append(("none", "no dataset on this board covers this ticker"))
        if "groups" in e and len(e["groups"]) > 1:
            f.append(("overlap", f"sits in {len(e['groups'])} groups — the "
                                 "TradingView leg still votes once"))
        if e.get("si") and e["si"].get("chg_z") is not None:
            z = e["si"]["chg_z"]
            if z is not None and abs(z) >= 2:
                f.append(("si", f"short interest change is {z:+.1f} sigma — "
                                f"{'covering' if z < 0 else 'building'} hard"))
        if e.get("cot"):
            for k, lab in (("ls", "large specs"), ("comm", "commercials")):
                v = e["cot"].get(k)
                if v is not None and (v >= 90 or v <= 10):
                    f.append(("cot", f"{lab} at percentile {v:.0f} of its 52-week range"))
        if e.get("etf") and e["etf"].get("z_1m") is not None:
            z = e["etf"]["z_1m"]
            if abs(z) >= 2:
                f.append(("flow", f"basket flow {z:+.1f} sigma on the month"))
    out = {"idx": idx, "groups": gmeta,
           "built": str(pd.Timestamp.today().date()),
           "counts": {"cot": cot_n, "etf": flow_n, "si": si_n, "grp": grp_n,
                      "tickers": len(idx)}}
    return out


def save(sub=None):
    o = build(sub)
    with open(f"{D}/tickerdesk.json", "w") as f:
        json.dump(o, f, separators=(",", ":"))
    print("ticker desk:", o["counts"], flush=True)
    return o
