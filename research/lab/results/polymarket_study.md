# Polymarket study (Y4), run 2026-10-21

Pre-registration: `results/polymarket_prereg.md`. Narrative and verdict: `results/polymarket.md`.

## Data

Universe: 1,089,674 closed markets with at least $1,000 of volume, 1,084,133 of them resolved to one side. Sampled with price history: 75,554; in the panel 74,751 markets of 30,405 events, 2,445,333 market states from 2022-11-18 to 2026-10-21. Data folder 223.4 MB.

| Year | Markets | States |
|---|---|---|
| 2022 | 39 | 682 |
| 2023 | 1,423 | 51,597 |
| 2024 | 10,818 | 357,151 |
| 2025 | 30,816 | 924,584 |
| 2026 | 37,086 | 1,111,319 |

| Category | Markets | States |
|---|---|---|
| crypto | 9,293 | 194,524 |
| culture | 8,008 | 186,668 |
| economics | 3,670 | 194,576 |
| finance | 5,803 | 165,565 |
| geopolitics | 6,909 | 317,695 |
| mentions | 7,191 | 107,276 |
| other | 456 | 11,194 |
| politics | 7,917 | 454,511 |
| sports | 13,701 | 567,166 |
| tech | 5,097 | 153,744 |
| weather | 6,706 | 92,414 |

## B1. Favourite/longshot

Outcome rate against the mean price per bucket, each market weighing one, reweighted to the universe; 95 % band from resampling whole events.

| Price bucket | Markets | Mean price | Won | 95 % band | Won minus price |
|---|---|---|---|---|---|
| 0-2 | 42,312 | 0.5 % | 0.4 % | 0.2 % to 0.6 % | -0.1 % |
| 2-5 | 31,724 | 3.2 % | 2.5 % | 1.2 % to 4.7 % | -0.8 % |
| 5-10 | 29,608 | 7.1 % | 6.1 % | 4.1 % to 8.7 % | -1.0 % |
| 10-20 | 31,018 | 14.6 % | 14.4 % | 11.5 % to 17.6 % | -0.2 % |
| 20-35 | 33,471 | 27.3 % | 25.7 % | 22.9 % to 28.6 % | -1.6 % |
| 35-50 | 35,424 | 44.8 % | 38.4 % | 35.3 % to 41.6 % | -6.4 % |
| 50-65 | 31,952 | 51.1 % | 51.3 % | 48.0 % to 55.0 % | +0.2 % |
| 65-80 | 14,683 | 71.7 % | 64.9 % | 59.6 % to 70.5 % | -6.8 % |
| 80-90 | 9,786 | 84.1 % | 84.3 % | 76.9 % to 89.9 % | +0.1 % |
| 90-95 | 6,957 | 92.2 % | 93.6 % | 89.6 % to 96.5 % | +1.4 % |
| 95-98 | 5,975 | 96.5 % | 95.6 % | 92.0 % to 97.9 % | -0.9 % |
| 98-100 | 10,779 | 99.6 % | 99.7 % | 99.4 % to 99.9 % | +0.1 % |


Calibration line `logit P(win) = a + b logit(p)`: a -0.067 (se 0.052), b 1.019 (se 0.035). b below 1 means longshots are too dear and favourites too cheap; above 1 the reverse.

## B2. Drift to resolution

| Days to end | Markets | a | b (se) | Market Brier |
|---|---|---|---|---|
| <1d | 56,252 | +0.016 | 1.016 (0.042) | 0.1742 |
| 1-3d | 51,478 | -0.110 | 1.008 (0.044) | 0.1563 |
| 3-7d | 44,033 | -0.258 | 0.986 (0.048) | 0.1640 |
| 7-30d | 33,458 | -0.286 | 1.012 (0.077) | 0.1929 |
| 30-90d | 18,293 | -0.394 | 1.116 (0.051) | 0.1035 |
| >90d | 10,213 | -0.399 | 1.129 (0.031) | 0.0876 |

## B3. Category and kind

| Category | Kind | Markets | a | b (se) | Market Brier |
|---|---|---|---|---|---|
| crypto | event | 7,780 | -0.240 | 0.997 (0.026) | 0.0816 |
| crypto | game | 723 | +0.176 | 0.825 (0.048) | 0.0754 |
| crypto | updown | 790 | +0.070 | 1.016 (0.173) | 0.2471 |
| culture | event | 6,805 | -0.316 | 1.123 (0.031) | 0.0758 |
| culture | game | 1,203 | -0.338 | 0.934 (0.067) | 0.0718 |
| economics | event | 3,544 | +0.051 | 1.088 (0.038) | 0.1011 |
| economics | game | 123 | -0.142 | 1.112 (0.144) | 0.1092 |
| finance | event | 4,170 | -0.143 | 1.160 (0.035) | 0.1115 |
| finance | game | 1,073 | +0.075 | 0.667 (0.040) | 0.1943 |
| finance | updown | 560 | +0.002 | 0.940 (0.082) | 0.1723 |
| geopolitics | event | 6,504 | +0.218 | 1.155 (0.029) | 0.0873 |
| geopolitics | game | 401 | +0.222 | 0.943 (0.083) | 0.1164 |
| mentions | event | 6,888 | -0.194 | 1.121 (0.029) | 0.1691 |
| mentions | game | 303 | -0.826 | 1.115 (0.111) | 0.1632 |
| other | event | 456 | -0.218 | 0.896 (0.077) | 0.1196 |
| politics | event | 7,458 | -0.038 | 1.111 (0.027) | 0.0794 |
| politics | game | 407 | +0.134 | 0.791 (0.089) | 0.1449 |
| sports | event | 9,112 | -0.480 | 1.127 (0.030) | 0.0894 |
| sports | game | 4,589 | -0.216 | 0.901 (0.060) | 0.2021 |
| tech | event | 5,023 | -0.188 | 1.103 (0.032) | 0.0707 |
| weather | event | 5,498 | -0.508 | 1.069 (0.039) | 0.0871 |
| weather | game | 1,208 | +0.336 | 1.275 (0.125) | 0.0672 |

## B4. Volume (final volume, hindsight, descriptive)

| Tercile | From $ | Markets | a | b (se) | Market Brier |
|---|---|---|---|---|---|
| low | 0 | 24,917 | -0.124 | 1.107 (0.073) | 0.1837 |
| mid | 5,608 | 24,917 | -0.023 | 1.022 (0.056) | 0.1835 |
| high | 33,053 | 24,917 | -0.006 | 0.883 (0.049) | 0.2041 |

## B5. Recent moves

7-day logit change added to logit(p): coefficient -0.205 (se 0.091); 1-day: -0.034 (se 0.044). Positive: the price under-reacts (momentum); negative: it over-reacts.

## M. Models against the market (out of sample by quarter from 2024)

| Model | Markets | Brier market | Brier model | Skill | Brier gain (95 %) | Log loss market | Log loss model | Years better | Categories better | Holm p | Passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| recal | 73,609 | 0.1071 | 0.1061 | +1.01 % | +0.00108 (+0.00082 to +0.00131) | 0.3310 | 0.3288 | 3/3 | 7/10 | 0.000 | yes |
| gbm | 73,609 | 0.1071 | 0.1035 | +3.41 % | +0.00365 (+0.00321 to +0.00410) | 0.3310 | 0.3238 | 2/3 | 9/10 | 0.000 | yes |


**Addendum slices** (same test, states where the history price is more likely a real price):

| Slice | Model | Share of states | Markets | Brier market | Brier model | Skill | Brier gain (95 %) | Years better | Rule met |
|---|---|---|---|---|---|---|---|---|---|
| after day one | recal | 87 % | 68,958 | 0.0888 | 0.0887 | +0.12 % | +0.00010 (-0.00011 to +0.00032) | 2/3 | no |
| after day one | gbm | 87 % | 68,958 | 0.0888 | 0.0876 | +1.31 % | +0.00116 (+0.00080 to +0.00149) | 2/3 | yes |
| price has moved | recal | 96 % | 73,230 | 0.0997 | 0.0994 | +0.32 % | +0.00032 (+0.00008 to +0.00058) | 2/3 | no |
| price has moved | gbm | 96 % | 73,230 | 0.0997 | 0.0981 | +1.64 % | +0.00163 (+0.00127 to +0.00197) | 2/3 | yes |
| after day one and moved | recal | 86 % | 68,780 | 0.0883 | 0.0882 | +0.10 % | +0.00009 (-0.00013 to +0.00030) | 2/3 | no |
| after day one and moved | gbm | 86 % | 68,780 | 0.0883 | 0.0871 | +1.32 % | +0.00117 (+0.00082 to +0.00151) | 2/3 | yes |


**By final volume** (after day one and moved; final volume is hindsight, so this only says where the skill sits):

| Final volume | Markets | Brier market | recal skill | gbm skill | gbm gain (95 %) |
|---|---|---|---|---|---|
| $0 to $5,000 | 20,189 | 0.0824 | +2.39 % | +6.76 % | +0.00557 (+0.00488 to +0.00627) |
| $5,000 to $33,000 | 24,596 | 0.0858 | -0.48 % | +0.21 % | +0.00018 (-0.00030 to +0.00064) |
| $33,000 to $100,000 | 10,027 | 0.0940 | -0.91 % | -0.79 % | -0.00074 (-0.00152 to +0.00006) |
| $100,000 to $1,000,000 | 11,204 | 0.0967 | -1.15 % | -1.84 % | -0.00178 (-0.00242 to -0.00107) |
| $1,000,000 and up | 2,764 | 0.0974 | -0.89 % | -3.36 % | -0.00328 (-0.00462 to -0.00186) |


**Quoted spreads of the open markets** (live record, Gamma's best bid and ask; every open market with $1,000 of liquidity, plus the first snapshot's every open market):

| Mid bucket | Markets | Median spread | Wider than 10 cents | Markets with $10k+ | Their median spread |
|---|---|---|---|---|---|
| 0-2 | 7,759 | 0.008 | 0 % | 3,000 | 0.005 |
| 2-5 | 9,083 | 0.041 | 0 % | 2,377 | 0.024 |
| 5-10 | 8,096 | 0.045 | 15 % | 1,320 | 0.020 |
| 10-20 | 9,419 | 0.050 | 35 % | 1,731 | 0.020 |
| 20-35 | 16,793 | 0.210 | 58 % | 1,799 | 0.020 |
| 35-50 | 30,991 | 0.900 | 82 % | 1,155 | 0.020 |
| 50-65 | 55,028 | 0.960 | 93 % | 864 | 0.020 |
| 65-80 | 4,538 | 0.060 | 42 % | 406 | 0.020 |
| 80-90 | 1,834 | 0.050 | 33 % | 287 | 0.020 |
| 90-95 | 1,077 | 0.050 | 30 % | 185 | 0.020 |
| 95-98 | 794 | 0.026 | 0 % | 421 | 0.019 |
| 98-100 | 764 | 0.001 | 0 % | 250 | 0.002 |


**recal by category** (Brier, market / model, markets):

| Category | Market | Model | Markets |
|---|---|---|---|
| crypto | 0.1060 | 0.1057 | 9,199 |
| culture | 0.0814 | 0.0798 | 7,961 |
| economics | 0.1012 | 0.1016 | 3,614 |
| finance | 0.1358 | 0.1363 | 5,778 |
| geopolitics | 0.0857 | 0.0854 | 6,815 |
| mentions | 0.1683 | 0.1681 | 7,159 |
| other | 0.1009 | 0.1003 | 193 |
| politics | 0.0842 | 0.0843 | 7,777 |
| sports | 0.1262 | 0.1236 | 13,351 |
| tech | 0.0709 | 0.0699 | 5,068 |
| weather | 0.0904 | 0.0865 | 6,694 |


**recal by days to end**:

| Days to end | Market | Model | Markets |
|---|---|---|---|
| <1d | 0.0714 | 0.0714 | 55,325 |
| 1-3d | 0.0957 | 0.0947 | 50,644 |
| 3-7d | 0.1008 | 0.0990 | 43,287 |
| 7-30d | 0.1034 | 0.1030 | 32,856 |
| 30-90d | 0.0950 | 0.0936 | 17,912 |
| >90d | 0.0915 | 0.0894 | 10,055 |


**gbm by category** (Brier, market / model, markets):

| Category | Market | Model | Markets |
|---|---|---|---|
| crypto | 0.1060 | 0.1048 | 9,199 |
| culture | 0.0814 | 0.0778 | 7,961 |
| economics | 0.1012 | 0.0994 | 3,614 |
| finance | 0.1358 | 0.1321 | 5,778 |
| geopolitics | 0.0857 | 0.0824 | 6,815 |
| mentions | 0.1683 | 0.1690 | 7,159 |
| other | 0.1009 | 0.0967 | 193 |
| politics | 0.0842 | 0.0823 | 7,777 |
| sports | 0.1262 | 0.1187 | 13,351 |
| tech | 0.0709 | 0.0665 | 5,068 |
| weather | 0.0904 | 0.0834 | 6,694 |


**gbm by days to end**:

| Days to end | Market | Model | Markets |
|---|---|---|---|
| <1d | 0.0714 | 0.0714 | 55,325 |
| 1-3d | 0.0957 | 0.0938 | 50,644 |
| 3-7d | 0.1008 | 0.0962 | 43,287 |
| 7-30d | 0.1034 | 0.0995 | 32,856 |
| 30-90d | 0.0950 | 0.0918 | 17,912 |
| >90d | 0.0915 | 0.0880 | 10,055 |


## P. The paper rule on the test states (historical twin)

Asks: history price plus the median half-spread of the live book record (1,790 book sides; at least half a cent), at most $500 per market, the published taker fees by category, $10,000 start, quarter Kelly with the caps.

| Forecast | Margin | Spread | Trades | Hit rate | Mean per trade (95 %) | P&L $ | Return | Sharpe | Max DD | Fees $ | Deflated p |
|---|---|---|---|---|---|---|---|---|---|---|---|
| recal | 0.02 | 1x | 31676 | 66.4 % | +12.6 % (+11.5 % to +13.8 %) | +1,972,322 | +19723.2 % | 3.60 | 56.9 % | 267,281 | 0.94 |
| recal | 0.03 | 1x | 26528 | 66.3 % | +13.8 % (+12.4 % to +15.2 %) | +1,795,309 | +17953.1 % | 3.46 | 56.9 % | 226,758 | 0.91 |
| recal | 0.05 | 1x | 18950 | 65.2 % | +15.7 % (+13.8 % to +17.1 %) | +1,469,921 | +14699.2 % | 3.68 | 53.9 % | 171,886 | 0.95 |
| gbm | 0.02 | 1x | 45938 | 70.7 % | +18.3 % (+17.4 % to +19.5 %) | +4,176,375 | +41763.7 % | 5.19 | 27.7 % | 391,143 | 1.00 |
| gbm | 0.03 | 1x | 42244 | 70.4 % | +20.2 % (+19.1 % to +21.1 %) | +4,225,127 | +42251.3 % | 5.21 | 27.7 % | 370,842 | 1.00 |
| gbm | 0.05 | 1x | 36002 | 70.5 % | +23.9 % (+22.7 % to +25.2 %) | +4,270,884 | +42708.8 % | 5.22 | 27.7 % | 330,021 | 1.00 |
| recal | 0.03 | 2x | 24826 | 66.3 % | +13.3 % (+12.0 % to +14.6 %) | +1,638,576 | +16385.8 % | 3.69 | 55.7 % | 211,195 | 0.95 |
| gbm | 0.03 | 2x | 39775 | 70.5 % | +19.9 % (+18.9 % to +21.0 %) | +3,921,155 | +39211.5 % | 5.39 | 34.3 % | 347,899 | 1.00 |


**Addendum checks** (declared after the test run, counted as trials):

| Forecast | Check | Trades | Hit rate | Mean per trade (95 %) | Return | Sharpe | Max DD | Deflated p |
|---|---|---|---|---|---|---|---|---|
| recal | no first-day states | 4282 | 55.9 % | +2.1 % (-1.0 % to +4.8 %) | +56.4 % | 0.58 | 71.9 % | 0.00 |
| recal | half-spread by age | 27040 | 66.3 % | +13.8 % (+12.4 % to +15.1 %) | +18358.4 % | 3.67 | 56.9 % | 0.95 |
| recal | price has moved | 16605 | 64.5 % | +7.7 % (+6.1 % to +9.3 %) | +6131.4 % | 2.67 | 54.3 % | 0.45 |
| recal | after day one and moved | 4333 | 56.1 % | +2.5 % (-0.4 % to +5.3 %) | +131.7 % | 0.77 | 66.7 % | 0.00 |
| gbm | no first-day states | 9461 | 64.5 % | +17.1 % (+14.7 % to +19.5 %) | +7661.0 % | 3.99 | 20.9 % | 0.99 |
| gbm | half-spread by age | 42261 | 70.4 % | +20.2 % (+19.1 % to +21.3 %) | +42332.3 % | 5.21 | 27.7 % | 1.00 |
| gbm | price has moved | 26810 | 67.0 % | +12.9 % (+11.6 % to +14.3 %) | +16821.5 % | 4.44 | 28.4 % | 1.00 |
| gbm | after day one and moved | 8964 | 64.7 % | +17.6 % (+15.2 % to +20.2 %) | +7456.5 % | 3.72 | 26.7 % | 0.97 |


Median half-spread of the live record by market age: <1d 0.50 cents (18 book sides), 1-7d 0.50 cents (214 book sides), >7d 0.50 cents (1,558 book sides).


Pool: 1,124 hand trials, 600 factory trials, 16 here: 1,740 (noise bar Sharpe 2.73).


Live model: fitted on 2,445,333 states of 74,751 markets.
