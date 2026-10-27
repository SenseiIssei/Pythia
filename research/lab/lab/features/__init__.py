"""D3: one point-in-time feature store over the lab's data, the recorder's order books included.

registry.py  the registry (name, sources, native frequency, delay until known, function) and frame(), the
             one call that gives a point-in-time frame for assets and times, hourly or daily
micro.py     microstructure from the recorder: spread, depth, imbalance, trade flow, realised vol from trades,
             cross-venue dispersion, funding, premium, liquidations
external.py  Binance's archives (funding, open interest) and the flow and D2 series, when they exist
store.py     the Parquet cache of the hourly tables, rebuilt incrementally (python -m lab.features build)
adapter.py   what the model and strategy factories draw from: a feature matrix on their own grid
study.py     coverage and rank IC of every feature (results/feature_store_d3.md)
"""

from . import external, micro  # noqa: F401  (they register their groups and features)
from .registry import DAY, HOUR, MARKET, REGISTRY, Feature, clear, frame, get, names, values  # noqa: F401
