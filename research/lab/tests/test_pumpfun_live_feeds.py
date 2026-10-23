"""The live pump.fun service streams from the owner's websocket providers: the feeds collector.feed_urls gives,
the links spread over them like the collector's, the start line without a key.

No network: only the URL plan is checked.

Run from research/lab:  python -m pytest tests/test_pumpfun_live_feeds.py
"""

from __future__ import annotations

from lab.pumpfun_rt import collector as COL
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import live_service as LS

PUBLIC = "wss://api.mainnet-beta.solana.com"
PROVIDER = "wss://provider.example/?api-key={token}"
TOKEN = "s3cr3t-tok"


def test_without_a_provider_every_link_reads_todays_single_public_url():
    assert COL.feed_urls({}) == [PUBLIC]
    assert COL.feed_urls({"PYTHIA_SOLANA_WS": "wss://own.example"}) == ["wss://own.example"]
    links = LS.feed_links(COL.feed_urls({}))
    assert len(links) == LS.LINKS + LS.AMM_LINKS
    assert {u for u, _, _ in links} == {PUBLIC}
    # a provider needing a token that is not set is left out: as today
    assert COL.feed_urls({"PYTHIA_SOLANA_WS_URLS": PROVIDER}) == [PUBLIC]


def test_a_provider_is_filled_and_first_the_public_one_appended():
    urls = COL.feed_urls({"PYTHIA_SOLANA_WS_URLS": PROVIDER, "PYTHIA_SOLANA_TOKEN": TOKEN})
    assert urls == [PROVIDER.replace("{token}", TOKEN), PUBLIC]
    off = COL.feed_urls({"PYTHIA_SOLANA_WS_URLS": PROVIDER, "PYTHIA_SOLANA_TOKEN": TOKEN,
                         "PYTHIA_PF_PUBLIC_FALLBACK": "0"})
    assert off == [PROVIDER.replace("{token}", TOKEN)]


def test_the_first_link_of_each_program_uses_the_provider(monkeypatch):
    monkeypatch.setattr(LS, "LINKS", 2)
    monkeypatch.setattr(LS, "AMM_LINKS", 2)
    urls = COL.feed_urls({"PYTHIA_SOLANA_WS_URLS": PROVIDER, "PYTHIA_SOLANA_TOKEN": TOKEN})
    links = LS.feed_links(urls)
    by = {(p, k): u for u, p, k in links}
    assert by[(E.PUMP, 0)] == urls[0] and by[(E.PUMP_AMM, 0)] == urls[0]
    assert by[(E.PUMP, 1)] == PUBLIC and by[(E.PUMP_AMM, 1)] == PUBLIC
    assert len(links) == 4


def test_the_start_line_names_scheme_and_host_never_the_token():
    urls = COL.feed_urls({"PYTHIA_SOLANA_WS_URLS": PROVIDER, "PYTHIA_SOLANA_TOKEN": TOKEN})
    line = LS.feeds_line(urls)
    assert TOKEN not in line and "api-key" not in line and "?" not in line
    assert line == "live service: feeds wss://provider.example, wss://api.mainnet-beta.solana.com"
