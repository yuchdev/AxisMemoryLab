# Synthetic leak scenarios

Controlled synthetic leak scenarios belong to M0002. This directory contains
no fake output that could be mistaken for a real diagnosis.

M0002 generates its leak, plateau, platform-growth, and restart traces in code: see
`tests/synthetic_traces.py` and `tests/unit/test_analysis.py`.
