# Contributing

Use Python 3.11 or newer and an ordinary C/C++ compiler with CMake 3.20+.
Install development tools with `python -m pip install -e '.[dev]'`. Before a
pull request, run `pytest`, `ruff check .`, `ruff format --check .`, `mypy src`,
`python -m build`, and the disabled native CMake/CTest commands in the README.

The `src/axis_memlab` package owns host-side contracts; `native/` owns the
SDK-free disabled interface; `schemas/` owns provisional wire formats; tests
and fixtures must remain synthetic and offline. Use explicit units in metric
names and never represent unavailable values with zero. Do not implement future
milestone behavior as a successful placeholder. Keep examples free of customer,
camera, credential, and surveillance data. Pull requests should describe
scope, safety implications, tests run, and any schema or compatibility
assumptions.
