"""
Evaluation harness for the chess engine autoresearch loop.

DO NOT MODIFY THIS FILE. This is the fixed evaluation harness.
The autoresearch agent should only modify src/lib.rs.

Plays the engine against Stockfish at calibrated ELO levels,
computes an estimated ELO rating, and saves game telemetry.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import chess
import chess.engine
import chess.pgn

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Games per Stockfish ELO level (half as white, half as black)
GAMES_PER_LEVEL = 2

# Anchor configuration: 5 levels spaced 100 apart.
# Center is determined adaptively from the last kept result in results.tsv,
# falling back to DEFAULT_ANCHOR_CENTER for the first run.
DEFAULT_ANCHOR_CENTER = 1800
ANCHOR_COUNT = 5
ANCHOR_STEP = 100

# Path to results file for adaptive anchoring
RESULTS_FILE = Path("results.tsv")

# Time per move for our engine (ms)
ENGINE_MOVETIME_MS = 100

# Time per move for Stockfish (seconds)
STOCKFISH_MOVETIME_S = 0.1

# Max plies before declaring a draw
MAX_PLIES = 200

# Output directory for game telemetry
GAMES_DIR = Path("games")

# Opening lines for diversity (mix of openings to reduce opening-dependent variance)
OPENING_LINES = [
    # Empty = start from initial position
    [],
    # Italian Game: 1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5
    ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5"],
    # QGD: 1.d4 d5 2.c4 e6 3.Nc3 Nf6
    ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6"],
    # Sicilian Open: 1.e4 c5 2.Nf3 d6 3.d4 cxd4 4.Nxd4
    ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4"],
    # English: 1.c4 e5 2.Nc3 Nf6 3.Nf3 Nc6
    ["c2c4", "e7e5", "b1c3", "g8f6", "g1f3", "b8c6"],
    # French: 1.e4 e6 2.d4 d5 3.Nc3 Nf6
    ["e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "g8f6"],
]


# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------

@dataclass
class MoveRecord:
    """Telemetry for a single engine move."""
    move_number: int
    fen_before: str
    move_uci: str
    move_san: str
    score: int
    depth: int
    nodes: int
    pv: list[str]
    time_ms: float


@dataclass
class GameResult:
    """Result of a single game."""
    game_id: int
    engine_color: str  # "white" or "black"
    stockfish_elo: int
    result: float  # 1.0 = engine win, 0.5 = draw, 0.0 = engine loss
    result_reason: str
    num_plies: int
    pgn: str
    opening_index: int = 0
    engine_moves: list[MoveRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# STOCKFISH HELPERS
# ---------------------------------------------------------------------------

def find_stockfish() -> str:
    """Find Stockfish binary, checking common locations."""
    env_path = os.environ.get("STOCKFISH_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    sf = shutil.which("stockfish")
    if sf:
        return sf

    for path in [
        "/usr/local/bin/stockfish",
        "/opt/homebrew/bin/stockfish",
        "/usr/bin/stockfish",
        "/snap/bin/stockfish",
    ]:
        if os.path.isfile(path):
            return path

    print("ERROR: Stockfish not found.", file=sys.stderr)
    print("Install it (e.g. 'brew install stockfish' or 'apt install stockfish')", file=sys.stderr)
    print("or set the STOCKFISH_PATH environment variable.", file=sys.stderr)
    sys.exit(1)


def get_prior_elo() -> int | None:
    """Read the last kept estimated_elo from results.tsv, or None if unavailable."""
    if not RESULTS_FILE.exists():
        return None
    try:
        last_kept_elo = None
        with open(RESULTS_FILE) as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 4 and parts[3] == "keep":
                    try:
                        last_kept_elo = float(parts[1])
                    except ValueError:
                        continue
        return int(round(last_kept_elo)) if last_kept_elo is not None else None
    except Exception:
        return None


def stockfish_elo_bounds(path: str) -> tuple[int, int]:
    """Get the min/max UCI_Elo supported by this Stockfish binary."""
    sf = chess.engine.SimpleEngine.popen_uci(path)
    try:
        elo_option = sf.options.get("UCI_Elo")
        if elo_option is not None:
            return int(elo_option.min), int(elo_option.max)
        return 1320, 3190  # reasonable defaults
    finally:
        sf.quit()


def compute_anchor_elos(center: int, sf_min: int, sf_max: int) -> list[int]:
    """Compute anchor ELO levels centered on `center`, clamped to Stockfish bounds."""
    start = center - ANCHOR_STEP * (ANCHOR_COUNT // 2)
    start = max(sf_min, start)
    end = start + ANCHOR_STEP * (ANCHOR_COUNT - 1)
    if end > sf_max:
        start = max(sf_min, sf_max - ANCHOR_STEP * (ANCHOR_COUNT - 1))
    return [start + ANCHOR_STEP * i for i in range(ANCHOR_COUNT)]


def create_stockfish(path: str, uci_elo: int) -> chess.engine.SimpleEngine:
    """Create a Stockfish engine configured to play at a given UCI_Elo."""
    sf = chess.engine.SimpleEngine.popen_uci(path)
    config: dict = {
        "UCI_LimitStrength": True,
        "UCI_Elo": uci_elo,
        "Threads": 1,
        "Hash": 16,
    }
    sf.configure(config)
    return sf


# ---------------------------------------------------------------------------
# OPENING SETUP
# ---------------------------------------------------------------------------

def build_opening_board(opening_index: int) -> tuple[chess.Board, chess.pgn.Game]:
    """Build a board and PGN game from a predefined opening line."""
    board = chess.Board()
    game = chess.pgn.Game()
    node = game

    line = OPENING_LINES[opening_index % len(OPENING_LINES)]
    for uci_str in line:
        move = chess.Move.from_uci(uci_str)
        if move in board.legal_moves:
            node = node.add_variation(move)
            board.push(move)
        else:
            break

    return board, game


# ---------------------------------------------------------------------------
# GAME PLAYING
# ---------------------------------------------------------------------------

def play_game(
    engine_module,
    stockfish: chess.engine.SimpleEngine,
    stockfish_elo: int,
    engine_is_white: bool,
    game_id: int,
    opening_index: int = 0,
) -> GameResult:
    """Play one game between our engine and Stockfish."""
    board, game = build_opening_board(opening_index)
    engine_color = chess.WHITE if engine_is_white else chess.BLACK
    engine_moves: list[MoveRecord] = []
    move_number = 0

    game.headers["White"] = "Engine" if engine_is_white else f"Stockfish ({stockfish_elo})"
    game.headers["Black"] = f"Stockfish ({stockfish_elo})" if engine_is_white else "Engine"

    # Find the last node in the PGN (end of opening line)
    node = game
    while node.variations:
        node = node.variations[0]

    while not board.is_game_over(claim_draw=True) and board.ply() < MAX_PLIES:
        if board.turn == engine_color:
            move_number += 1
            fen_before = board.fen()
            try:
                result = engine_module.choose_move(board, movetime_ms=ENGINE_MOVETIME_MS)
                move = result.move
                san = board.san(move)
                engine_moves.append(MoveRecord(
                    move_number=move_number,
                    fen_before=fen_before,
                    move_uci=move.uci(),
                    move_san=san,
                    score=result.score,
                    depth=result.depth,
                    nodes=result.nodes,
                    pv=result.pv,
                    time_ms=result.time_ms,
                ))
            except Exception as e:
                print(f"  Engine error: {e}", file=sys.stderr)
                move = next(iter(board.legal_moves))
        else:
            sf_result = stockfish.play(board, chess.engine.Limit(time=STOCKFISH_MOVETIME_S))
            move = sf_result.move

        node = node.add_variation(move)
        board.push(move)

    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        result_val = 0.5
        reason = "max_plies"
    elif outcome.winner is None:
        result_val = 0.5
        reason = outcome.termination.name.lower()
    elif outcome.winner == engine_color:
        result_val = 1.0
        reason = outcome.termination.name.lower()
    else:
        result_val = 0.0
        reason = outcome.termination.name.lower()

    game.headers["Result"] = board.result(claim_draw=True)

    return GameResult(
        game_id=game_id,
        engine_color="white" if engine_is_white else "black",
        stockfish_elo=stockfish_elo,
        result=result_val,
        result_reason=reason,
        num_plies=board.ply(),
        pgn=str(game),
        opening_index=opening_index,
        engine_moves=engine_moves,
    )


# ---------------------------------------------------------------------------
# ELO ESTIMATION (binary search over logistic expected score)
# ---------------------------------------------------------------------------

def expected_score(player_elo: float, opponent_elo: float) -> float:
    """Standard ELO expected score: E = 1 / (1 + 10^((opp - player) / 400))."""
    return 1.0 / (1.0 + 10 ** ((opponent_elo - player_elo) / 400.0))


def estimate_elo(results: list[GameResult]) -> float:
    """
    Estimate engine ELO via binary search.

    Finds the rating R where the sum of expected scores against all opponents
    matches the actual total score. This properly weights games by opponent
    strength using the standard logistic ELO formula.
    """
    if not results:
        return 0.0

    actual_score = sum(g.result for g in results)
    total_games = len(results)

    # Edge cases
    if actual_score <= 0.0:
        return min(g.stockfish_elo for g in results) - 400
    if actual_score >= total_games:
        return max(g.stockfish_elo for g in results) + 400

    lo = 400.0
    hi = 3000.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        expected_total = sum(expected_score(mid, g.stockfish_elo) for g in results)
        if expected_total < actual_score:
            lo = mid
        else:
            hi = mid

    return round((lo + hi) / 2.0, 1)


# ---------------------------------------------------------------------------
# TELEMETRY
# ---------------------------------------------------------------------------

def save_telemetry(
    results: list[GameResult],
    estimated_elo: float,
    elapsed_seconds: float,
    anchor_elos: list[int],
) -> Path:
    """Save game telemetry to JSONL file in games/ directory."""
    GAMES_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = GAMES_DIR / f"{timestamp}_games.jsonl"

    wins = sum(1 for g in results if g.result == 1.0)
    losses = sum(1 for g in results if g.result == 0.0)
    draws = sum(1 for g in results if g.result == 0.5)

    summary = {
        "type": "summary",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "estimated_elo": estimated_elo,
        "games": len(results),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "time_seconds": round(elapsed_seconds, 1),
        "engine_movetime_ms": ENGINE_MOVETIME_MS,
        "anchor_elos": anchor_elos,
    }

    with open(filepath, "w") as f:
        f.write(json.dumps(summary) + "\n")

        for game in results:
            game_data = {
                "type": "game",
                "game_id": game.game_id,
                "engine_color": game.engine_color,
                "stockfish_elo": game.stockfish_elo,
                "result": game.result,
                "result_reason": game.result_reason,
                "num_plies": game.num_plies,
                "pgn": game.pgn,
                "opening_index": game.opening_index,
                "engine_moves": [
                    {
                        "move_number": m.move_number,
                        "fen_before": m.fen_before,
                        "move_uci": m.move_uci,
                        "move_san": m.move_san,
                        "score": m.score,
                        "depth": m.depth,
                        "nodes": m.nodes,
                        "pv": m.pv,
                        "time_ms": m.time_ms,
                    }
                    for m in game.engine_moves
                ],
            }
            f.write(json.dumps(game_data) + "\n")

    return filepath


# ---------------------------------------------------------------------------
# MAIN EVALUATION
# ---------------------------------------------------------------------------

def run_evaluation() -> None:
    """Run the full evaluation: play games, estimate ELO, save telemetry."""
    stockfish_path = find_stockfish()
    print(f"Stockfish: {stockfish_path}")

    # Determine anchor levels (adaptive: center on last kept ELO from results.tsv)
    prior_elo = get_prior_elo()
    center = prior_elo if prior_elo is not None else DEFAULT_ANCHOR_CENTER
    sf_min, sf_max = stockfish_elo_bounds(stockfish_path)
    anchor_elos = compute_anchor_elos(center, sf_min, sf_max)
    if prior_elo is not None:
        print(f"Prior ELO from results.tsv: {prior_elo}")
    else:
        print(f"No prior ELO found, using default center: {DEFAULT_ANCHOR_CENTER}")
    print(f"Anchor ELOs: {anchor_elos}")

    # Import engine fresh (picks up agent's latest edits)
    if "engine" in sys.modules:
        engine_module = importlib.reload(sys.modules["engine"])
    else:
        engine_module = importlib.import_module("engine")

    start_time = time.monotonic()
    all_results: list[GameResult] = []
    game_id = 0

    for level_index, elo in enumerate(anchor_elos):
        print(f"\n--- Testing vs Stockfish {elo} ---")

        stockfish = create_stockfish(stockfish_path, elo)
        try:
            for game_index in range(GAMES_PER_LEVEL):
                engine_is_white = (level_index + game_index) % 2 == 0
                opening_index = (level_index * GAMES_PER_LEVEL + game_index) % len(OPENING_LINES)
                game_id += 1
                color_str = "W" if engine_is_white else "B"

                game_result = play_game(
                    engine_module, stockfish, elo,
                    engine_is_white, game_id, opening_index,
                )
                all_results.append(game_result)

                result_str = {1.0: "WIN", 0.5: "DRAW", 0.0: "LOSS"}[game_result.result]
                print(f"  Game {game_id} [{color_str}] opening={opening_index}: {result_str} "
                      f"({game_result.result_reason}, {game_result.num_plies} plies)")
        finally:
            stockfish.quit()

    elapsed = time.monotonic() - start_time
    elo = estimate_elo(all_results)
    wins = sum(1 for g in all_results if g.result == 1.0)
    losses = sum(1 for g in all_results if g.result == 0.0)
    draws = sum(1 for g in all_results if g.result == 0.5)

    # Save telemetry
    telemetry_path = save_telemetry(all_results, elo, elapsed, anchor_elos)
    print(f"\nTelemetry saved to: {telemetry_path}")

    # Print parseable output (matches autoresearch grep pattern)
    print("\n---")
    print(f"estimated_elo:  {elo}")
    print(f"games:          {len(all_results)}")
    print(f"wins:           {wins}")
    print(f"losses:         {losses}")
    print(f"draws:          {draws}")
    print(f"time_seconds:   {elapsed:.1f}")


if __name__ == "__main__":
    run_evaluation()
