# Decision 0000: bootstrap

## Decisions

- Use Python 3.11+, `src/axis_memlab`, PEP 621/setuptools, and stdlib
  `argparse`/`tomllib`; runtime dependencies are empty.
- Keep host tooling independent from the optional native C ABI/C++17 surface.
- Use provisional Draft 2020-12 JSON schemas and synthetic fixtures. M0001 owns
  protocol refinement; no compatibility or stability claim is made.
- Native examples compile only with `AXMEM_DISABLED`; enabled instrumentation
  modes are not provided.
- Preserve the repository's existing MIT `LICENSE`; no new license was chosen.

## Unresolved

Companion specifications and the proposed `configs-default.toml` were not
present in the supplied repository. The scaffold uses the decisions and
contracts in the task statement; exact protocol and future device compatibility
remain open for M0001.
