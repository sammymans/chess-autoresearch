# chess-autoresearch

Give an AI agent a chess engine with hand-tuned heuristics and let it experiment overnight. It tweaks piece values, evaluation terms, and search heuristics, plays against Stockfish to measure strength, keeps improvements, discards regressions, and repeats. You wake up to a stronger engine.

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch).

## How it works

The repo has a small set of files:

- **`src/lib.rs`** — the Rust search backend. Alpha-beta search, evaluation, move ordering, pruning — all in ~1000 lines of Rust. ~2M nodes/sec. **This file is edited and iterated on by the agent**.
- **`engine.py`** — Python wrapper. Imports the Rust module, handles the opening book, converts between python-chess and Rust types. Falls back to a pure Python search if Rust isn't built.
- **`eval_harness.py`** — fixed evaluation harness. Plays the engine against Stockfish at calibrated ELO levels, computes an estimated rating, and saves game telemetry. Not modified.
- **`program.md`** — agent instructions. Point your agent here and let it go. **This file is edited and iterated on by the human**.
- **`play.py`** — interactive CLI for playing against the engine.
- **`server.py`** — lightweight FastAPI server for browser-based play.
- **`replay.html`** — browser-based game replay viewer with full engine telemetry.

The metric is **estimated ELO** — higher is better. Each evaluation plays ~20-28 games against Stockfish at levels from 800 to 2000, alternating colors.

## Quick start

**Requirements:** Python 3.10+, [uv](https://docs.astral.sh/uv/), Stockfish, Rust toolchain.

```bash
# 1. Install uv (if you don't already have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install Rust (if you don't already have it)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"

# 3. Install Stockfish
brew install stockfish    # macOS
# apt install stockfish   # Ubuntu/Debian

# 4. Build the Rust engine + install Python dependencies
uv run maturin develop --release

# 5. Run a baseline evaluation (~3-5 min)
uv run eval_harness.py

# 6. Play against the engine
uv run play.py
uv run play.py --depth 3   # easier
uv run play.py --depth 8   # harder
```

## Running the agent

Spin up Claude Code (or your agent of choice) in this repo, then prompt:

```
Have a look at program.md and let's kick off a new experiment! Let's do the setup first.
```

The agent will read the instructions, create a branch, establish a baseline, and start experimenting autonomously. Each experiment takes ~3-5 minutes, so you can expect ~12-15 experiments per hour, or ~100+ overnight.

## Viewing results

**Play interactively:**
```bash
uv run play.py                    # default settings
uv run play.py --depth 3          # easy opponent
uv run play.py --depth 8          # hard opponent
uv run play.py --color black      # play as black
uv run play.py --movetime 5000    # 5 seconds per move
```

**Replay games from autoresearch runs:**
Open `replay.html` in your browser and drag in a `.jsonl` file from the `games/` directory. You'll see every game with full engine telemetry — what it was thinking, evaluation scores, principal variation, nodes searched.

**Analyze experiment progress:**
Open `analysis.ipynb` to plot ELO progression across experiments.

## Project structure

```
src/lib.rs        — Rust search backend (agent modifies this)
engine.py         — Python wrapper + opening book + fallback search
eval_harness.py   — plays vs Stockfish, measures ELO (do not modify)
play.py           — interactive CLI game
server.py         — FastAPI server for browser play
replay.html       — browser game replay viewer
program.md        — agent instructions
analysis.ipynb    — experiment analysis notebook
Cargo.toml        — Rust dependencies
pyproject.toml    — Python dependencies + maturin build config
```

## Design choices

- **Classical engine, no neural networks.** Alpha-beta search with hand-crafted evaluation. No torch, no training data. The "learning" happens through the autoresearch loop editing heuristic constants.
- **Rust search backend.** ~2M nodes/sec, depth 8-9 at 100ms. Python fallback available if Rust isn't built.
- **Fixed evaluation harness.** Games against Stockfish at known ELO levels. The metric (estimated ELO) is objective and reproducible.
- **Full telemetry.** Every engine move during evaluation is logged with eval score, principal variation, depth, nodes, and timing. Replay any game in the browser.

## License

MIT
