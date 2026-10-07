// One sentence of plain language for every number a beginner meets.
// StatCard, Card titles, Field labels and <Term> look their label up here, so a
// new card is explained by adding a line.

export const GLOSSARY: Record<string, string> = {
  // Home
  "Markets watched": "How many markets it is keeping an eye on: coins, shares and prediction questions.",
  "Strategies running": "How many of its rule sets are switched on. Each one decides on its own when to buy or sell.",
  "Trades made today": "How many buys and sells actually went through today.",
  "Things it owns": "How many different things it holds right now.",

  // Portfolio and performance
  Equity: "Everything it is worth right now: cash plus what it holds at today's prices.",
  "Today's P&L": "How much it is up or down since today started (midnight UTC). P&L means profit and loss.",
  "P&L": "Profit and loss: how much money was made or lost.",
  Unrealized: "Gain or loss on things it still holds. It only becomes real when it sells.",
  "Open positions": "How many different things it currently owns.",
  "Open Exposure": "How much money is in the market right now instead of sitting as cash.",
  "Net Return": "What it made after every fee and cost, as a share of the money it used.",
  "Win Rate": "How many closed trades made money. Under half can still be fine if the winners are bigger than the losers.",
  Win: "How many closed trades made money. Under half can still be fine if the winners are bigger than the losers.",
  Sharpe: "Return for the amount of up and down along the way. Above 1 is good, below 0 means it lost money.",
  "Median Sharpe": "The middle Sharpe across all tested settings: half did better, half worse. Harder to fool than the best one.",
  "Median Return": "The middle return across all tested settings. Harder to fool with one lucky setting than the best.",
  "% Profitable": "The share of tested settings that made money after costs. High means the result does not hang on one lucky choice.",
  "Max Drawdown": "Worst dip: the biggest fall from a high point before it recovered. Smaller is calmer.",
  "Worst Drawdown": "Worst dip: the biggest fall from a high point before it recovered. Smaller is calmer.",
  maxDD: "Worst dip: the biggest fall from a high point before it recovered. Smaller is calmer.",
  "Worst DD": "Worst dip: the biggest fall from a high point before it recovered. Smaller is calmer.",
  "Portfolio Drawdown": "How far the account is below its best point so far. Zero means it is at its high.",
  PF: "Profit factor: money won on winning trades divided by money lost on losing ones. Above 1 means it made money overall.",
  "Profit factor": "Money won on winning trades divided by money lost on losing ones. Above 1 means it made money overall.",
  Gross: "The result before fees, spread and price impact.",
  Costs: "Fees plus slippage: what trading itself cost.",
  Net: "What was kept after every cost. The only number that ends up in your pocket.",
  Trades: "How many round trips (a buy and the matching sell) were completed.",

  // Dashboard and markets
  "Equity Curve": "The account's value over time. Up and to the right is good; a steady line is calmer than a jagged one.",
  "Venue Balances": "How the practice money is split between the places it can trade: prediction markets, crypto and US shares.",
  "Live Activity": "The newest things the engine did, newest first: signals, orders, fills and risk checks.",
  "Price / Prob": "For coins and shares, the last price. For prediction markets, the chance the market gives the event, in percent.",
  "24h": "How much the price moved in the last 24 hours.",
  Model: "Pythia's own estimate. For prediction markets, the chance it gives the event; compare it with the market's.",
  "Order size": "How many practice dollars one click on Buy or Sell spends.",
  "real bars": "Indicators run on real exchange candles, so the signals measure a real market.",
  sim: "Simulated prices. Useful to watch the machinery work, but the indicators measure the simulator, not a market.",
  trending: "Prices are moving steadily in one direction, which suits trend-following strategies.",
  choppy: "Prices are going back and forth without a clear direction, which suits mean-reversion strategies.",

  // Positions and orders
  Qty: "How much of it is held. Negative means a short: borrowed and sold, hoping to buy back cheaper.",
  Avg: "The average price it paid to get in.",
  Last: "The latest market price.",
  Flatten: "Close the whole position: sell what is held, or buy back what is short.",
  LONG: "Bought, so it makes money if the price goes up.",
  SHORT: "Sold short, so it makes money if the price goes down.",
  "Recent Orders": "The latest orders it sent, filled or not, with the reason when one was refused.",

  // Strategies and research
  "Strategy Passport": "Eight checks a strategy has to pass before it may touch real money. Green passed, red failed, grey not checked yet.",
  Budget: "The most of the account this strategy may use at once.",
  Bars: "How many price candles (time steps) the test runs over. More bars means a longer history.",
  Seed: "The starting number for the random price generator. The same seed always gives the same fake history, so results can be repeated.",
  Volatility: "How much the simulated price jumps around from one candle to the next. 0.02 is about 2 % per candle.",
  "Drift/bar": "A built-in up or down trend per candle in the simulated prices. Zero means no trend.",
  "Seeds / combo": "How many different random histories every setting is tested on. More gives a fairer picture but takes longer.",
  "OOS Sharpe": "The Sharpe on data the optimizer never saw while choosing. This is the honest one.",
  "IS Sharpe": "The Sharpe on the data the settings were chosen on. Always looks better than reality.",
  "OOS/IS": "Out-of-sample result divided by in-sample result. Near 1 means the edge survived new data; below 0.5 it was mostly luck.",
  "Deflated Sharpe": "How likely the Sharpe is to be real edge, after accounting for how many settings were tried. Below 95 % it could be luck.",
  Deflated: "How likely the Sharpe is to be real edge, after accounting for how many settings were tried. Below 95 % it could be luck.",
  "OOS net": "What the held-out data made after every cost, as a share of capital.",
  "Walk-forward validation": "Pick the best settings on one batch of histories, then test them on a fresh batch they never saw. Overfitted settings fall apart here.",
  "Strategy Leaderboard": "Every strategy ranked by what it has made, with what trading cost it along the way.",
  "Strategy Equity Curves": "Each strategy's running profit or loss, drawn on one chart so you can compare them.",
  "Execution: realised vs modelled slippage":
    "Whether real fills cost what the cost model assumed. If they cost much more, every backtest was too optimistic.",
  "Trade Log": "Every filled order, newest first.",
  "Return Correlation Matrix": "How alike each pair of markets moves. Red squares move together (risk piles up), green ones move opposite (they balance).",

  // Diversification
  "Effective bets": "How many truly separate bets it holds. Ten coins that move together count as about one.",
  "Avg |correlation|": "How much the markets move together, from 0 (on their own) to 1 (in lockstep). Lower spreads the risk better.",

  // Predictions
  Market: "The chance everyone trading this market currently gives it.",
  "Pooled sources": "The combined opinion of every source that commented, weighted by how well each has done before.",
  Ensemble: "Pythia's final number: the market price, pulled toward the pooled sources only as far as they have earned.",
  "Kelly stake": "The share of the account a textbook betting formula would put on this. Pythia uses a fraction of it.",
  "Trust in the pool": "How far the pooled sources may pull away from the market price. Zero until they beat the market on a track record.",
  Disagreement: "How much the sources disagree with each other. High disagreement means less certainty.",
  "Effective sources": "How many truly independent opinions there are. Sources that always agree count as one.",
  "Coherence breaks": "Markets whose own outcomes do not add up to 100 %. The gap is arithmetic, not a forecast.",
  "Source scoreboard": "How each source's forecasts scored against what really happened, next to the market's own score on the same questions.",
  Brier: "Forecast error: 0 is perfect, 0.25 is what always saying 50 % scores. Lower is better.",
  Skill: "How much better than the market a source was on the same questions. Positive is better than the market.",
  Pooled: "That skill after borrowing strength from the source's wider record, so a thin record does not swing wildly.",
  Bias: "Whether a source forecasts too high (positive) or too low (negative) on average.",
  Trust: "How much weight a source carries now: its skill, discounted for how little evidence there is.",
  n: "How many of its forecasts have been checked against reality.",
  bps: "Basis points: hundredths of a percent. 100 bps is 1 %.",

  // Money
  Free: "The part you could spend or move right now.",
  Total: "Everything held, including amounts locked in open orders.",
  USD: "What it is worth in US dollars at the latest price.",

  // Risk limits
  "Max daily loss": "If the account loses this much in one day, it stops opening new trades until tomorrow.",
  "Max drawdown (breaker)": "If the account falls this far below its best point, everything new stops until you let it continue.",
  "Max position size": "The most of the account it may put into any single market.",
  "Max gross exposure": "The most of the account that may be in the market at once, all positions added up.",
  "Max correlated exposure": "Like gross exposure, but markets that move together count as one bet. Zero switches the cap off.",
  "Book volatility target": "How much the whole account may swing in a typical year. New trades that would push past it are made smaller.",
  "Per-strategy budget": "The most of the account any one strategy may use.",
  "Kelly fraction": "How much of the textbook bet size it uses. Smaller is more careful; 0.25 means a quarter.",
  "Vol-target sizing": "Size each trade so it moves about this much per candle. Calmer markets get bigger trades, wilder ones smaller.",
  "Stop-loss (ATR)": "Sell when the price falls this many typical daily moves (ATR) below the entry. Zero switches it off.",
  "Take-profit (ATR)": "Take the profit when the price rises this many typical moves (ATR) above the entry. Zero switches it off.",
  "Trailing stop (ATR)": "A stop that follows the price up and sells if it drops this many typical moves from the high. Zero switches it off.",
  "Loss streak → cooldown": "After this many losing trades in a row, a strategy takes a break. Zero switches it off.",
  "Cooldown duration": "How long that break lasts.",
  "Max orders / min": "A speed limit, so a bug can never fire a flood of orders.",
  "Max data staleness": "If prices are older than this, it refuses to trade on them.",
  "Daily Loss Utilization": "How much of today's loss allowance is used up. At 100 % it stops opening trades for the day.",
  "Gross Exposure Utilization": "How much of the allowed money-in-the-market is in use.",
  "Correlated Exposure": "Money in the market, counting positions that move together as one bet, against its cap.",
  "Book Volatility": "How much the whole account is expected to swing in a typical year, against its target.",
  "Drawdown De-risking": "As the account falls from its best point, new trades get smaller, down to none at the breaker.",
  "Position Sizing": "How big each strategy's next trade will be, and what that size is based on.",
  "Adaptive controls": "Two automatic helpers: one skips trades that do not suit the current market, the other gives more money to strategies that are working.",

  // Live
  "Dry-run": "Write down the orders it would send, but send nothing.",
  Endpoint: "Which account the orders go to: the broker's practice account (paper) or the real one (live).",
  "Order timeout": "How long an order may wait unfilled before it is cancelled at the broker.",
  "Extended hours": "Also trade before and after the normal US market session, when there are fewer buyers and sellers.",
  "Adaptive execution": "Learns whether waiting inside the spread is cheaper than paying the asking price, from what each choice actually cost.",
  "Day-trade cap": "US brokers limit how many same-day round trips a small account may make. When reached, new entries wait.",
  "Buying power": "How much the broker would let it buy right now.",

  // Models
  "Hours scored live": "How many forecasts have been checked against what really happened since it started.",
  "Better than HAR": "How much smaller its forecast error is than the standard textbook method. Above zero means it is better.",
  "Hours won": "How often its forecast was closer to reality than the textbook method's.",
  "Error, model vs HAR": "The average forecast error (QLIKE), its own against the textbook method's. Lower is better.",

  // AI
  "Live AI overlay": "An AI model that can shrink or block trades the strategies already chose. It can never start a trade on its own.",
  Confidence: "How sure the model says it is. Models are often overconfident, so treat this as a hint.",
  Calls: "How many times the overlay asked a model so far.",
  "Input tokens": "How much text was sent to the model. Providers charge by tokens.",
  "Output tokens": "How much text the model wrote back. Usually priced higher than input.",
  Errors: "Calls that failed, for example a wrong key or a timeout.",
};

export function explain(label: string): string | undefined {
  return GLOSSARY[label];
}
