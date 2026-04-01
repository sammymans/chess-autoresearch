"""Lightweight FastAPI server wrapping the chess engine for browser play."""

from __future__ import annotations

import chess
import engine
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class MoveRequest(BaseModel):
    fen: str
    movetime_ms: int = 200


class MoveResponse(BaseModel):
    move_uci: str
    move_san: str
    score: int
    depth: int
    nodes: int
    pv: list[str]
    time_ms: float
    fen_after: str


@app.post("/move")
def get_engine_move(req: MoveRequest) -> MoveResponse:
    board = chess.Board(req.fen)
    result = engine.choose_move(board, movetime_ms=req.movetime_ms)
    san = board.san(result.move)
    board.push(result.move)
    return MoveResponse(
        move_uci=result.move.uci(),
        move_san=san,
        score=result.score,
        depth=result.depth,
        nodes=result.nodes,
        pv=result.pv,
        time_ms=result.time_ms,
        fen_after=board.fen(),
    )


class LegalMovesRequest(BaseModel):
    fen: str


@app.post("/legal_moves")
def get_legal_moves(req: LegalMovesRequest) -> dict:
    board = chess.Board(req.fen)
    moves = []
    for m in board.legal_moves:
        moves.append({
            "uci": m.uci(),
            "san": board.san(m),
            "from": m.uci()[:2],
            "to": m.uci()[2:4],
        })
    return {"moves": moves, "turn": "white" if board.turn else "black"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
