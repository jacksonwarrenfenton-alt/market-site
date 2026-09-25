import sys, pandas as pd, numpy as np
sys.path.insert(0,'/root/pos')
import stockbee as SB, sbstats as SS, prices as P
b=pd.read_parquet('/root/pos/bars_deep.parquet')
print('deep bars', b.shape, b.date.min().date(), '->', b.date.max().date(), flush=True)
row,hist = SB.build(b, lookback=10**6)
print('stockbee history rows', len(hist), hist.index.min().date(), '->', hist.index.max().date(), flush=True)
hist.to_parquet('/root/pos/sb_hist_deep.parquet')
px=P.fetch_list(['SPY']); spy=px['SPY'].dropna()
print('spy', len(spy), spy.index.min().date(), '->', spy.index.max().date(), flush=True)
r=SS.build(hist, spy)
r.to_parquet('/root/pos/sbstats.parquet')
print('\ntests:', len(r), '| BH survivors:', int(r.bh.sum()), '| raw p<0.05:', int((r.p<0.05).sum()), flush=True)
print(r[['label','tail','horizon','n','n_eff','hit','med_excess','p','bh']].head(20).to_string(index=False), flush=True)
