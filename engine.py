"""
Chess engine with alpha-beta search and heuristic evaluation.

The autoresearch agent modifies this file and/or src/lib.rs (the Rust backend).
If the Rust module is available, it is used for search (much faster).
Otherwise, the Python search below is used as a fallback.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import chess

# Try to import Rust backend
try:
    import chess_engine_rs
    _USE_RUST = True
except ImportError:
    _USE_RUST = False

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

INFINITY = 1_000_000
MATE_SCORE = 100_000
DRAW_SCORE = 0
MAX_ITERATIVE_DEPTH = 64

# Transposition table flags
EXACT = 0
LOWER_BOUND = 1
UPPER_BOUND = 2

# ---------------------------------------------------------------------------
# PIECE VALUES
# ---------------------------------------------------------------------------

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

# ---------------------------------------------------------------------------
# PIECE-SQUARE TABLES
# Indexed from white's perspective, a1=0, h8=63.
# Each row is one rank: rank 1 (index 0-7) to rank 8 (index 56-63).
# ---------------------------------------------------------------------------

# fmt: off

# -- Pawns --
PAWN_PST_MG = [
#    a    b    c    d    e    f    g    h
     0,   0,   0,   0,   0,   0,   0,   0,  # rank 1 (never occupied)
     5,  10,  10, -20, -20,  10,  10,   5,  # rank 2
     5,  -5, -10,   0,   0, -10,  -5,   5,  # rank 3
     0,   0,   0,  20,  20,   0,   0,   0,  # rank 4
     5,   5,  10,  25,  25,  10,   5,   5,  # rank 5
    10,  10,  20,  30,  30,  20,  10,  10,  # rank 6
    50,  50,  50,  50,  50,  50,  50,  50,  # rank 7
     0,   0,   0,   0,   0,   0,   0,   0,  # rank 8 (never occupied)
]

PAWN_PST_EG = [
     0,   0,   0,   0,   0,   0,   0,   0,
     5,   5,   5,   5,   5,   5,   5,   5,
    10,  10,  10,  10,  10,  10,  10,  10,
    20,  20,  20,  20,  20,  20,  20,  20,
    30,  30,  30,  30,  30,  30,  30,  30,
    50,  50,  50,  50,  50,  50,  50,  50,
    80,  80,  80,  80,  80,  80,  80,  80,
     0,   0,   0,   0,   0,   0,   0,   0,
]

# -- Knights --
KNIGHT_PST_MG = [
   -50, -40, -30, -30, -30, -30, -40, -50,
   -40, -20,   0,   0,   0,   0, -20, -40,
   -30,   0,  10,  15,  15,  10,   0, -30,
   -30,   5,  15,  20,  20,  15,   5, -30,
   -30,   0,  15,  20,  20,  15,   0, -30,
   -30,   5,  10,  15,  15,  10,   5, -30,
   -40, -20,   0,   5,   5,   0, -20, -40,
   -50, -40, -30, -30, -30, -30, -40, -50,
]

KNIGHT_PST_EG = [
   -50, -40, -30, -30, -30, -30, -40, -50,
   -40, -20,   0,   0,   0,   0, -20, -40,
   -30,   0,  10,  15,  15,  10,   0, -30,
   -30,   5,  15,  20,  20,  15,   5, -30,
   -30,   0,  15,  20,  20,  15,   0, -30,
   -30,   5,  10,  15,  15,  10,   5, -30,
   -40, -20,   0,   5,   5,   0, -20, -40,
   -50, -40, -30, -30, -30, -30, -40, -50,
]

# -- Bishops --
BISHOP_PST_MG = [
   -20, -10, -10, -10, -10, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,   5,  10,  10,   5,   0, -10,
   -10,   5,   5,  10,  10,   5,   5, -10,
   -10,   0,  10,  10,  10,  10,   0, -10,
   -10,  10,  10,  10,  10,  10,  10, -10,
   -10,   5,   0,   0,   0,   0,   5, -10,
   -20, -10, -10, -10, -10, -10, -10, -20,
]

BISHOP_PST_EG = [
   -20, -10, -10, -10, -10, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,  10,  10,  10,  10,   0, -10,
   -10,   0,  10,  15,  15,  10,   0, -10,
   -10,   0,  10,  15,  15,  10,   0, -10,
   -10,   0,  10,  10,  10,  10,   0, -10,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -20, -10, -10, -10, -10, -10, -10, -20,
]

# -- Rooks --
ROOK_PST_MG = [
     0,   0,   0,   5,   5,   0,   0,   0,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
     5,  10,  10,  10,  10,  10,  10,   5,
     0,   0,   0,   0,   0,   0,   0,   0,
]

ROOK_PST_EG = [
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
]

# -- Queens --
QUEEN_PST_MG = [
   -20, -10, -10,  -5,  -5, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,   5,   5,   5,   5,   0, -10,
    -5,   0,   5,   5,   5,   5,   0,  -5,
     0,   0,   5,   5,   5,   5,   0,  -5,
   -10,   5,   5,   5,   5,   5,   0, -10,
   -10,   0,   5,   0,   0,   0,   0, -10,
   -20, -10, -10,  -5,  -5, -10, -10, -20,
]

QUEEN_PST_EG = [
   -20, -10, -10,  -5,  -5, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,   5,   5,   5,   5,   0, -10,
    -5,   0,   5,  10,  10,   5,   0,  -5,
    -5,   0,   5,  10,  10,   5,   0,  -5,
   -10,   0,   5,   5,   5,   5,   0, -10,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -20, -10, -10,  -5,  -5, -10, -10, -20,
]

# -- Kings --
KING_PST_MG = [
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -20, -30, -30, -40, -40, -30, -30, -20,
   -10, -20, -20, -20, -20, -20, -20, -10,
    20,  20,   0,   0,   0,   0,  20,  20,
    20,  30,  10,   0,   0,  10,  30,  20,
]

KING_PST_EG = [
   -50, -40, -30, -20, -20, -30, -40, -50,
   -30, -20, -10,   0,   0, -10, -20, -30,
   -30, -10,  20,  30,  30,  20, -10, -30,
   -30, -10,  30,  40,  40,  30, -10, -30,
   -30, -10,  30,  40,  40,  30, -10, -30,
   -30, -10,  20,  30,  30,  20, -10, -30,
   -30, -30,   0,   0,   0,   0, -30, -30,
   -50, -30, -30, -30, -30, -30, -30, -50,
]

# fmt: on

PST_MG = {
    chess.PAWN: PAWN_PST_MG,
    chess.KNIGHT: KNIGHT_PST_MG,
    chess.BISHOP: BISHOP_PST_MG,
    chess.ROOK: ROOK_PST_MG,
    chess.QUEEN: QUEEN_PST_MG,
    chess.KING: KING_PST_MG,
}

PST_EG = {
    chess.PAWN: PAWN_PST_EG,
    chess.KNIGHT: KNIGHT_PST_EG,
    chess.BISHOP: BISHOP_PST_EG,
    chess.ROOK: ROOK_PST_EG,
    chess.QUEEN: QUEEN_PST_EG,
    chess.KING: KING_PST_EG,
}

# ---------------------------------------------------------------------------
# EVALUATION PARAMETERS
# ---------------------------------------------------------------------------

BISHOP_PAIR_BONUS = 50
ROOK_OPEN_FILE_BONUS = 25
ROOK_SEMI_OPEN_FILE_BONUS = 15

DOUBLED_PAWN_PENALTY = 20
ISOLATED_PAWN_PENALTY = 15

PASSED_PAWN_BONUS = [0, 10, 20, 40, 60, 100, 150, 0]  # by rank progress

MOBILITY_WEIGHTS = {
    chess.KNIGHT: 4,
    chess.BISHOP: 5,
    chess.ROOK: 2,
    chess.QUEEN: 1,
}

KING_SHIELD_BONUS = 8
KING_SHIELD_PENALTY = 6
CASTLED_KING_BONUS = 18
TEMPO_BONUS = 10

# ---------------------------------------------------------------------------
# SEARCH PARAMETERS
# ---------------------------------------------------------------------------

NULL_MOVE_R = 2
FUTILITY_MARGIN = 200
ASPIRATION_WINDOW = 50
LMR_FULL_DEPTH_MOVES = 4
LMR_REDUCTION_LIMIT = 3

TT_SIZE = 1 << 20  # ~1M entries


# ---------------------------------------------------------------------------
# OPENING BOOK
# ---------------------------------------------------------------------------

_OPENING_LINES = [
    # === White repertoire (1.e4) ===
    # Ruy Lopez: 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 5.O-O
    ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1"],
    # Italian: 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6 4.d3
    ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "d2d3"],
    # Sicilian Open (2...d6): 1.e4 c5 2.Nf3 d6 3.d4 cxd4 4.Nxd4
    ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4"],
    # Sicilian Open (2...Nc6): 1.e4 c5 2.Nf3 Nc6 3.d4 cxd4 4.Nxd4
    ["e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4"],
    # French: 1.e4 e6 2.d4 d5 3.Nc3
    ["e2e4", "e7e6", "d2d4", "d7d5", "b1c3"],
    # Caro-Kann: 1.e4 c6 2.d4 d5 3.Nc3
    ["e2e4", "c7c6", "d2d4", "d7d5", "b1c3"],
    # Scandinavian: 1.e4 d5 2.exd5 Qxd5 3.Nc3
    ["e2e4", "d7d5", "e4d5", "d8d5", "b1c3"],
    # === Black repertoire vs 1.d4 ===
    # QGD: 1.d4 d5 2.c4 e6 3.Nc3 Nf6
    ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6"],
    # London: 1.d4 d5 2.Bf4 Nf6 3.e3 c5
    ["d2d4", "d7d5", "c1f4", "g8f6", "e2e3", "c7c5"],
    # 1.d4 d5 2.Nf3 Nf6 3.c4 e6
    ["d2d4", "d7d5", "g1f3", "g8f6", "c2c4", "e7e6"],
    # === Black repertoire vs 1.c4 / 1.Nf3 ===
    ["c2c4", "e7e5"],
    ["g1f3", "d7d5"],
]


def _build_opening_book():
    """Build opening book mapping position keys to moves."""
    book = {}
    for line in _OPENING_LINES:
        board = chess.Board()
        for uci in line:
            key = " ".join(board.fen().split()[:4])
            move = chess.Move.from_uci(uci)
            if key not in book:
                book[key] = move
            board.push(move)
    return book


OPENING_BOOK = _build_opening_book()


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


@dataclass
class TTEntry:
    """Transposition table entry."""
    depth: int
    score: int
    flag: int
    best_move: chess.Move | None


# ---------------------------------------------------------------------------
# EVALUATION
# ---------------------------------------------------------------------------

# Total non-pawn material at game start (both sides)
MAX_PHASE_MATERIAL = 2 * (2 * PIECE_VALUES[chess.KNIGHT]
                          + 2 * PIECE_VALUES[chess.BISHOP]
                          + 2 * PIECE_VALUES[chess.ROOK]
                          + PIECE_VALUES[chess.QUEEN])


def game_phase(board: chess.Board) -> float:
    """Returns 1.0 for opening/middlegame, 0.0 for pure endgame."""
    material = 0
    for piece_type in [chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
        material += len(board.pieces(piece_type, chess.WHITE)) * PIECE_VALUES[piece_type]
        material += len(board.pieces(piece_type, chess.BLACK)) * PIECE_VALUES[piece_type]
    return min(1.0, material / MAX_PHASE_MATERIAL)


def evaluate_material(board: chess.Board) -> tuple[int, int]:
    """Returns (white_material, black_material)."""
    w, b = 0, 0
    for piece_type, value in PIECE_VALUES.items():
        w += len(board.pieces(piece_type, chess.WHITE)) * value
        b += len(board.pieces(piece_type, chess.BLACK)) * value
    return w, b


def evaluate_pst(board: chess.Board, phase: float) -> int:
    """Piece-square table evaluation, interpolated by game phase. Returns white-relative."""
    mg_score = 0
    eg_score = 0
    for piece_type in chess.PIECE_TYPES:
        mg_table = PST_MG[piece_type]
        eg_table = PST_EG[piece_type]
        for sq in board.pieces(piece_type, chess.WHITE):
            mg_score += mg_table[sq]
            eg_score += eg_table[sq]
        for sq in board.pieces(piece_type, chess.BLACK):
            mg_score -= mg_table[chess.square_mirror(sq)]
            eg_score -= eg_table[chess.square_mirror(sq)]
    return int(phase * mg_score + (1.0 - phase) * eg_score)


def evaluate_pawns(board: chess.Board) -> int:
    """Pawn structure evaluation. Returns white-relative score."""
    score = 0
    for color in [chess.WHITE, chess.BLACK]:
        sign = 1 if color == chess.WHITE else -1
        enemy = not color
        pawns = board.pieces(chess.PAWN, color)
        enemy_pawns = board.pieces(chess.PAWN, enemy)

        files: list[list[int]] = [[] for _ in range(8)]
        enemy_files: list[list[int]] = [[] for _ in range(8)]
        for sq in pawns:
            files[chess.square_file(sq)].append(chess.square_rank(sq))
        for sq in enemy_pawns:
            enemy_files[chess.square_file(sq)].append(chess.square_rank(sq))

        for f_idx, ranks in enumerate(files):
            # Doubled pawns
            if len(ranks) > 1:
                score -= sign * DOUBLED_PAWN_PENALTY * (len(ranks) - 1)

            # Isolated pawns
            left = files[f_idx - 1] if f_idx > 0 else []
            right = files[f_idx + 1] if f_idx < 7 else []
            if not left and not right:
                score -= sign * ISOLATED_PAWN_PENALTY * len(ranks)

            # Passed pawns
            for rank in ranks:
                passed = True
                for delta in (-1, 0, 1):
                    ef = f_idx + delta
                    if not 0 <= ef < 8:
                        continue
                    for er in enemy_files[ef]:
                        if color == chess.WHITE and er > rank:
                            passed = False
                        if color == chess.BLACK and er < rank:
                            passed = False
                if passed:
                    progress = rank if color == chess.WHITE else 7 - rank
                    score += sign * PASSED_PAWN_BONUS[progress]

    return score


def evaluate_mobility(board: chess.Board) -> int:
    """Mobility evaluation. Returns white-relative score."""
    score = 0
    for color in [chess.WHITE, chess.BLACK]:
        sign = 1 if color == chess.WHITE else -1
        occupied_own = board.occupied_co[color]
        for piece_type, weight in MOBILITY_WEIGHTS.items():
            for sq in board.pieces(piece_type, color):
                attacks = board.attacks_mask(sq) & ~occupied_own
                score += sign * chess.popcount(attacks) * weight
    return score


def evaluate_king_safety(board: chess.Board, phase: float) -> int:
    """King safety evaluation. Only active in middlegame. Returns white-relative."""
    if phase < 0.3:
        return 0

    score = 0
    for color in [chess.WHITE, chess.BLACK]:
        sign = 1 if color == chess.WHITE else -1
        king_sq = board.king(color)
        if king_sq is None:
            continue

        rank = chess.square_rank(king_sq)
        file_idx = chess.square_file(king_sq)

        # Castled king bonus
        if color == chess.WHITE and king_sq in (chess.G1, chess.C1):
            score += sign * CASTLED_KING_BONUS
        elif color == chess.BLACK and king_sq in (chess.G8, chess.C8):
            score += sign * CASTLED_KING_BONUS

        # Pawn shield
        shield_rank = rank + (1 if color == chess.WHITE else -1)
        if 0 <= shield_rank <= 7:
            for delta in (-1, 0, 1):
                sf = file_idx + delta
                if not 0 <= sf <= 7:
                    continue
                shield_sq = chess.square(sf, shield_rank)
                piece = board.piece_at(shield_sq)
                if piece and piece.color == color and piece.piece_type == chess.PAWN:
                    score += sign * KING_SHIELD_BONUS
                else:
                    score -= sign * KING_SHIELD_PENALTY

    return int(score * phase)


def evaluate_bishop_pair(board: chess.Board) -> int:
    """Bishop pair bonus. Returns white-relative."""
    score = 0
    if len(board.pieces(chess.BISHOP, chess.WHITE)) >= 2:
        score += BISHOP_PAIR_BONUS
    if len(board.pieces(chess.BISHOP, chess.BLACK)) >= 2:
        score -= BISHOP_PAIR_BONUS
    return score


def evaluate_rook_files(board: chess.Board) -> int:
    """Rook on open/semi-open file bonus. Returns white-relative."""
    score = 0
    for color in [chess.WHITE, chess.BLACK]:
        sign = 1 if color == chess.WHITE else -1
        own_pawns = board.pieces(chess.PAWN, color)
        enemy_pawns = board.pieces(chess.PAWN, not color)
        for sq in board.pieces(chess.ROOK, color):
            f = chess.square_file(sq)
            own_on_file = any(chess.square_file(p) == f for p in own_pawns)
            enemy_on_file = any(chess.square_file(p) == f for p in enemy_pawns)
            if not own_on_file and not enemy_on_file:
                score += sign * ROOK_OPEN_FILE_BONUS
            elif not own_on_file:
                score += sign * ROOK_SEMI_OPEN_FILE_BONUS
    return score


def evaluate(board: chess.Board) -> int:
    """
    Full position evaluation. Returns score from side-to-move perspective.
    Positive = good for side to move.
    """
    if board.is_checkmate():
        return -MATE_SCORE
    if board.is_stalemate() or board.is_insufficient_material() or board.can_claim_draw():
        return DRAW_SCORE

    phase = game_phase(board)
    w_mat, b_mat = evaluate_material(board)
    material = w_mat - b_mat

    score = (
        material
        + evaluate_pst(board, phase)
        + evaluate_pawns(board)
        + evaluate_mobility(board)
        + evaluate_king_safety(board, phase)
        + evaluate_bishop_pair(board)
        + evaluate_rook_files(board)
        + TEMPO_BONUS
    )

    if board.turn == chess.WHITE:
        return score
    return -score


# ---------------------------------------------------------------------------
# MOVE ORDERING
# ---------------------------------------------------------------------------

class MoveOrderer:
    """Tracks killer moves and history heuristic across the search."""

    def __init__(self) -> None:
        self.killer_moves: dict[int, list[chess.Move]] = {}
        self.history: dict[tuple[bool, int, int], int] = {}  # (color, from, to) -> score

    def record_killer(self, move: chess.Move, ply: int) -> None:
        killers = self.killer_moves.setdefault(ply, [])
        if move in killers:
            killers.remove(move)
        killers.insert(0, move)
        del killers[2:]

    def record_history(self, board: chess.Board, move: chess.Move, depth: int) -> None:
        key = (board.turn, move.from_square, move.to_square)
        self.history[key] = self.history.get(key, 0) + depth * depth

    def score_move(
        self, board: chess.Board, move: chess.Move,
        tt_move: chess.Move | None, ply: int,
    ) -> int:
        # TT move first
        if tt_move is not None and move == tt_move:
            return 10_000_000

        score = 0

        # Promotions
        if move.promotion:
            score += 800_000 + PIECE_VALUES.get(move.promotion, 0)

        # Captures: MVV-LVA
        if board.is_capture(move):
            victim = board.piece_type_at(move.to_square)
            if victim is None and board.is_en_passant(move):
                victim = chess.PAWN
            attacker = board.piece_type_at(move.from_square) or chess.PAWN
            score += 500_000 + 16 * PIECE_VALUES.get(victim or chess.PAWN, 0) - PIECE_VALUES[attacker]
            return score

        # Killer moves
        killers = self.killer_moves.get(ply, [])
        if move in killers:
            score += 300_000 - 10_000 * killers.index(move)
            return score

        # Checks
        if board.gives_check(move):
            score += 50_000

        # Castling
        if board.is_castling(move):
            score += 10_000

        # History heuristic
        key = (board.turn, move.from_square, move.to_square)
        score += self.history.get(key, 0)

        return score

    def order_moves(
        self, board: chess.Board, moves: list[chess.Move],
        tt_move: chess.Move | None, ply: int,
    ) -> list[chess.Move]:
        moves.sort(
            key=lambda m: self.score_move(board, m, tt_move, ply),
            reverse=True,
        )
        return moves


# ---------------------------------------------------------------------------
# SEARCH
# ---------------------------------------------------------------------------

class Searcher:
    """Alpha-beta searcher with iterative deepening."""

    def __init__(self) -> None:
        self.nodes = 0
        self.tt: dict[int, TTEntry] = {}
        self.orderer = MoveOrderer()
        self._stop = False
        self._deadline: float | None = None

    def _check_time(self) -> bool:
        if self._deadline is not None and time.monotonic() >= self._deadline:
            self._stop = True
        return self._stop

    def _terminal_score(self, board: chess.Board, ply: int) -> int | None:
        if board.is_checkmate():
            return -MATE_SCORE + ply
        if (board.is_stalemate()
                or board.is_insufficient_material()
                or board.can_claim_fifty_moves()
                or board.can_claim_threefold_repetition()):
            return DRAW_SCORE
        return None

    def _quiescence(self, board: chess.Board, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        if self._check_time():
            return 0

        terminal = self._terminal_score(board, ply)
        if terminal is not None:
            return terminal

        in_check = board.is_check()
        if not in_check:
            stand_pat = evaluate(board)
            if stand_pat >= beta:
                return stand_pat
            alpha = max(alpha, stand_pat)

        # In check: search all moves. Otherwise: captures + promotions only.
        moves = list(board.legal_moves)
        if not in_check:
            moves = [m for m in moves if board.is_capture(m) or m.promotion]

        self.orderer.order_moves(board, moves, None, ply)

        for move in moves:
            board.push(move)
            score = -self._quiescence(board, -beta, -alpha, ply + 1)
            board.pop()

            if self._stop:
                return 0
            if score >= beta:
                return score
            alpha = max(alpha, score)

        return alpha

    def _alpha_beta(
        self, board: chess.Board, depth: int,
        alpha: int, beta: int, ply: int,
    ) -> int:
        self.nodes += 1
        if self._check_time():
            return 0

        terminal = self._terminal_score(board, ply)
        if terminal is not None:
            return terminal

        # Check extension
        in_check = board.is_check()
        if in_check:
            depth += 1

        if depth <= 0:
            return self._quiescence(board, alpha, beta, ply)

        # TT probe
        tt_key = hash(board._transposition_key())
        tt_entry = self.tt.get(tt_key)
        tt_move = tt_entry.best_move if tt_entry else None

        if tt_entry and tt_entry.depth >= depth:
            if tt_entry.flag == EXACT:
                return tt_entry.score
            if tt_entry.flag == LOWER_BOUND:
                alpha = max(alpha, tt_entry.score)
            elif tt_entry.flag == UPPER_BOUND:
                beta = min(beta, tt_entry.score)
            if alpha >= beta:
                return tt_entry.score

        # Null move pruning
        if (depth >= 3
                and not in_check
                and not board.is_game_over()
                and ply > 0):
            board.push(chess.Move.null())
            score = -self._alpha_beta(board, depth - 1 - NULL_MOVE_R, -beta, -beta + 1, ply + 1)
            board.pop()
            if self._stop:
                return 0
            if score >= beta:
                return score

        alpha_orig = alpha
        best_move: chess.Move | None = None
        best_score = -INFINITY

        moves = list(board.legal_moves)
        self.orderer.order_moves(board, moves, tt_move, ply)

        for i, move in enumerate(moves):
            # Late move reductions
            reduction = 0
            if (i >= LMR_FULL_DEPTH_MOVES
                    and depth >= LMR_REDUCTION_LIMIT
                    and not in_check
                    and not board.is_capture(move)
                    and not move.promotion):
                reduction = 1

            board.push(move)

            # Search with reduction
            if reduction > 0:
                score = -self._alpha_beta(board, depth - 1 - reduction, -alpha - 1, -alpha, ply + 1)
                # Re-search at full depth if it beat alpha
                if score > alpha and not self._stop:
                    score = -self._alpha_beta(board, depth - 1, -beta, -alpha, ply + 1)
            else:
                score = -self._alpha_beta(board, depth - 1, -beta, -alpha, ply + 1)

            board.pop()

            if self._stop:
                return 0

            if score > best_score:
                best_score = score
                best_move = move

            if score > alpha:
                alpha = score

            if alpha >= beta:
                # Beta cutoff — record killer + history for quiet moves
                if not board.is_capture(move):
                    self.orderer.record_killer(move, ply)
                    self.orderer.record_history(board, move, depth)
                break

        if best_move is None:
            return self._terminal_score(board, ply) or DRAW_SCORE

        # TT store
        if best_score <= alpha_orig:
            flag = UPPER_BOUND
        elif best_score >= beta:
            flag = LOWER_BOUND
        else:
            flag = EXACT

        # Evict if TT is too large
        if len(self.tt) >= TT_SIZE:
            self.tt.clear()

        self.tt[tt_key] = TTEntry(
            depth=depth, score=best_score,
            flag=flag, best_move=best_move,
        )

        return best_score

    def _extract_pv(self, board: chess.Board, depth: int) -> list[str]:
        """Extract principal variation from TT."""
        pv: list[str] = []
        seen: set[int] = set()
        probe = board.copy(stack=False)

        for _ in range(depth):
            key = hash(probe._transposition_key())
            if key in seen:
                break
            seen.add(key)
            entry = self.tt.get(key)
            if entry is None or entry.best_move is None or not probe.is_legal(entry.best_move):
                break
            pv.append(probe.san(entry.best_move))
            probe.push(entry.best_move)

        return pv

    def search(
        self, board: chess.Board,
        max_depth: int | None = None,
        movetime_ms: int | None = None,
    ) -> SearchResult:
        """
        Iterative deepening search.

        Args:
            board: Current position.
            max_depth: Maximum search depth. If None, searches until time runs out.
            movetime_ms: Time limit in milliseconds. If None, searches to max_depth.

        Returns:
            SearchResult with best move, score, depth, nodes, PV, and timing.
        """
        if board.is_game_over(claim_draw=True):
            raise ValueError("Cannot search a finished game.")

        self.nodes = 0
        self._stop = False
        self._deadline = (
            time.monotonic() + movetime_ms / 1000.0
            if movetime_ms is not None and movetime_ms > 0
            else None
        )

        target_depth = max_depth if max_depth and max_depth > 0 else MAX_ITERATIVE_DEPTH
        if max_depth is None and movetime_ms is None:
            raise ValueError("Must specify max_depth or movetime_ms (or both).")

        start = time.monotonic()
        best_move: chess.Move | None = None
        best_score = -INFINITY
        completed_depth = 0
        depths_info: list[dict] = []

        for current_depth in range(1, target_depth + 1):
            if self._stop:
                break

            # Aspiration window (only after depth 4)
            if current_depth >= 4 and best_score != -INFINITY:
                alpha = best_score - ASPIRATION_WINDOW
                beta = best_score + ASPIRATION_WINDOW
                score = self._alpha_beta(board, current_depth, alpha, beta, 0)

                # Re-search with full window if aspiration failed
                if not self._stop and (score <= alpha or score >= beta):
                    score = self._alpha_beta(board, current_depth, -INFINITY, INFINITY, 0)
            else:
                score = self._alpha_beta(board, current_depth, -INFINITY, INFINITY, 0)

            if self._stop:
                break

            entry = self.tt.get(hash(board._transposition_key()))
            if entry and entry.best_move and board.is_legal(entry.best_move):
                best_move = entry.best_move
                best_score = score
                completed_depth = current_depth

                pv = self._extract_pv(board, current_depth)
                elapsed = (time.monotonic() - start) * 1000
                depths_info.append({
                    "depth": current_depth,
                    "score": score,
                    "nodes": self.nodes,
                    "pv": pv,
                    "time_ms": round(elapsed, 1),
                })

        if best_move is None:
            best_move = next(iter(board.legal_moves))

        elapsed = (time.monotonic() - start) * 1000
        pv = self._extract_pv(board, completed_depth) if completed_depth > 0 else []

        return SearchResult(
            move=best_move,
            score=best_score,
            depth=completed_depth,
            nodes=self.nodes,
            pv=pv,
            time_ms=round(elapsed, 1),
            depths_completed=depths_info,
        )


# ---------------------------------------------------------------------------
# PUBLIC INTERFACE
# ---------------------------------------------------------------------------

_searcher = Searcher()


def choose_move(
    board: chess.Board,
    depth: int | None = None,
    movetime_ms: int | None = None,
) -> SearchResult:
    """
    Choose the best move for the current position.

    Args:
        board: Current board state.
        depth: Fixed search depth (plies).
        movetime_ms: Time limit in milliseconds.

    Returns:
        SearchResult with move, score, depth, nodes, PV, and telemetry.
    """
    if _USE_RUST:
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

    # Python fallback: opening book + Python search
    key = " ".join(board.fen().split()[:4])
    book_move = OPENING_BOOK.get(key)
    if book_move and book_move in board.legal_moves:
        return SearchResult(
            move=book_move, score=0, depth=0, nodes=0, pv=[], time_ms=0.0,
        )

    return _searcher.search(board, max_depth=depth, movetime_ms=movetime_ms)


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
