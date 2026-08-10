"""Sieve — evidence infrastructure for simulation validation.

Everything durable is a versioned, hashable artifact; nothing anywhere
aggregates evidence into a single score.
"""

__version__ = "0.4.0"

from sieve.api import from_arrays, from_dataframe, from_runs  # noqa: E402

__all__ = ["__version__", "from_arrays", "from_dataframe", "from_runs"]
