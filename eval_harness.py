"""
Evaluation harness for the chess engine autoresearch loop.

DO NOT MODIFY THIS FILE. This is the fixed evaluation harness.
The autoresearch agent should only modify engine.py.

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
GAMES_PER_LEVEL = 4

# Stockfish levels to test against.
# Each entry is (approx_elo, skill_level, uci_elo).
# For levels below Stockfish's UCI_Elo minimum (1320), we use Skill Level only.
# Skill Level 0-20 maps roughly to 800-3000+ ELO.
STOCKFISH_LEVELS = [
    (800,  0,  None),   # Skill 0: very weak
    (1000, 3,  None),   # Skill 3: beginner
    (1200, 6,  None),   # Skill 6: casual
    (1400, 9,  1400),   # Skill 9 + UCI_Elo 1400
    (1600, 12, 1600),   # Skill 12 + UCI_Elo 1600
    (1800, 15, 1800),   # Skill 15 + UCI_Elo 1800
    (2000, 20, 2000),   # Skill 20 + UCI_Elo 2000
]

# Time per move for our engine (ms)
ENGINE_MOVETIME_MS = 100

# Time per move for Stockfish (seconds)
STOCKFISH_MOVETIME_S = 0.1

# Max plies before declaring a draw
MAX_PLIES = 200

# Output directory for game telemetry
GAMES_DIR = Path("games")


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
    engine_moves: list[MoveRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# STOCKFISH HELPERS
# ---------------------------------------------------------------------------

def find_stockfish() -> str:
    """Find Stockfish binary, checking common locations."""
    # Check env var first
    env_path = os.environ.get("STOCKFISH_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    # Check PATH
    sf = shutil.which("stockfish")
    if sf:
        return sf

    # Common locations
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


def create_stockfish(path: str, skill_level: int, uci_elo: int | None) -> chess.engine.SimpleEngine:
    """Create a Stockfish engine configured to play at a given strength."""
    sf = chess.engine.SimpleEngine.popen_uci(path)
    config: dict = {
        "Skill Level": skill_level,
        "Threads": 1,
        "Hash": 16,
    }
    if uci_elo is not None:
        config["UCI_LimitStrength"] = True
        config["UCI_Elo"] = uci_elo
    sf.configure(config)
    return sf


# ---------------------------------------------------------------------------
# GAME PLAYING
# ---------------------------------------------------------------------------

def play_game(
    engine_module,
    stockfish: chess.engine.SimpleEngine,
    stockfish_elo: int,
    engine_is_white: bool,
    game_id: int,
) -> GameResult:
    """Play one game between our engine and Stockfish."""
    board = chess.Board()
    engine_color = chess.WHITE if engine_is_white else chess.BLACK
    engine_moves: list[MoveRecord] = []
    move_number = 0

    game = chess.pgn.Game()
    game.headers["White"] = "Engine" if engine_is_white else f"Stockfish ({stockfish_elo})"
    game.headers["Black"] = f"Stockfish ({stockfish_elo})" if engine_is_white else "Engine"
    node = game

    while not board.is_game_over(claim_draw=True) and board.ply() < MAX_PLIES:
        if board.turn == engine_color:
            # Our engine's turn
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
                # Pick any legal move on error
                move = next(iter(board.legal_moves))
        else:
            # Stockfish's turn
            sf_result = stockfish.play(board, chess.engine.Limit(time=STOCKFISH_MOVETIME_S))
            move = sf_result.move

        node = node.add_variation(move)
        board.push(move)

    # Determine result
    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        # Hit MAX_PLIES
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
        engine_moves=engine_moves,
    )


# ---------------------------------------------------------------------------
# ELO ESTIMATION
# ---------------------------------------------------------------------------

def estimate_elo(results: list[GameResult]) -> float:
    """
    Estimate engine ELO using performance rating.

    Groups games by Stockfish level, computes score percentage,
    then uses the standard performance rating formula.
    """
    if not results:
        return 0.0

    total_score = 0.0
    total_games = 0
    weighted_elo = 0.0

    for game in results:
        total_score += game.result
        total_games += 1
        weighted_elo += game.stockfish_elo

    if total_games == 0:
        return 0.0

    avg_opponent_elo = weighted_elo / total_games
    score_pct = total_score / total_games

    # Clamp to avoid infinity
    if score_pct >= 1.0:
        return avg_opponent_elo + 400
    if score_pct <= 0.0:
        return avg_opponent_elo - 400

    # Standard performance rating: R_p = R_avg + 400 * (W - L) / N
    wins = total_score
    losses = total_games - total_score
    performance = avg_opponent_elo + 400 * (wins - losses) / total_games

    return round(performance, 1)


# ---------------------------------------------------------------------------
# TELEMETRY
# ---------------------------------------------------------------------------

def save_telemetry(
    results: list[GameResult],
    estimated_elo: float,
    elapsed_seconds: float,
) -> Path:
    """Save game telemetry to JSONL file in games/ directory."""
    GAMES_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = GAMES_DIR / f"{timestamp}_games.jsonl"

    # First line: summary metadata
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
        "stockfish_levels": [elo for elo, _, _ in STOCKFISH_LEVELS],
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

    # Import engine fresh (picks up agent's latest edits)
    if "engine" in sys.modules:
        engine_module = importlib.reload(sys.modules["engine"])
    else:
        engine_module = importlib.import_module("engine")

    start_time = time.monotonic()
    all_results: list[GameResult] = []
    game_id = 0

    for approx_elo, skill_level, uci_elo in STOCKFISH_LEVELS:
        print(f"\n--- Testing vs Stockfish ~{approx_elo} (Skill {skill_level}) ---")
        level_results: list[GameResult] = []

        stockfish = create_stockfish(stockfish_path, skill_level, uci_elo)
        try:
            for i in range(GAMES_PER_LEVEL):
                engine_is_white = (i % 2 == 0)
                game_id += 1
                color_str = "W" if engine_is_white else "B"

                game_result = play_game(
                    engine_module, stockfish, approx_elo,
                    engine_is_white, game_id,
                )
                level_results.append(game_result)
                all_results.append(game_result)

                result_str = {1.0: "WIN", 0.5: "DRAW", 0.0: "LOSS"}[game_result.result]
                print(f"  Game {game_id} [{color_str}]: {result_str} "
                      f"({game_result.result_reason}, {game_result.num_plies} plies)")
        finally:
            stockfish.quit()

        # Adaptive early stopping
        level_score = sum(g.result for g in level_results)
        if level_score == 0:
            print(f"  Lost all games at ~{approx_elo}, stopping.")
            break
        elif level_score == GAMES_PER_LEVEL:
            print(f"  Won all games at ~{approx_elo}, moving up.")

    elapsed = time.monotonic() - start_time
    elo = estimate_elo(all_results)
    wins = sum(1 for g in all_results if g.result == 1.0)
    losses = sum(1 for g in all_results if g.result == 0.0)
    draws = sum(1 for g in all_results if g.result == 0.5)

    # Save telemetry
    telemetry_path = save_telemetry(all_results, elo, elapsed)
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
