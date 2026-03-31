"""
Interactive CLI for playing against the chess engine.

Usage:
    uv run play.py                    # Play with default settings
    uv run play.py --depth 3          # Easy (shallow search)
    uv run play.py --depth 8          # Hard (deep search)
    uv run play.py --movetime 5000    # 5 seconds per move
    uv run play.py --color black      # Play as black
"""

from __future__ import annotations

import argparse
import sys

import chess

import engine

# ---------------------------------------------------------------------------
# BOARD DISPLAY
# ---------------------------------------------------------------------------

PIECE_UNICODE = {
    "P": "\u2659", "N": "\u2658", "B": "\u2657", "R": "\u2656", "Q": "\u2655", "K": "\u2654",
    "p": "\u265F", "n": "\u265E", "b": "\u265D", "r": "\u265C", "q": "\u265B", "k": "\u265A",
}

# ANSI colors
LIGHT_SQ = "\033[48;5;223m"  # light tan
DARK_SQ = "\033[48;5;136m"   # brown
HIGHLIGHT = "\033[48;5;228m" # yellow highlight
CHECK_BG = "\033[48;5;196m"  # red
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def print_board(
    board: chess.Board,
    perspective: chess.Color = chess.WHITE,
    last_move: chess.Move | None = None,
) -> None:
    """Print a colored Unicode chessboard."""
    highlight_squares: set[int] = set()
    if last_move:
        highlight_squares.add(last_move.from_square)
        highlight_squares.add(last_move.to_square)

    check_square: int | None = None
    if board.is_check():
        check_square = board.king(board.turn)

    ranks = range(7, -1, -1) if perspective == chess.WHITE else range(8)
    files = range(8) if perspective == chess.WHITE else range(7, -1, -1)

    print()
    for rank in ranks:
        line = f" {rank + 1}  "
        for file in files:
            sq = chess.square(file, rank)
            piece = board.piece_at(sq)
            is_light = (rank + file) % 2 == 1

            # Choose background
            if sq == check_square:
                bg = CHECK_BG
            elif sq in highlight_squares:
                bg = HIGHLIGHT
            elif is_light:
                bg = LIGHT_SQ
            else:
                bg = DARK_SQ

            if piece:
                ch = PIECE_UNICODE.get(piece.symbol(), "?")
                line += f"{bg} {ch} {RESET}"
            else:
                line += f"{bg}   {RESET}"

        print(line)

    if perspective == chess.WHITE:
        print("     a  b  c  d  e  f  g  h")
    else:
        print("     h  g  f  e  d  c  b  a")
    print()


# ---------------------------------------------------------------------------
# THINKING DISPLAY
# ---------------------------------------------------------------------------

def format_score(score: int) -> str:
    """Format centipawn score as +/- pawns or mate."""
    if abs(score) >= engine.MATE_SCORE - 200:
        mate_in = (engine.MATE_SCORE - abs(score) + 1) // 2
        return f"{'#' if score > 0 else '#-'}{mate_in}"
    return f"{score / 100:+.2f}"


def show_thinking(result: engine.SearchResult) -> None:
    """Display engine thinking info."""
    score_str = format_score(result.score)
    pv_str = " ".join(result.pv[:8]) if result.pv else "..."
    nps = int(result.nodes / (result.time_ms / 1000)) if result.time_ms > 0 else 0
    print(f"{DIM}  depth {result.depth} | eval {score_str} | "
          f"{result.nodes:,} nodes | {result.time_ms:.0f}ms | {nps:,} nps{RESET}")
    if pv_str:
        print(f"{DIM}  PV: {pv_str}{RESET}")


# ---------------------------------------------------------------------------
# MOVE PARSING
# ---------------------------------------------------------------------------

def parse_move(board: chess.Board, text: str) -> chess.Move | None:
    """Try to parse user input as UCI or SAN notation."""
    text = text.strip()
    if not text:
        return None

    # Try UCI first (e.g., e2e4)
    try:
        move = chess.Move.from_uci(text)
        if move in board.legal_moves:
            return move
    except (ValueError, chess.InvalidMoveError):
        pass

    # Try SAN (e.g., Nf3, e4, O-O)
    try:
        return board.parse_san(text)
    except (ValueError, chess.IllegalMoveError, chess.AmbiguousMoveError) as e:
        print(f"  Invalid move: {e}")
        return None


# ---------------------------------------------------------------------------
# MAIN GAME LOOP
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play chess against the engine.")
    parser.add_argument("--depth", type=int, default=None,
                        help="Search depth (default: time-based)")
    parser.add_argument("--movetime", type=int, default=2000,
                        help="Time per move in ms (default: 2000, ignored if --depth set)")
    parser.add_argument("--color", choices=["white", "black", "random"], default="white",
                        help="Your color (default: white)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.color == "random":
        import random
        player_color = random.choice([chess.WHITE, chess.BLACK])
    else:
        player_color = chess.WHITE if args.color == "white" else chess.BLACK

    engine_color = not player_color
    color_name = "White" if player_color == chess.WHITE else "Black"

    print(f"\n{BOLD}=== Chess Autoresearch Engine ==={RESET}")
    if args.depth:
        print(f"Engine: depth {args.depth}")
    else:
        print(f"Engine: {args.movetime}ms per move")
    print(f"You are playing as {color_name}")
    print(f"Enter moves as UCI (e2e4) or SAN (Nf3, e4, O-O)")
    print(f"Type 'quit' to resign, 'undo' to take back\n")

    board = chess.Board()
    last_move: chess.Move | None = None

    while not board.is_game_over(claim_draw=True):
        print_board(board, perspective=player_color, last_move=last_move)

        if board.turn == player_color:
            # Human's turn
            move_num = board.fullmove_number
            side = "W" if board.turn == chess.WHITE else "B"
            try:
                text = input(f"  {move_num}. [{side}] Your move: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGame aborted.")
                return

            if text.lower() in ("quit", "resign", "q"):
                print("\nYou resigned.")
                return
            if text.lower() == "undo":
                if len(board.move_stack) >= 2:
                    board.pop()
                    board.pop()
                    last_move = board.peek() if board.move_stack else None
                    print("  Took back last move pair.")
                else:
                    print("  Nothing to undo.")
                continue

            move = parse_move(board, text)
            if move is None:
                continue

            last_move = move
            board.push(move)

        else:
            # Engine's turn
            print("  Engine is thinking...")
            if args.depth:
                result = engine.choose_move(board, depth=args.depth)
            else:
                result = engine.choose_move(board, movetime_ms=args.movetime)

            san = board.san(result.move)
            show_thinking(result)
            print(f"  {BOLD}Engine plays: {san}{RESET}")

            last_move = result.move
            board.push(result.move)

    # Game over
    print_board(board, perspective=player_color, last_move=last_move)
    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        print("Game over: unknown result")
    elif outcome.winner is None:
        print(f"Draw: {outcome.termination.name.lower()}")
    elif outcome.winner == player_color:
        print("You win!")
    else:
        print("Engine wins!")


if __name__ == "__main__":
    main()
