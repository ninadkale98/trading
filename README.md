# trading

A background research and paper-trading system for multi-week to multi-month stock holds.
It keeps a living map of the US market, tests ideas honestly, paper-trades the ones that prove themselves
on Alpaca, and escalates risky decisions to a human.

- **Design:** [docs/architecture.md](docs/architecture.md)
- **Build progress:** [docs/build-plan.md](docs/build-plan.md)
- **Beginner guides to every term:** [learning/](learning/README.md)
- **VS Code chart extension:** [stock-view/](stock-view/README.md)

## Quick start (on the always-on Mac)

```sh
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
brew services start postgresql@17 && createdb market
.venv/bin/tradebot migrate
./scripts/install_services.sh          # background service: starts at login, restarts if it crashes
.venv/bin/tradebot status              # heartbeat, queue, failures
.venv/bin/python -m pytest             # tests
.venv/bin/python -m core.backtest.validate
```

Secrets live in `.env` (never committed): `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY`, `SEC_USER_AGENT`.
