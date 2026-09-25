# Curated COT universe: code -> (display name, asset class)
COT_UNIVERSE = {
    "134741": ("SOFR 3M",            "Rates"),
    "134742": ("SOFR 1M",            "Rates"),
    "045601": ("Fed Funds 30D",      "Rates"),
    "042601": ("UST 2Y",             "Rates"),
    "044601": ("UST 5Y",             "Rates"),
    "043602": ("UST 10Y",            "Rates"),
    "043607": ("Ultra 10Y",          "Rates"),
    "020601": ("UST Bond (30Y)",     "Rates"),
    "020604": ("Ultra Bond",         "Rates"),
    "098662": ("US Dollar Index",    "FX"),
    "099741": ("Euro FX",            "FX"),
    "097741": ("Japanese Yen",       "FX"),
    "096742": ("British Pound",      "FX"),
    "090741": ("Canadian Dollar",    "FX"),
    "232741": ("Australian Dollar",  "FX"),
    "112741": ("NZ Dollar",          "FX"),
    "092741": ("Swiss Franc",        "FX"),
    "095741": ("Mexican Peso",       "FX"),
    "102741": ("Brazilian Real",     "FX"),
    "088691": ("Gold",               "Metals"),
    "084691": ("Silver",             "Metals"),
    "085692": ("Copper",             "Metals"),
    "076651": ("Platinum",           "Metals"),
    "075651": ("Palladium",          "Metals"),
    "191693": ("Aluminum MWP",       "Metals"),
    "067651": ("WTI Crude",          "Energy"),
    "06765T": ("Brent Crude",        "Energy"),
    "023651": ("Nat Gas (NYMEX)",    "Energy"),
    "111659": ("RBOB Gasoline",      "Energy"),
    "022651": ("NY Harbor ULSD",     "Energy"),
    "06665O": ("Propane",            "Energy"),
    "002602": ("Corn",               "Ags"),
    "005602": ("Soybeans",           "Ags"),
    "007601": ("Soybean Oil",        "Ags"),
    "026603": ("Soybean Meal",       "Ags"),
    "001602": ("Wheat SRW",          "Ags"),
    "001612": ("Wheat HRW",          "Ags"),
    "057642": ("Live Cattle",        "Ags"),
    "061641": ("Feeder Cattle",      "Ags"),
    "054642": ("Lean Hogs",          "Ags"),
    "135731": ("Canola",             "Ags"),
    "080732": ("Sugar #11",          "Softs"),
    "033661": ("Cotton #2",          "Softs"),
    "073732": ("Cocoa",              "Softs"),
    "083731": ("Coffee C",           "Softs"),
    "040701": ("Orange Juice",       "Softs"),
    "058644": ("Lumber",             "Softs"),
    "13874+": ("S&P 500 (consol)",   "Equity"),
    "20974+": ("Nasdaq 100 (consol)","Equity"),
    "239742": ("Russell 2000",       "Equity"),
    "12460+": ("Dow Jones",          "Equity"),
    "33874A": ("S&P 400 MidCap",     "Equity"),
    "244042": ("MSCI EM",            "Equity"),
    "244041": ("MSCI EAFE",          "Equity"),
    "240743": ("Nikkei (yen)",       "Equity"),
    "1170E1": ("VIX Futures",        "Equity"),
    "13874I": ("S&P Technology",     "Sectors"),
    "13874C": ("S&P Financials",     "Sectors"),
    "138749": ("S&P Energy",         "Sectors"),
    "13874E": ("S&P Health Care",    "Sectors"),
    "13874F": ("S&P Industrials",    "Sectors"),
    "13874J": ("S&P Utilities",      "Sectors"),
    "138748": ("S&P Cons Staples",   "Sectors"),
    "13874P": ("S&P Comm Svcs",      "Sectors"),
    "133741": ("Bitcoin (CME)",      "Crypto"),
    "133742": ("Micro Bitcoin",      "Crypto"),
    "146021": ("Ether (CME)",        "Crypto"),
    "146022": ("Micro Ether",        "Crypto"),
    "176740": ("XRP (CME)",          "Crypto"),
    "221602": ("Bloomberg Cmdty Idx","Commodity Index"),
}

CLASS_ORDER = ["Rates","FX","Metals","Energy","Ags","Softs","Equity","Sectors",
               "Crypto","Commodity Index"]

# ETF baskets: theme -> list of tickers.
ETF_BASKETS = {
    "Semiconductors":   ["SMH","SOXX","XSD","PSI","SOXQ","FTXL"],
    # PATCH E1a: TQQQ/SQQQ/QID/QLD/SSO moved to the index-leverage baskets.
    # TECL/TECS (sector 3x) and FNGU/FNGD (FANG+ thematic) deliberately stay.
    "Technology":       ["XLK","VGT","IYW","FTEC","IGM","QTEC","HACK","CIBR","BUG",
                         "BOTZ","ROBO","IRBO","AIQ","QTUM"],
    "Financials":       ["XLF","VFH","IYF","KRE","KBE","IAT","KBWB","KIE","IAK","KBWP","FNCL","IYG","RSPF"],
    "Health Care":      ["XLV","VHT","IYH","IBB","XBI","IHI","FHLC","PPH","BBH","XHE"],
    "Energy":           ["XLE","VDE","IYE","XOP","OIH","IEO","FENY","PXE","XES","AMLP",
                         "MLPX","EMLP","FCG","UCO","SCO","BOIL","KOLD"],
    "Industrials":      ["XLI","VIS","IYJ","ITA","XAR","PAVE","FIDU","PPA","JETS","BOAT"],
    "Consumer Disc":    ["XLY","VCR","IYC","XRT","FDIS","RTH","IBUY","ITB","XHB"],
    "Cons Staples":     ["XLP","VDC","IYK","FSTA","KXI","PBJ","FTXG"],
    "Utilities":        ["XLU","VPU","IDU","FUTY","JXI","RSPU","GRID"],
    "Real Estate":      ["XLRE","VNQ","IYR","SCHH","REZ","FREL"],
    "Comm Services":    ["XLC","VOX","IYZ","FCOM","SOCL","XTL"],
    "Precious Metals":  ["GLD","IAU","GLDM","SLV","SIVR","PPLT","PALL",
                         "GDX","GDXJ","SIL","SILJ","RING","GOAU","SGDM","SLVP",
                         "AGQ","ZSL","UGL","GLL"],
    "Industrial & Rare Metals": ["COPX","CPER","XME","PICK","REMX","LIT","SLX",
                                 "URA","URNM","URNJ","NLR","NUKZ"],
    "Agriculture":      ["CORN","WEAT","SOYB","CANE","TAGS","DBA",
                         "MOO","VEGI","FTAG","PAGG"],
    "Broad Commodity":  ["DBC","PDBC","GSG","DJP","COMT","FTGC","DBB","DBP","USO","UNG"],
    # PATCH E1a: the eighteen levered/inverse index funds are gone from here.
    # What remains is the clean unlevered core, which is what this basket was
    # always supposed to measure.
    "Broad US Equity":  ["SPY","IVV","VOO","QQQ","IWM","DIA","VTI","RSP"],
    # ---- index leverage, split out from the cash baskets (PATCH E1a) ----
    # Levered and inverse INDEX funds only. Sector leverage (SOXL/SOXS, FAS/FAZ,
    # LABU/LABD, ERX/ERY, NUGT/DUST, TECL/TECS) deliberately stays inside its own
    # sector basket: there the leverage IS the sector expression. Here the fund is
    # a bet on market direction and nothing else, which is why it earns its own
    # bucket. Every ticker below was already tracked, so etfdb flow history covers
    # all of them and audit check 7 stays green.
    "Index Long (leveraged)":  ["SPXL","UPRO","SSO","SPUU","QLD","TQQQ",
                                "TNA","URTY","MIDU","UDOW","DDM","UWM"],
    "Index Short (inverse)":   ["SPXS","SPXU","SH","SDS","SQQQ","QID","PSQ",
                                "TZA","TWM","RWM","SRTY","DOG","SDOW",
                                "DXD","MYY","EUM","EFZ"],
    "Intl / EM":        ["EEM","VWO","IEMG","EFA","IEFA","VEA","EWJ","EWZ","INDA",
                         "DXJ","ILF","EWW","INDY","EPI","EMXC","EWY","EWT","EZA","TUR"],
    "China":            ["FXI","KWEB","CQQQ","MCHI","ASHR","GXC","PGJ","CXSE","CHIQ","CHIX",
                         "KBA","ASHS","ECNS","CNYA","KURE","KTEC","CHIK","CWEB","YINN","YANG",
                         "FXP","CHAU","EWH","KALL","CNXT","CHIE","CHII","CHIM"],
    "Rates - Long":     ["TLT","EDV","VGLT","SPTL","ZROZ","TMF","TMV","TBT","TBF","TTT","UBT",
                         "GOVZ","VGIT","IEF","TLH","SPTI"],
    "Rates - Short":    ["SHY","SGOV","BIL","VGSH","SCHO"],
    "Credit":           ["LQD","HYG","JNK","VCIT","VCSH","SJNK","BKLN"],
    "Crypto":           ["IBIT","FBTC","GBTC","ETHA","BITO","BLOK","WGMI","BITQ","DAPP",
                         "ARKB","BITB","HODL","BRRR","EZBC","BTCO","ETHW","ETHV","FETH",
                         "QETH","CETH","BSOL","GSOL","SSK","XRPR","GXRP","XXRP",
                         "BITX","BITI","ETHU","ETHD","CONL","MSTX","MSTZ","BTCL","BTCZ",
                         "ETQ","SOLT","SOLZ"],
    "Clean Energy":     ["TAN","ICLN","QCLN","PBW","ACES","FAN"],

    # ---- SECTOR leverage, split out of the sector baskets ----
    # Levered and inverse ETFs on EQUITY SECTORS AND INDUSTRIES only. The index
    # versions already live in "Index Long (leveraged)" / "Index Short (inverse)";
    # this is the sector-level twin. Same reasoning as the index split: a 3x fund's
    # creations are a leverage-demand signal, not a sector-allocation signal, and
    # they are violent enough to swamp the underlying basket in exactly the weeks
    # that matter. Leverage on commodities (UCO/SCO/BOIL/KOLD/AGQ/ZSL/UGL/GLL),
    # duration (TMF/TMV/TBT/TBF/TTT/UBT), crypto (BITX/BITI/CONL/MSTX...) and the
    # China country funds (YINN/YANG/FXP/CWEB/CHAU) deliberately STAYS in its own
    # complex, where the leverage IS the expression of that asset class.
    "Sector Long (leveraged)":  ["SOXL", "USD", "TECL", "FNGU", "FAS", "DPST", "LABU", "CURE", "PILL", "ERX", "GUSH", "NRGU", "DFEN", "DUSL", "NAIL", "RETL", "WANT", "UTSL", "DRN", "NUGT", "JNUG"],
    "Sector Short (inverse)":   ["SOXS", "SSG", "TECS", "FNGD", "FAZ", "SKF", "LABD", "ERY", "DRIP", "DUG", "DRV", "DUST", "JDST"],
    # ---- factor and sentiment baskets ----
    # MOMENTUM FACTOR. The thing jman's whole book rides on, tracked as a flow
    # rather than a price ratio. MTUM/JMOM/PDP/QMOM/FDMO are the five on the
    # StockCharts panel; SPMO/VFMO/XMMO/DWAS round out the US momentum complex.
    # Deliberately excludes IMTM (international) and PTF (sector momentum) -- both
    # are different exposures and would blur the read.
    "Momentum Factor":  ["MTUM","JMOM","PDP","QMOM","FDMO","SPMO","VFMO","XMMO","DWAS"],

    # ARKK & SPECULATIVE RETAIL. The whole ARK complex plus the retail-sentiment
    # vehicles. This is a risk-appetite gauge, not a sector: when money leaves
    # here first it usually leads the high-beta unwind.
    "ARKK & Spec Retail": ["ARKK","ARKW","ARKG","ARKQ","ARKF","ARKX","PRNT","IZRL",
                           "MEME","BUZZ","TARK","SARK"],
}

PRICE_MAP = {
    "042601": ("ZT=F", False), "044601": ("ZF=F", False), "043602": ("ZN=F", False),
    "043607": ("TN=F", False), "020601": ("ZB=F", False), "020604": ("UB=F", False),
    "098662": ("DX-Y.NYB", False), "099741": ("6E=F", False), "097741": ("6J=F", False),
    "096742": ("6B=F", False), "090741": ("6C=F", False), "232741": ("6A=F", False),
    "112741": ("6N=F", False), "092741": ("6S=F", False), "095741": ("6M=F", False),
    "102741": ("6L=F", False),
    "088691": ("GLD", True), "084691": ("SLV", True), "085692": ("HG=F", False),
    "076651": ("PPLT", True), "075651": ("PALL", True), "191693": ("ALI=F", False),
    "067651": ("CL=F", False), "06765T": ("BZ=F", False), "023651": ("NG=F", False),
    "111659": ("RB=F", False), "022651": ("HO=F", False),
    "002602": ("ZC=F", False), "005602": ("ZS=F", False), "007601": ("ZL=F", False),
    "026603": ("ZM=F", False), "001602": ("ZW=F", False), "001612": ("KE=F", False),
    "057642": ("LE=F", False), "061641": ("GF=F", False), "054642": ("HE=F", False),
    "080732": ("SB=F", False), "033661": ("CT=F", False), "073732": ("CC=F", False),
    "083731": ("KC=F", False), "040701": ("OJ=F", False), "058644": ("LBR=F", False),
    "13874+": ("ES=F", False), "20974+": ("NQ=F", False), "239742": ("RTY=F", False),
    "12460+": ("YM=F", False), "240743": ("NIY=F", False), "1170E1": ("^VIX", False),
    "33874A": ("MDY", True), "244042": ("EEM", True), "244041": ("EFA", True),
    "13874I": ("XLK", True), "13874C": ("XLF", True), "138749": ("XLE", True),
    "13874E": ("XLV", True), "13874F": ("XLI", True), "13874J": ("XLU", True),
    "138748": ("XLP", True), "13874P": ("XLC", True),
    "133741": ("BTC-USD", True), "133742": ("BTC-USD", True),
    "146021": ("ETH-USD", True), "146022": ("ETH-USD", True),
    "176740": ("XRP-USD", True),
    "221602": ("DJP", True),
}

BASKET_PROXY = {
    "Semiconductors": "SMH", "Technology": "XLK", "Financials": "XLF",
    "Health Care": "XLV", "Energy": "XLE", "Industrials": "XLI",
    "Consumer Disc": "XLY", "Cons Staples": "XLP", "Utilities": "XLU",
    "Real Estate": "XLRE", "Comm Services": "XLC",
    "Precious Metals": "GLD", "Industrial & Rare Metals": "XME",
    "Agriculture": "DBA", "Broad Commodity": "DBC",
    "Broad US Equity": "SPY", "Intl / EM": "EEM",
    "Rates - Long": "TLT", "Rates - Short": "SHY", "Credit": "LQD",
    "Crypto": "IBIT", "Clean Energy": "ICLN", "China": "FXI",
    "Momentum Factor": "MTUM", "ARKK & Spec Retail": "ARKK",
    "Sector Long (leveraged)": "SOXL", "Sector Short (inverse)": "SPY",
    # PATCH E1a — proxy must be a member of its own basket (audit check 3)
    "Index Long (leveraged)": "TQQQ", "Index Short (inverse)": "SPY",
}

INVERSE_ETFS = {
    "SOXS","SSG","SQQQ","QID","PSQ","TECS","FAZ","SKF","ERY","DRIP","DUG",
    "DUST","JDST","ZSL","GLL","SH","SDS","SPXS","SPXU","TZA","RWM","DOG",
    "TMV","TBT","TBF","TTT","BITI","YANG","FXP",
    "ETHD","MSTZ","BTCZ","SOLZ","SCO","KOLD","LABD","DRV","SRTY","SDOW","TWM",
    "SARK","DXD","MYY","EUM","EFZ",
}

# Baskets whose price proxy is deliberately NOT a member: an inverse basket should
# chart the thing being SHORTED, not the decaying inverse fund. A 3x inverse like
# SQQQ bleeds to the bottom-right of every chart and tells you nothing about where
# price was when the crowd piled in. Flow for these baskets is sign-flipped (see
# flows.per_etf_weekly) so the line reads as NET LONG-EQUIVALENT positioning:
# deep negative = crowd maximally short = contrarian buy at price lows.
PROXY_NOT_MEMBER = {"Index Short (inverse)", "Sector Short (inverse)"}
