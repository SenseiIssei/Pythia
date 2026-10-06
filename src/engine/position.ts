// Position accounting, shared by the paper engine and its tests. Mirrors Rust
// `engine::apply_fill`.

export interface FillResult {
  qty: number;
  avgPrice: number;
  realized: number;
}

/**
 * Apply a signed fill (`+` buys, `-` sells) to a position.
 *
 * Whether the fill adds or reduces is decided by its own sign against the
 * position's, not by the sign of the result. Comparing the result's sign made a
 * partial reduction look like an add: no P&L was realised and the average price
 * was dragged toward the exit.
 */
export function applyFill(qty: number, avgPrice: number, signed: number, fill: number): FillResult {
  const newQty = qty + signed;
  if (qty === 0 || Math.sign(qty) === Math.sign(signed)) {
    const total = avgPrice * Math.abs(qty) + fill * Math.abs(signed);
    return { qty: newQty, avgPrice: Math.abs(newQty) > 0 ? total / Math.abs(newQty) : fill, realized: 0 };
  }
  const closed = Math.min(Math.abs(signed), Math.abs(qty));
  const realized = (fill - avgPrice) * closed * Math.sign(qty);
  // A reduction keeps the entry price of what is left; a flip starts fresh at this fill.
  const flipped = Math.abs(newQty) > 1e-12 && Math.sign(newQty) !== Math.sign(qty);
  return { qty: newQty, avgPrice: flipped ? fill : avgPrice, realized };
}
