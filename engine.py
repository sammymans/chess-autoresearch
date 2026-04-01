"""
Thin wrapper around the Rust chess engine backend.

The Rust module (chess_engine_rs) handles all search and evaluation.
This file provides the Python interface that eval_harness.py and play.py expect.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess
import chess_engine_rs

# ---------------------------------------------------------------------------
# CONSTANTS (used by play.py)
# ---------------------------------------------------------------------------

MATE_SCORE = 100_000

# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """Result of a search, including telemetry."""
    move: chess.Move
    score: int
    depth: int
    nodes: int
    pv: list[str]
    time_ms: float
    depths_completed: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PUBLIC INTERFACE
# ---------------------------------------------------------------------------

def choose_move(
    board: chess.Board,
    depth: int | None = None,
    movetime_ms: int | None = None,
) -> SearchResult:
    """
    Choose the best move for the current position.

    Delegates entirely to the Rust backend.
    """
    result = chess_engine_rs.search_position(
        board.fen(),
        movetime_ms if movetime_ms else 0,
        depth if depth else 0,
    )

    # Convert PV from UCI to SAN
    pv_san = []
    temp = board.copy()
    for uci_str in result["pv"]:
        try:
            mv = chess.Move.from_uci(uci_str)
            if mv in temp.legal_moves:
                pv_san.append(temp.san(mv))
                temp.push(mv)
            else:
                break
        except Exception:
            break

    return SearchResult(
        move=chess.Move.from_uci(result["move"]),
        score=result["score"],
        depth=result["depth"],
        nodes=result["nodes"],
        pv=pv_san,
        time_ms=result["time_ms"],
    )


def get_telemetry(result: SearchResult) -> dict:
    """Convert SearchResult to a JSON-serializable dict."""
    return {
        "move": result.move.uci(),
        "score": result.score,
        "depth": result.depth,
        "nodes": result.nodes,
        "pv": result.pv,
        "time_ms": result.time_ms,
        "depths": result.depths_completed,
    }
