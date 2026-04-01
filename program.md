# autoresearch (chess engine)

This is an experiment to have the LLM autonomously improve a chess engine.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `apr1`). The branch `autoresearch/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current master.
3. **Read the in-scope files**: The repo is small. Read these files for full context:
   - `README.md` — repository context.
   - `src/lib.rs` — the Rust search backend. This is the PRIMARY file you modify. Evaluation function, search algorithm, tuning constants, move ordering, pruning.
   - `engine.py` — Python wrapper. Imports the Rust module, converts FEN/moves. You can modify the opening book here.
   - `eval_harness.py` — fixed evaluation harness. Do not modify.
4. **Verify Stockfish is installed**: Run `which stockfish`. If not found, tell the human to install it.
5. **Initialize results.tsv**: Create `results.tsv` with just the header row. The baseline will be recorded after the first run.
6. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each experiment: you modify `src/lib.rs` (or `engine.py`), rebuild, run the evaluation harness, and check if the estimated ELO improved.

**What you CAN do:**
- Modify `src/lib.rs` — the Rust search backend. Everything is fair game: piece values, piece-square tables, evaluation terms, search heuristics, move ordering, pruning, extensions.
- Modify `engine.py` — the Python wrapper. You can change the opening book or the Rust/Python dispatch logic.

**What you CANNOT do:**
- Modify `eval_harness.py`, `play.py`, or `replay.html`. They are read-only.
- Use neural networks or external evaluation libraries. This is a classical engine.

**The goal is simple: get the highest estimated_elo.** The evaluation harness plays games against Stockfish at calibrated levels and computes an ELO estimate. Higher is better.

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing something and getting equal or better results is a great outcome.

**The first run**: Your very first run should always be to establish the baseline, so you will run the evaluation harness as is.

**Building after changes**: After modifying `src/lib.rs`, you MUST rebuild before running the harness:
```
source "$HOME/.cargo/env" && uv run maturin develop --release 2>&1 | tail -5
```
Check the output for errors. If it says `Installed chess-autoresearch`, the build succeeded. If there are Rust compilation errors, fix them before proceeding. Incremental builds take ~5-15 seconds.

## Output format

Once the harness finishes it prints a summary like this:

```
---
estimated_elo:  1234.5
games:          28
wins:           14
losses:         8
draws:          6
time_seconds:   187.3
```

You can extract the key metric from the log file:

```
grep "^estimated_elo:" run.log
```

## Logging results

When an experiment is done, log it to `results.tsv` (tab-separated, NOT comma-separated).

The TSV has a header row and 5 columns:

```
commit	estimated_elo	games_played	status	description
```

1. git commit hash (short, 7 chars)
2. estimated_elo achieved (e.g. 1234.5) — use 0.0 for crashes
3. total games played
4. status: `keep`, `discard`, or `crash`
5. short text description of what this experiment tried

Example:

```
commit	estimated_elo	games_played	status	description
a1b2c3d	1150.0	28	keep	baseline
b2c3d4e	1185.0	28	keep	increase knight value to 330
c3d4e5f	1120.0	28	discard	experimental king tropism eval
d4e5f6g	0.0	0	crash	syntax error in PST
```

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autoresearch/apr1`).

LOOP FOREVER:

1. Look at the git state: the current branch/commit we're on
2. Plan an experimental idea and modify `src/lib.rs` (and/or `engine.py`).
3. **Always git commit every change before running.** Use a short descriptive message, e.g. `git commit -am "increase knight value to 330"`. Every experiment must have its own commit so we can track and revert cleanly.
4. **Rebuild**: `source "$HOME/.cargo/env" && uv run maturin develop --release 2>&1 | tail -5`
5. If the build fails, fix the error and re-commit. Do NOT run the harness with a failed build.
6. Run the experiment: `uv run eval_harness.py > run.log 2>&1` (redirect everything — do NOT let output flood your context)
7. Read out the results: `grep "^estimated_elo:\|^games:" run.log`
8. If the grep output is empty, the run crashed. Run `tail -n 50 run.log` to read the stack trace and attempt a fix. If you can't get things to work after more than a few attempts, give up on this idea.
9. Record the results in the tsv (NOTE: do not commit the results.tsv file, leave it untracked by git)
10. If estimated_elo improved (higher), you "advance" the branch, keeping the git commit
11. If estimated_elo is equal or worse, you git reset back to where you started

## Strategy guidance

**CONTEXT**: The engine uses a Rust search backend (~2M nodes/sec) that reaches depth 8-9 at 100ms per move. The baseline ELO is ~1650. With deeper search now working, both eval improvements AND search improvements have real impact.

Here are high-value directions to try, roughly in priority order:

1. **Search pruning and reductions** — more aggressive pruning lets the engine reach deeper depths. Ideas: reverse futility pruning (static eval margins at shallow depths), futility pruning at frontier nodes, late move pruning (LMP — skip quiet moves after a threshold), razoring (drop to quiescence when eval is far below alpha). Also tune LMR more aggressively with a logarithmic formula: `reduction = 1 + ln(depth) * ln(move_index) / 2.0`.
2. **Move ordering** — better ordering = more cutoffs = deeper search. Ideas: countermove heuristic, static exchange evaluation (SEE) for capture ordering, separate capture history table.
3. **Evaluation improvements** — now that search is deep enough, eval quality matters. Ideas: knight outpost bonus (pawn-supported knight that can't be attacked by enemy pawns), rook on 7th rank bonus, connected rooks bonus, king tropism (penalty for enemy pieces near our king), center pawn bonus, undeveloped minor penalty, space advantage.
4. **Piece-square tables** — refine MG/EG tables. Consider more aggressive centralization in EG king table, better pawn structure incentives.
5. **Endgame knowledge** — king centralization bonus in endgame, pawn race detection, mop-up evaluation (drive enemy king to corner when ahead in material).
6. **Piece value tuning** — try adjustments to knight/bishop/rook/queen values. Bishop slightly above knight, etc.

**Noise warning**: The evaluation has variance (~30-50 ELO per run due to limited games). Improvements under ~30 ELO may be noise. If an experiment shows marginal improvement, consider re-running to confirm. Be skeptical of small gains.

**Timeout**: Each evaluation should take ~3-5 minutes. If a run exceeds 10 minutes, kill it and treat it as a failure.

**Crashes**: If a run crashes, use your judgment. Typos and syntax errors are easy fixes. If the idea itself is broken, skip it and move on. For Rust compilation errors, read the error message carefully — the Rust compiler gives very helpful diagnostics.

**NEVER STOP**: Once the experiment loop has begun, do NOT pause to ask the human if you should continue. The human might be asleep. You are autonomous. If you run out of ideas, think harder — re-read src/lib.rs for new angles, try combining previous near-misses, try more radical changes. The loop runs until the human interrupts you.
