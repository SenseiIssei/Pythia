// One sentence of plain language for every number a beginner meets.
// StatCard looks its label up here, so a new card is explained by adding a line.

export const GLOSSARY: Record<string, string> = {
  // Home
  "Markets watched": "How many markets it is keeping an eye on: coins, shares and prediction questions.",
  "Strategies running": "How many of its rule sets are switched on. Each one decides on its own when to buy or sell.",
  "Trades made today": "How many buys and sells actually went through today.",
  "Things it owns": "How many different things it holds right now.",

  // Portfolio and performance
  Equity: "Everything it is worth right now: cash plus what it holds at today's prices.",
  "Today's P&L": "How much it is up or down since today started (midnight UTC).",
  Unrealized: "Gain or loss on things it still holds. It only becomes real when it sells.",
  "Open positions": "How many different things it currently owns.",
  "Open Exposure": "How much money is in the market right now instead of sitting as cash.",
  "Net Return": "What it made after every fee and cost, as a share of the money it used.",
  "Win Rate": "How many closed trades made money. Under half can still be fine if the winners are bigger than the losers.",
  Sharpe: "Return for the amount of up and down along the way. Above 1 is good, below 0 means it lost money.",
  "Median Sharpe": "The middle Sharpe across all tested settings: half did better, half worse. Harder to fool than the best one.",
  "Median Return": "The middle return across all tested settings. Harder to fool with one lucky setting than the best.",
  "% Profitable": "The share of tested settings that made money after costs. High means the result does not hang on one lucky choice.",
  "Max Drawdown": "Worst dip: the biggest fall from a high point before it recovered. Smaller is calmer.",
  "Worst Drawdown": "Worst dip: the biggest fall from a high point before it recovered. Smaller is calmer.",

  // Diversification
  "Effective bets": "How many truly separate bets it holds. Ten coins that move together count as about one.",
  "Avg |correlation|": "How much the markets move together, from 0 (on their own) to 1 (in lockstep). Lower spreads the risk better.",

  // Models
  "Hours scored live": "How many forecasts have been checked against what really happened since it started.",
  "Better than HAR": "How much smaller its forecast error is than the standard textbook method. Above zero means it is better.",
  "Hours won": "How often its forecast was closer to reality than the textbook method's.",
  "Error, model vs HAR": "The average forecast error (QLIKE), its own against the textbook method's. Lower is better.",
};

export function explain(label: string): string | undefined {
  return GLOSSARY[label];
}
