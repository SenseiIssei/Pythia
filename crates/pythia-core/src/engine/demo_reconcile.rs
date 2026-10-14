//! The Alpaca paper account against Pythia's book, per Alpaca pair.
//!
//! With `PYTHIA_DEMO_EXCHANGE=alpaca`, crypto demo orders trade on the Alpaca
//! paper account. Several of Pythia's markets can land in one Alpaca position
//! there: `crypto:BTC/USD` on the demo route, `alpaca:BTC/USD` (the Alpaca
//! demo connection test, or the live arm on the paper endpoint) all hold
//! `BTC/USD`. So the comparison is per Alpaca pair: the sum of every Pythia
//! position on the paper account that maps to the pair, against what Alpaca
//! holds. The daemon runs it at startup and every ten minutes
//! (`execution::reconcile_demo`) with the account's crypto positions and open
//! orders, and the result is on the Live page (`LiveStatus::demo_reconcile`).
//!
//! What each pair can come out as ([`PairStatus`]):
//!
//! - **ok**: equal, or different by less than rounding (a billionth of the
//!   position, or less than a cent).
//! - **pending**: an order for the pair is still in flight (one that went out
//!   before a restart included). The venue may already hold part of its fill
//!   that the book has not booked; the order's own report settles it.
//! - **feeTaken**: the venue holds fewer coins than the book, and the
//!   unposted fees of the watched buys explain the gap (see `alpaca_fees`).
//!   Booked as those fees.
//! - **corrected**: one demo position holds the pair and nothing is open:
//!   the venue wins, as in the live reconciliation, and an autopilot that
//!   owns it books the difference at the mark.
//! - **adopted**: the venue holds the pair, the book holds none, and exactly
//!   one market on the paper route has Pythia demo orders in that pair: the
//!   position is taken into the book as a demo position of the strategy that
//!   sent the newest of them. The autopilot that strategy runs in does not
//!   count it (it never decided to hold it); its exit rules see it as the
//!   strategy's.
//! - **strayOrder**: Alpaca has an open order for the pair that Pythia does
//!   not follow. Reported, nothing corrected while it can still fill.
//! - **mismatch**: anything else (several markets hold the pair, or the one
//!   that does is a live paper-endpoint position the live reconciliation
//!   owns). Reported, never guessed.
//! - **untracked**: the venue holds a pair Pythia never traded on this route,
//!   or one several markets could own. Reported, not adopted.
//!
//! Each finding is journaled once; the same numbers ten minutes later are
//! not journaled again.

use super::alpaca_fees::{alpaca_crypto_order, EstimatedFee};
use super::{Engine, FillRoute, JournalKind, OrderStatus, PositionInternal};
use crate::connectors::alpaca::alpaca_crypto_pair;
use crate::connectors::alpaca_crypto::OpenOrder;
use crate::connectors::{BrokerPosition, Venue};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet, HashSet};

/// How often the daemon reconciles the paper account.
pub const DEMO_RECONCILE_EVERY_MS: i64 = 10 * 60_000;

/// What the comparison of one pair came out as. See the module docs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum PairStatus {
    Ok,
    Pending,
    FeeTaken,
    Corrected,
    Adopted,
    StrayOrder,
    Mismatch,
    Untracked,
}

impl PairStatus {
    /// Pythia and Alpaca agree now, or will once an order reports.
    pub fn settled(self) -> bool {
        matches!(self, PairStatus::Ok | PairStatus::Pending | PairStatus::FeeTaken | PairStatus::Corrected | PairStatus::Adopted)
    }
}

/// One Alpaca pair on the paper account.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PairCheck {
    /// `BTC/USD`.
    pub symbol: String,
    /// Pythia's markets holding it on the paper account.
    pub markets: Vec<String>,
    /// Their summed quantity, before anything this run changed.
    pub pythia: f64,
    /// What Alpaca holds.
    pub alpaca: f64,
    /// `pythia - alpaca`, and its value at the mark.
    pub diff: f64,
    pub diff_usd: f64,
    pub status: PairStatus,
    pub note: String,
}

/// The last reconciliation of the Alpaca paper account.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DemoReconcile {
    /// When it ran (epoch ms); 0 when it never completed.
    pub checked_at: i64,
    /// Every pair either side holds.
    pub pairs: Vec<PairCheck>,
    /// Pairs that are not settled (`mismatch`, `untracked`, `strayOrder`).
    pub mismatches: usize,
    /// Open crypto orders on the account, and those Pythia does not follow.
    pub open_orders: usize,
    pub stray_orders: Vec<String>,
    /// Why the last attempt could not read the account, if it failed.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    /// When the last attempt failed (epoch ms).
    #[serde(default)]
    pub failed_at: i64,
    /// Alpaca crypto fees booked from the published schedule, newest last.
    #[serde(default)]
    pub estimated_fees: Vec<EstimatedFee>,
}

/// Equal up to rounding: a billionth of the position (Alpaca's 9 decimals),
/// or less than a cent at the mark.
fn rounding(diff: f64, size: f64, price: f64) -> bool {
    diff.abs() <= (size.abs() * 1e-9).max(2e-9) || (price > 0.0 && diff.abs() * price < 0.01)
}

impl Engine {
    /// A position Pythia holds on the Alpaca paper account: a crypto demo
    /// position on the Alpaca route, an Alpaca demo position, or a live one
    /// while the live arm points at the paper endpoint. Crypto pairs only.
    fn on_alpaca_paper(&self, p: &PositionInternal) -> bool {
        if !p.symbol.contains('/') || p.qty.abs() < 1e-12 {
            return false;
        }
        if p.demo {
            p.venue == Venue::Alpaca || (p.venue == Venue::Crypto && self.crypto_demo_on_alpaca())
        } else {
            p.live && p.venue == Venue::Alpaca && self.live.paper
        }
    }

    /// The coins Pythia's demo positions hold of `pair` on the paper account.
    /// The live reconciliation of the paper endpoint leaves them out of the
    /// venue's position: they are the demo book's, not the live arm's.
    pub(super) fn paper_demo_qty(&self, pair: &str) -> f64 {
        self.positions
            .values()
            .filter(|p| p.demo && self.on_alpaca_paper(p))
            .filter(|p| alpaca_crypto_pair(&p.symbol).as_deref() == Some(pair))
            .map(|p| p.qty)
            .sum()
    }

    /// Markets on a route to the paper account whose symbol is `pair`.
    fn paper_route_markets(&self, pair: &str) -> Vec<String> {
        self.markets
            .iter()
            .filter(|m| alpaca_crypto_pair(&m.symbol).as_deref() == Some(pair))
            .filter(|m| match m.venue {
                Venue::Crypto => self.crypto_demo_on_alpaca(),
                Venue::Alpaca => self.demo_venues.contains(&Venue::Alpaca),
                Venue::Polymarket => false,
            })
            .map(|m| m.id.clone())
            .collect()
    }

    /// Compare the paper account (its crypto `positions` and `open` orders)
    /// with the book, settle what can be settled without guessing, report
    /// the rest. Returns how many pairs are not settled.
    pub fn apply_demo_reconcile(&mut self, positions: &[BrokerPosition], open: &[OpenOrder]) -> usize {
        let now = self.now();
        // Pythia's side, per pair: (market, qty, demo).
        let mut book: BTreeMap<String, Vec<(String, f64, bool)>> = BTreeMap::new();
        for (id, p) in &self.positions {
            if !self.on_alpaca_paper(p) {
                continue;
            }
            if let Some(pair) = alpaca_crypto_pair(&p.symbol) {
                book.entry(pair).or_default().push((id.clone(), p.qty, p.demo));
            }
        }
        for holders in book.values_mut() {
            holders.sort_by(|a, b| a.0.cmp(&b.0));
        }
        // Alpaca's side.
        let mut venue: BTreeMap<String, (f64, f64)> = BTreeMap::new();
        // `BTC/USD` or Alpaca's `BTCUSD`; equities map to no pair.
        for bp in positions {
            if let Some(pair) = alpaca_crypto_pair(&bp.symbol) {
                let e = venue.entry(pair).or_insert((0.0, 0.0));
                e.0 += bp.qty;
                e.1 = bp.avg_price;
            }
        }
        // Orders Pythia follows on the paper account, and pairs they hold up.
        let followed: Vec<_> = self.inflight.values().filter(|f| alpaca_crypto_order(f) && (f.demo || f.paper)).collect();
        let known_ids: HashSet<String> = followed.iter().filter_map(|f| f.broker_id.clone()).collect();
        let known_cids: HashSet<String> = followed.iter().map(|f| f.client_order_id.clone()).filter(|c| !c.is_empty()).collect();
        let pending: HashSet<String> = followed.iter().filter_map(|f| alpaca_crypto_pair(&f.symbol)).collect();
        let stray: Vec<&OpenOrder> = open
            .iter()
            .filter(|o| !known_ids.contains(&o.id) && (o.client_order_id.is_empty() || !known_cids.contains(&o.client_order_id)))
            .collect();
        let stray_pairs: HashSet<String> = stray.iter().map(|o| o.symbol.clone()).collect();
        let stray_orders: Vec<String> = stray
            .iter()
            .map(|o| {
                let cid = if o.client_order_id.is_empty() { String::new() } else { format!(", client id {}", o.client_order_id) };
                format!("{} {:?} {} ({} filled, {}{cid}, id {})", o.symbol, o.side, o.qty, o.filled_qty, o.status, o.id)
            })
            .collect();
        for (o, line) in stray.iter().zip(&stray_orders) {
            let key = format!("order:{}", o.id);
            if self.demo_reconcile_noted.insert(key, line.clone()).is_none() {
                let ours = if o.client_order_id.starts_with("pythia-") {
                    "sent by Pythia before a restart and no longer followed"
                } else {
                    "not sent by Pythia"
                };
                self.log(
                    JournalKind::Risk,
                    format!(
                        "Alpaca paper has an open order Pythia does not follow ({ours}): {line}. The pair is not corrected while it can fill; cancel it in Alpaca's dashboard if it is not wanted."
                    ),
                    None,
                    None,
                );
            }
        }

        let pairs: BTreeSet<String> = book.keys().chain(venue.keys()).cloned().collect();
        let mut checks = Vec::new();
        for pair in pairs {
            let holders = book.get(&pair).cloned().unwrap_or_default();
            let pythia: f64 = holders.iter().map(|h| h.1).sum();
            let (alpaca, venue_avg) = venue.get(&pair).copied().unwrap_or((0.0, 0.0));
            let diff = pythia - alpaca;
            let price = holders
                .iter()
                .map(|h| self.price_of(&h.0))
                .chain(self.paper_route_markets(&pair).iter().map(|m| self.price_of(m)))
                .find(|p| *p > 0.0)
                .unwrap_or(venue_avg);
            let markets: Vec<String> = holders.iter().map(|h| h.0.clone()).collect();
            let (status, note) = if rounding(diff, pythia.abs().max(alpaca.abs()), price) {
                (PairStatus::Ok, String::new())
            } else if pending.contains(&pair) {
                (PairStatus::Pending, "an order is in flight; its report settles the difference".to_string())
            } else if stray_pairs.contains(&pair) {
                (PairStatus::StrayOrder, "Alpaca has an open order Pythia does not follow".to_string())
            } else {
                self.settle_pair(&pair, &holders, alpaca, venue_avg, price)
            };
            checks.push(PairCheck {
                symbol: pair.clone(),
                markets,
                pythia,
                alpaca,
                diff,
                diff_usd: diff * price,
                status,
                note: note.clone(),
            });
            // Journal each finding once.
            if matches!(status, PairStatus::Ok | PairStatus::Pending) {
                self.demo_reconcile_noted.remove(&pair);
                continue;
            }
            let sig = format!("{status:?}|{pythia:.9}|{alpaca:.9}");
            if self.demo_reconcile_noted.get(&pair) == Some(&sig) {
                continue;
            }
            self.demo_reconcile_noted.insert(pair.clone(), sig);
            let kind = if status.settled() { JournalKind::Fill } else { JournalKind::Risk };
            self.log(
                kind,
                format!(
                    "Alpaca paper reconcile {pair}: Pythia {pythia:.9} ({}), Alpaca {alpaca:.9}, difference {diff:+.9} (${:+.2}): {status:?}. {note}",
                    if holders.is_empty() { "no position".to_string() } else { holders.iter().map(|h| h.0.clone()).collect::<Vec<_>>().join(" + ") },
                    diff * price
                ),
                None,
                holders.first().map(|h| h.0.clone()),
            );
        }
        // Stray orders that are gone are forgotten, so a new one is said.
        let open_ids: HashSet<String> = open.iter().map(|o| format!("order:{}", o.id)).collect();
        self.demo_reconcile_noted.retain(|k, _| !k.starts_with("order:") || open_ids.contains(k));

        let mismatches = checks.iter().filter(|c| !c.status.settled()).count();
        if mismatches > 0 && self.demo_reconcile.as_ref().is_none_or(|d| d.mismatches != mismatches) {
            self.pending_alerts.push(format!("⚠ Alpaca paper and Pythia's demo book differ in {mismatches} pair(s); see the Live page"));
            self.alert(
                crate::alerts::AlertKind::ReconcileMismatch,
                format!("reconcile:demo:{mismatches}"),
                format!("the Alpaca paper account and Pythia's demo book differ in {mismatches} pair(s); see the Live page."),
            );
        }
        self.demo_reconcile = Some(DemoReconcile {
            checked_at: now,
            pairs: checks,
            mismatches,
            open_orders: open.len(),
            stray_orders,
            error: None,
            failed_at: 0,
            estimated_fees: Vec::new(),
        });
        mismatches
    }

    /// Settle one pair whose numbers differ, nothing in flight and nothing
    /// stray: a fee gap, a correction of the one demo holder, an adoption, or
    /// a report.
    fn settle_pair(&mut self, pair: &str, holders: &[(String, f64, bool)], alpaca: f64, venue_avg: f64, price: f64) -> (PairStatus, String) {
        let pythia: f64 = holders.iter().map(|h| h.1).sum();
        let gap = pythia - alpaca;
        // Fewer coins at the venue: the unposted fees of the watched buys?
        if gap > 0.0 && alpaca >= 0.0 {
            for (market, _, demo) in holders {
                let flags: Vec<(bool, bool)> = self
                    .alpaca_fees
                    .iter()
                    .filter(|w| &w.market_id == market && (w.paper || w.demo))
                    .map(|w| (w.paper, w.demo))
                    .collect::<BTreeSet<_>>()
                    .into_iter()
                    .collect();
                for (paper, wdemo) in flags {
                    if wdemo == *demo && self.take_alpaca_fee_gap(market, gap, paper, wdemo, "the Alpaca paper reconcile shows it") {
                        return (PairStatus::FeeTaken, format!("the gap is the unposted Alpaca fee of {market}'s buys; booked as that fee"));
                    }
                }
            }
        }
        match holders {
            [] if alpaca > 0.0 => self.adopt_pair(pair, alpaca, venue_avg, price),
            [] => (PairStatus::Untracked, "Alpaca reports a short crypto position; not Pythia's".to_string()),
            [(market, was, true)] => {
                let market = market.clone();
                let was = *was;
                let Some(p) = self.positions.get_mut(&market) else {
                    return (PairStatus::Mismatch, "the position went away during the check".to_string());
                };
                let was_avg = p.avg_price;
                let avg = if venue_avg > 0.0 { venue_avg } else { was_avg };
                if alpaca.abs() < 1e-12 {
                    self.positions.remove(&market);
                    self.ref_prices.remove(&market);
                } else {
                    p.qty = alpaca;
                    p.avg_price = avg;
                    // Stops were sized for the old quantity.
                    p.stop = 0.0;
                    p.target = 0.0;
                    p.trail_ref = avg;
                    self.ref_prices.remove(&market);
                }
                self.autopilot_on_correction(&market, (was, was_avg), (alpaca, avg), "Alpaca paper");
                (PairStatus::Corrected, format!("{market} is the only holder and nothing is open: set to Alpaca's {alpaca:.9}, Alpaca wins"))
            }
            [(market, _, false)] => (
                PairStatus::Mismatch,
                format!("{market} is a live paper-endpoint position; the live reconciliation owns it"),
            ),
            _ => (
                PairStatus::Mismatch,
                format!("{} markets share {pair} on the paper account; which one is off cannot be told, so nothing is changed", holders.len()),
            ),
        }
    }

    /// Alpaca holds `pair`, the book holds none of it. Adopt it when exactly
    /// one market on the paper route has Pythia demo orders in that pair.
    fn adopt_pair(&mut self, pair: &str, qty: f64, venue_avg: f64, price: f64) -> (PairStatus, String) {
        let candidates = self.paper_route_markets(pair);
        let traded: Vec<(String, String)> = self
            .orders
            .iter()
            .filter(|o| o.route == FillRoute::Demo && candidates.contains(&o.market_id))
            .filter(|o| o.filled_qty > 0.0 || o.status == OrderStatus::Pending || o.reject_reason.as_deref().is_some_and(|r| r.contains("status unknown")))
            .map(|o| (o.market_id.clone(), o.strategy_id.clone()))
            .collect();
        let distinct: BTreeSet<&String> = traded.iter().map(|t| &t.0).collect();
        if distinct.len() != 1 {
            let why = if distinct.is_empty() {
                format!("Pythia has no demo order in {pair} on this route; not Pythia's to manage")
            } else {
                format!("Pythia traded {pair} in {} markets on this route; which one owns it cannot be told", distinct.len())
            };
            return (PairStatus::Untracked, why);
        }
        // The newest order is first.
        let (market_id, sid) = traded[0].clone();
        let Some(m) = self.markets.iter().find(|m| m.id == market_id).cloned() else {
            return (PairStatus::Untracked, format!("{market_id} is not a market any more"));
        };
        let sid = if self.strategies.iter().any(|s| s.id == sid) {
            sid
        } else {
            let i = self.ensure_manual_strategy();
            self.strategies[i].id.clone()
        };
        let avg = if venue_avg > 0.0 { venue_avg } else { price };
        self.positions.insert(
            market_id.clone(),
            PositionInternal {
                venue: m.venue,
                symbol: m.symbol.clone(),
                qty,
                avg_price: avg,
                strategy_id: sid.clone(),
                stop: 0.0,
                target: 0.0,
                trail_ref: avg,
                live: false,
                demo: true,
            },
        );
        (PairStatus::Adopted, format!("only {market_id} trades {pair} on this route: adopted {qty:.9} at {avg:.6} as a demo position of {sid}"))
    }

    /// The paper account could not be read. Kept on the Live page; journaled
    /// once per distinct reason.
    pub fn demo_reconcile_failed(&mut self, why: &str) {
        let now = self.now();
        let mut d = self.demo_reconcile.clone().unwrap_or_default();
        let changed = d.error.as_deref() != Some(why);
        d.error = Some(why.to_string());
        d.failed_at = now;
        self.demo_reconcile = Some(d);
        if changed {
            self.log(JournalKind::Risk, format!("Alpaca paper reconcile could not read the account: {why}"), None, None);
        }
    }

    /// The last reconciliation with the fee estimates, for the Live page.
    pub(super) fn demo_reconcile_view(&self) -> Option<DemoReconcile> {
        if self.demo_reconcile.is_none() && self.alpaca_fee_estimates.is_empty() {
            return None;
        }
        let mut d = self.demo_reconcile.clone().unwrap_or_default();
        d.estimated_fees = self.alpaca_fee_estimates.clone();
        Some(d)
    }

    /// The last reconciliation, for hosts and tests.
    pub fn demo_reconcile(&self) -> Option<DemoReconcile> {
        self.demo_reconcile_view()
    }
}
