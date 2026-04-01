# autoresearch (chess engine)

This is an experiment to have the LLM autonomously improve a chess engine.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `apr1`). The branch `autoresearch/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current master.
3. **Read the in-scope files**: The repo is small. Read these files for full context:
   - `README.md` — repository context.
   - `engine.py` — the file you modify. Evaluation function, search algorithm, tuning constants.
   - `eval_harness.py` — fixed evaluation harness. Do not modify.
4. **Verify Stockfish is installed**: Run `which stockfish`. If not found, tell the human to install it.
5. **Initialize results.tsv**: Create `results.tsv` with just the header row. The baseline will be recorded after the first run.
6. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each experiment: you modify `engine.py`, run the evaluation harness, and check if the estimated ELO improved.

**What you CAN do:**
- Modify `engine.py` — this is the only file you edit. Everything is fair game: piece values, piece-square tables, evaluation terms, search heuristics, move ordering, pruning, extensions.

**What you CANNOT do:**
- Modify `eval_harness.py`, `play.py`, or `replay.html`. They are read-only.
- Install new packages or add dependencies. You can only use what's already in `pyproject.toml`.
- Use neural networks or external evaluation libraries. This is a classical engine.

**The goal is simple: get the highest estimated_elo.** The evaluation harness plays games against Stockfish at calibrated levels and computes an ELO estimate. Higher is better.

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing something and getting equal or better results is a great outcome.

**The first run**: Your very first run should always be to establish the baseline, so you will run the evaluation harness as is.

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
2. Tune `engine.py` with an experimental idea.
3. **Always git commit every change before running.** Use a short descriptive message, e.g. `git commit -am "increase knight value to 330"`. Every experiment must have its own commit so we can track and revert cleanly.
4. Run the experiment: `uv run eval_harness.py > run.log 2>&1` (redirect everything — do NOT let output flood your context)
5. Read out the results: `grep "^estimated_elo:\|^games:" run.log`
6. If the grep output is empty, the run crashed. Run `tail -n 50 run.log` to read the Python stack trace and attempt a fix. If you can't get things to work after more than a few attempts, give up on this idea.
7. Record the results in the tsv (NOTE: do not commit the results.tsv file, leave it untracked by git)
8. If estimated_elo improved (higher), you "advance" the branch, keeping the git commit
9. If estimated_elo is equal or worse, you git reset back to where you started

## Strategy guidance

**CRITICAL CONTEXT**: This is a pure Python engine tested at 100ms per move. At that budget, search typically reaches depth 3-5. The #1 priority is making search faster and deeper — getting even one extra ply of depth is worth far more than any eval tweak. Do NOT spend time on piece value tuning or PST refinements early on — at depth 3, the engine can't see basic tactics, so eval quality barely matters.

Here are high-value directions to try, roughly in priority order:

1. **Search speed and pruning** — the biggest lever. The engine is slow because it's Python. Make it search deeper in the same 100ms. Ideas: more aggressive null move pruning (adaptive R = 2 + depth/4), reverse futility pruning (skip nodes where static eval is already way above beta), futility pruning at frontier nodes, late move pruning (skip quiet moves entirely after a threshold at low depths), razoring (drop to quiescence when eval is far below alpha at low depth). Each of these prunes branches and lets the engine reach deeper.
2. **Move ordering improvements** — better ordering means more beta cutoffs, which means faster search. Ideas: separate capture history table, countermove heuristic (the move that refuted the previous move), improve MVV-LVA with static exchange evaluation (SEE).
3. **Search extensions and reductions** — tune LMR more aggressively (reduce more at higher depths and higher move indices), add singular extensions for TT moves, extend on passed pawn pushes to 7th rank.
4. **Reduce Python overhead** — avoid creating lists where generators work, cache expensive computations, avoid redundant board.is_check() calls, pre-compute piece lists. Even small constant-factor speedups compound across millions of nodes.
5. **Lightweight evaluation terms** — only add terms that are cheap to compute. Good: knight outpost bonus, rook on 7th rank, center pawn bonus, undeveloped minor penalty. Bad: anything that loops over many squares or calls board.attacks_mask() repeatedly.
6. **Piece-square tables and piece values** — low priority. Only tune these after search is solid. Small PST changes are indistinguishable from noise at low depth.

**Noise warning**: The evaluation has variance (~30-50 ELO per run due to limited games). Improvements under ~30 ELO may be noise. If an experiment shows marginal improvement, consider re-running to confirm. Be skeptical of small gains.

**Timeout**: Each evaluation should take ~3-5 minutes. If a run exceeds 10 minutes, kill it and treat it as a failure.

**Crashes**: If a run crashes, use your judgment. Typos and syntax errors are easy fixes. If the idea itself is broken, skip it and move on.

**NEVER STOP**: Once the experiment loop has begun, do NOT pause to ask the human if you should continue. The human might be asleep. You are autonomous. If you run out of ideas, think harder — re-read engine.py for new angles, try combining previous near-misses, try more radical changes. The loop runs until the human interrupts you.
