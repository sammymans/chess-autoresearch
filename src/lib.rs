//! Chess Engine Rust Backend
//!
//! This is the ONLY Rust file the autoresearch agent modifies.
//! Everything is fair game: piece values, piece-square tables, evaluation terms,
//! search heuristics, move ordering, pruning parameters.

use pyo3::prelude::*;
use pyo3::types::PyDict;

use chess::{
    BitBoard, Board, BoardStatus, ChessMove, Color, MoveGen, Piece, Square,
    ALL_SQUARES, EMPTY,
};
use std::collections::HashMap;
use std::str::FromStr;
use std::sync::{LazyLock, Mutex};
use std::time::Instant;

// ============================================================
// CONSTANTS
// ============================================================

const INFINITY: i32 = 1_000_000;
const MATE_SCORE: i32 = 100_000;
const DRAW_SCORE: i32 = 0;
const MAX_DEPTH: usize = 64;

const TT_FLAG_EXACT: u8 = 0;
const TT_FLAG_LOWER: u8 = 1;
const TT_FLAG_UPPER: u8 = 2;

// ============================================================
// PIECE VALUES
// ============================================================

const PAWN_VALUE: i32 = 100;
const KNIGHT_VALUE: i32 = 320;
const BISHOP_VALUE: i32 = 330;
const ROOK_VALUE: i32 = 500;
const QUEEN_VALUE: i32 = 900;

fn piece_value(piece: Piece) -> i32 {
    match piece {
        Piece::Pawn => PAWN_VALUE,
        Piece::Knight => KNIGHT_VALUE,
        Piece::Bishop => BISHOP_VALUE,
        Piece::Rook => ROOK_VALUE,
        Piece::Queen => QUEEN_VALUE,
        Piece::King => 0,
    }
}

// ============================================================
// PIECE-SQUARE TABLES
// Indexed from white's perspective, A1=0, H8=63.
// Each row is one rank: rank 1 (index 0-7) to rank 8 (56-63).
// For black pieces, flip rank: index ^ 56.
// ============================================================

// -- Pawns --
const PAWN_PST_MG: [i32; 64] = [
     0,   0,   0,   0,   0,   0,   0,   0,
     5,  10,  10, -20, -20,  10,  10,   5,
     5,  -5, -10,   0,   0, -10,  -5,   5,
     0,   0,   0,  20,  20,   0,   0,   0,
     5,   5,  10,  25,  25,  10,   5,   5,
    10,  10,  20,  30,  30,  20,  10,  10,
    50,  50,  50,  50,  50,  50,  50,  50,
     0,   0,   0,   0,   0,   0,   0,   0,
];

const PAWN_PST_EG: [i32; 64] = [
     0,   0,   0,   0,   0,   0,   0,   0,
     5,   5,   5,   5,   5,   5,   5,   5,
    10,  10,  10,  10,  10,  10,  10,  10,
    20,  20,  20,  20,  20,  20,  20,  20,
    30,  30,  30,  30,  30,  30,  30,  30,
    50,  50,  50,  50,  50,  50,  50,  50,
    80,  80,  80,  80,  80,  80,  80,  80,
     0,   0,   0,   0,   0,   0,   0,   0,
];

// -- Knights --
const KNIGHT_PST_MG: [i32; 64] = [
   -50, -40, -30, -30, -30, -30, -40, -50,
   -40, -20,   0,   0,   0,   0, -20, -40,
   -30,   0,  10,  15,  15,  10,   0, -30,
   -30,   5,  15,  20,  20,  15,   5, -30,
   -30,   0,  15,  20,  20,  15,   0, -30,
   -30,   5,  10,  15,  15,  10,   5, -30,
   -40, -20,   0,   5,   5,   0, -20, -40,
   -50, -40, -30, -30, -30, -30, -40, -50,
];

const KNIGHT_PST_EG: [i32; 64] = [
   -50, -40, -30, -30, -30, -30, -40, -50,
   -40, -20,   0,   0,   0,   0, -20, -40,
   -30,   0,  10,  15,  15,  10,   0, -30,
   -30,   5,  15,  20,  20,  15,   5, -30,
   -30,   0,  15,  20,  20,  15,   0, -30,
   -30,   5,  10,  15,  15,  10,   5, -30,
   -40, -20,   0,   5,   5,   0, -20, -40,
   -50, -40, -30, -30, -30, -30, -40, -50,
];

// -- Bishops --
const BISHOP_PST_MG: [i32; 64] = [
   -20, -10, -10, -10, -10, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,   5,  10,  10,   5,   0, -10,
   -10,   5,   5,  10,  10,   5,   5, -10,
   -10,   0,  10,  10,  10,  10,   0, -10,
   -10,  10,  10,  10,  10,  10,  10, -10,
   -10,   5,   0,   0,   0,   0,   5, -10,
   -20, -10, -10, -10, -10, -10, -10, -20,
];

const BISHOP_PST_EG: [i32; 64] = [
   -20, -10, -10, -10, -10, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,  10,  10,  10,  10,   0, -10,
   -10,   0,  10,  15,  15,  10,   0, -10,
   -10,   0,  10,  15,  15,  10,   0, -10,
   -10,   0,  10,  10,  10,  10,   0, -10,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -20, -10, -10, -10, -10, -10, -10, -20,
];

// -- Rooks --
const ROOK_PST_MG: [i32; 64] = [
     0,   0,   0,   5,   5,   0,   0,   0,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
     5,  10,  10,  10,  10,  10,  10,   5,
     0,   0,   0,   0,   0,   0,   0,   0,
];

const ROOK_PST_EG: [i32; 64] = [0; 64];

// -- Queens --
const QUEEN_PST_MG: [i32; 64] = [
   -20, -10, -10,  -5,  -5, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,   5,   5,   5,   5,   0, -10,
    -5,   0,   5,   5,   5,   5,   0,  -5,
     0,   0,   5,   5,   5,   5,   0,  -5,
   -10,   5,   5,   5,   5,   5,   0, -10,
   -10,   0,   5,   0,   0,   0,   0, -10,
   -20, -10, -10,  -5,  -5, -10, -10, -20,
];

const QUEEN_PST_EG: [i32; 64] = [
   -20, -10, -10,  -5,  -5, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,   5,   5,   5,   5,   0, -10,
    -5,   0,   5,  10,  10,   5,   0,  -5,
    -5,   0,   5,  10,  10,   5,   0,  -5,
   -10,   0,   5,   5,   5,   5,   0, -10,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -20, -10, -10,  -5,  -5, -10, -10, -20,
];

// -- Kings --
const KING_PST_MG: [i32; 64] = [
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -20, -30, -30, -40, -40, -30, -30, -20,
   -10, -20, -20, -20, -20, -20, -20, -10,
    20,  20,   0,   0,   0,   0,  20,  20,
    20,  30,  10,   0,   0,  10,  30,  20,
];

const KING_PST_EG: [i32; 64] = [
   -50, -40, -30, -20, -20, -30, -40, -50,
   -30, -20, -10,   0,   0, -10, -20, -30,
   -30, -10,  20,  30,  30,  20, -10, -30,
   -30, -10,  30,  40,  40,  30, -10, -30,
   -30, -10,  30,  40,  40,  30, -10, -30,
   -30, -10,  20,  30,  30,  20, -10, -30,
   -30, -30,   0,   0,   0,   0, -30, -30,
   -50, -30, -30, -30, -30, -30, -30, -50,
];

fn pst_mg(piece: Piece, sq_idx: usize) -> i32 {
    match piece {
        Piece::Pawn => PAWN_PST_MG[sq_idx],
        Piece::Knight => KNIGHT_PST_MG[sq_idx],
        Piece::Bishop => BISHOP_PST_MG[sq_idx],
        Piece::Rook => ROOK_PST_MG[sq_idx],
        Piece::Queen => QUEEN_PST_MG[sq_idx],
        Piece::King => KING_PST_MG[sq_idx],
    }
}

fn pst_eg(piece: Piece, sq_idx: usize) -> i32 {
    match piece {
        Piece::Pawn => PAWN_PST_EG[sq_idx],
        Piece::Knight => KNIGHT_PST_EG[sq_idx],
        Piece::Bishop => BISHOP_PST_EG[sq_idx],
        Piece::Rook => ROOK_PST_EG[sq_idx],
        Piece::Queen => QUEEN_PST_EG[sq_idx],
        Piece::King => KING_PST_EG[sq_idx],
    }
}

// ============================================================
// EVALUATION PARAMETERS
// ============================================================

const BISHOP_PAIR_BONUS: i32 = 50;
const ROOK_OPEN_FILE_BONUS: i32 = 25;
const ROOK_SEMI_OPEN_FILE_BONUS: i32 = 15;

const DOUBLED_PAWN_PENALTY: i32 = 20;
const ISOLATED_PAWN_PENALTY: i32 = 15;

const PASSED_PAWN_BONUS: [i32; 8] = [0, 10, 20, 40, 60, 100, 150, 0];

const MOBILITY_WEIGHT_KNIGHT: i32 = 4;
const MOBILITY_WEIGHT_BISHOP: i32 = 5;
const MOBILITY_WEIGHT_ROOK: i32 = 2;
const MOBILITY_WEIGHT_QUEEN: i32 = 1;

const KING_SHIELD_BONUS: i32 = 8;
const KING_SHIELD_PENALTY: i32 = 6;
const CASTLED_KING_BONUS: i32 = 18;
const TEMPO_BONUS: i32 = 10;

// ============================================================
// SEARCH PARAMETERS
// ============================================================

const NULL_MOVE_R_BASE: i32 = 2;
const NULL_MOVE_R_DIVISOR: i32 = 4;
const ASPIRATION_WINDOW: i32 = 50;
const LMR_FULL_DEPTH_MOVES: usize = 4;
const LMR_REDUCTION_LIMIT: i32 = 3;

const TT_SIZE: usize = 1 << 22; // ~4M entries

// ============================================================
// TRANSPOSITION TABLE
// ============================================================

#[derive(Clone, Copy)]
struct TTEntry {
    key: u64,
    score: i32,
    depth: i16,
    flag: u8,
    best_move_from: u8,
    best_move_to: u8,
    best_move_promo: u8, // 0=none, 1=knight, 2=bishop, 3=rook, 4=queen
}

impl Default for TTEntry {
    fn default() -> Self {
        Self {
            key: 0,
            score: 0,
            depth: -1,
            flag: 0,
            best_move_from: 0,
            best_move_to: 0,
            best_move_promo: 0,
        }
    }
}

impl TTEntry {
    fn store_move(&mut self, mv: Option<ChessMove>) {
        if let Some(m) = mv {
            self.best_move_from = m.get_source().to_index() as u8;
            self.best_move_to = m.get_dest().to_index() as u8;
            self.best_move_promo = match m.get_promotion() {
                Some(Piece::Knight) => 1,
                Some(Piece::Bishop) => 2,
                Some(Piece::Rook) => 3,
                Some(Piece::Queen) => 4,
                _ => 0,
            };
        } else {
            self.best_move_from = 64; // sentinel
        }
    }

    fn get_move(&self) -> Option<ChessMove> {
        if self.best_move_from >= 64 {
            return None;
        }
        let from = ALL_SQUARES[self.best_move_from as usize];
        let to = ALL_SQUARES[self.best_move_to as usize];
        let promo = match self.best_move_promo {
            1 => Some(Piece::Knight),
            2 => Some(Piece::Bishop),
            3 => Some(Piece::Rook),
            4 => Some(Piece::Queen),
            _ => None,
        };
        Some(ChessMove::new(from, to, promo))
    }
}

struct TranspositionTable {
    entries: Vec<TTEntry>,
    size: usize,
}

impl TranspositionTable {
    fn new(size: usize) -> Self {
        Self {
            entries: vec![TTEntry::default(); size],
            size,
        }
    }

    fn probe(&self, key: u64) -> Option<&TTEntry> {
        let idx = (key as usize) % self.size;
        let entry = &self.entries[idx];
        if entry.key == key && entry.depth >= 0 {
            Some(entry)
        } else {
            None
        }
    }

    fn store(&mut self, key: u64, score: i32, depth: i32, flag: u8, best_move: Option<ChessMove>) {
        let idx = (key as usize) % self.size;
        let entry = &mut self.entries[idx];
        // Always replace (simplest scheme)
        entry.key = key;
        entry.score = score;
        entry.depth = depth as i16;
        entry.flag = flag;
        entry.store_move(best_move);
    }
}

// ============================================================
// OPENING BOOK
// ============================================================

fn build_opening_book() -> HashMap<u64, ChessMove> {
    let lines: Vec<Vec<&str>> = vec![
        // White repertoire (1.e4)
        vec!["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1"],
        vec!["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "d2d3"],
        vec!["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4"],
        vec!["e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4"],
        vec!["e2e4", "e7e6", "d2d4", "d7d5", "b1c3"],
        vec!["e2e4", "c7c6", "d2d4", "d7d5", "b1c3"],
        vec!["e2e4", "d7d5", "e4d5", "d8d5", "b1c3"],
        // Black repertoire vs 1.d4
        vec!["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6"],
        vec!["d2d4", "d7d5", "c1f4", "g8f6", "e2e3", "c7c5"],
        vec!["d2d4", "d7d5", "g1f3", "g8f6", "c2c4", "e7e6"],
        // Black repertoire vs 1.c4 / 1.Nf3
        vec!["c2c4", "e7e5"],
        vec!["g1f3", "d7d5"],
    ];

    let mut book = HashMap::new();
    for line in &lines {
        let mut board = Board::default();
        for uci_str in line {
            let key = board.get_hash();
            if let Some(mv) = parse_uci(uci_str) {
                book.entry(key).or_insert(mv);
                board = board.make_move_new(mv);
            }
        }
    }
    book
}

fn parse_uci(uci: &str) -> Option<ChessMove> {
    if uci.len() < 4 {
        return None;
    }
    let from = Square::from_str(&uci[0..2]).ok()?;
    let to = Square::from_str(&uci[2..4]).ok()?;
    let promotion = if uci.len() > 4 {
        match uci.as_bytes()[4] {
            b'q' => Some(Piece::Queen),
            b'r' => Some(Piece::Rook),
            b'b' => Some(Piece::Bishop),
            b'n' => Some(Piece::Knight),
            _ => None,
        }
    } else {
        None
    };
    Some(ChessMove::new(from, to, promotion))
}

static OPENING_BOOK: LazyLock<HashMap<u64, ChessMove>> = LazyLock::new(build_opening_book);

// ============================================================
// BITBOARD HELPERS
// ============================================================

fn iter_bits(mut bb: BitBoard) -> impl Iterator<Item = Square> {
    std::iter::from_fn(move || {
        if bb == EMPTY {
            None
        } else {
            let sq = bb.to_square();
            bb ^= BitBoard::from_square(sq);
            Some(sq)
        }
    })
}

fn popcount(bb: BitBoard) -> i32 {
    bb.popcnt() as i32
}

// ============================================================
// EVALUATION
// ============================================================

// Total non-pawn material at game start (both sides)
const MAX_PHASE_MATERIAL: i32 =
    2 * (2 * KNIGHT_VALUE + 2 * BISHOP_VALUE + 2 * ROOK_VALUE + QUEEN_VALUE);

fn game_phase(board: &Board) -> f32 {
    let mut material = 0;
    for &piece in &[Piece::Knight, Piece::Bishop, Piece::Rook, Piece::Queen] {
        let count = popcount(*board.pieces(piece));
        material += count * piece_value(piece);
    }
    (material as f32 / MAX_PHASE_MATERIAL as f32).min(1.0)
}

fn evaluate_material(board: &Board) -> (i32, i32) {
    let mut w = 0;
    let mut b = 0;
    let white = board.color_combined(Color::White);
    let black = board.color_combined(Color::Black);
    for &piece in &[Piece::Pawn, Piece::Knight, Piece::Bishop, Piece::Rook, Piece::Queen] {
        let val = piece_value(piece);
        w += popcount(board.pieces(piece) & white) * val;
        b += popcount(board.pieces(piece) & black) * val;
    }
    (w, b)
}

fn evaluate_pst(board: &Board, phase: f32) -> i32 {
    let mut mg = 0i32;
    let mut eg = 0i32;
    let white = board.color_combined(Color::White);
    let black = board.color_combined(Color::Black);

    for &piece in &[Piece::Pawn, Piece::Knight, Piece::Bishop, Piece::Rook, Piece::Queen, Piece::King] {
        let piece_bb = board.pieces(piece);

        for sq in iter_bits(piece_bb & white) {
            let idx = sq.to_index();
            mg += pst_mg(piece, idx);
            eg += pst_eg(piece, idx);
        }

        for sq in iter_bits(piece_bb & black) {
            let idx = sq.to_index() ^ 56; // flip rank for black
            mg -= pst_mg(piece, idx);
            eg -= pst_eg(piece, idx);
        }
    }

    (phase * mg as f32 + (1.0 - phase) * eg as f32) as i32
}

fn evaluate_pawns(board: &Board) -> i32 {
    let mut score = 0i32;
    let white = board.color_combined(Color::White);
    let black = board.color_combined(Color::Black);
    let pawns = board.pieces(Piece::Pawn);

    for &(color, sign) in &[(Color::White, 1i32), (Color::Black, -1i32)] {
        let own_mask = if color == Color::White { white } else { black };
        let enemy_mask = if color == Color::White { black } else { white };
        let own_pawns = pawns & own_mask;
        let enemy_pawns = pawns & enemy_mask;

        // Build file arrays
        let mut own_files = [0u8; 8]; // count of own pawns per file
        let mut enemy_file_mask = [0u8; 8]; // bitmask of enemy pawn ranks per file

        for sq in iter_bits(own_pawns) {
            own_files[sq.get_file().to_index()] += 1;
        }
        for sq in iter_bits(enemy_pawns) {
            let rank = sq.get_rank().to_index();
            enemy_file_mask[sq.get_file().to_index()] |= 1 << rank;
        }

        for sq in iter_bits(own_pawns) {
            let file = sq.get_file().to_index();
            let rank = sq.get_rank().to_index();

            // Doubled pawns
            if own_files[file] > 1 {
                score -= sign * DOUBLED_PAWN_PENALTY / (own_files[file] as i32);
            }

            // Isolated pawns
            let has_left = file > 0 && own_files[file - 1] > 0;
            let has_right = file < 7 && own_files[file + 1] > 0;
            if !has_left && !has_right {
                score -= sign * ISOLATED_PAWN_PENALTY;
            }

            // Passed pawns
            let mut passed = true;
            for delta in [-1i32, 0, 1] {
                let ef = file as i32 + delta;
                if ef < 0 || ef > 7 {
                    continue;
                }
                let enemy_mask_file = enemy_file_mask[ef as usize];
                if color == Color::White {
                    // Check if any enemy pawn on this file has rank > our rank
                    let blocking = enemy_mask_file >> (rank + 1);
                    if blocking != 0 {
                        passed = false;
                        break;
                    }
                } else {
                    // Check if any enemy pawn on this file has rank < our rank
                    let blocking = enemy_mask_file & ((1 << rank) - 1);
                    if blocking != 0 {
                        passed = false;
                        break;
                    }
                }
            }
            if passed {
                let progress = if color == Color::White { rank } else { 7 - rank };
                score += sign * PASSED_PAWN_BONUS[progress];
            }
        }
    }
    score
}

fn evaluate_mobility(board: &Board) -> i32 {
    let mut score = 0i32;

    for &(color, sign) in &[(Color::White, 1i32), (Color::Black, -1i32)] {
        let own = if color == Color::White {
            board.color_combined(Color::White)
        } else {
            board.color_combined(Color::Black)
        };

        // Count attacks for each piece type
        for &(piece, weight) in &[
            (Piece::Knight, MOBILITY_WEIGHT_KNIGHT),
            (Piece::Bishop, MOBILITY_WEIGHT_BISHOP),
            (Piece::Rook, MOBILITY_WEIGHT_ROOK),
            (Piece::Queen, MOBILITY_WEIGHT_QUEEN),
        ] {
            let piece_bb = *board.pieces(piece) & *own;
            for sq in iter_bits(piece_bb) {
                let blockers = *board.combined();
                let mobility = match piece {
                    Piece::Knight => popcount(chess::get_knight_moves(sq) & !*own),
                    Piece::Bishop => popcount(chess::get_bishop_moves(sq, blockers) & !*own),
                    Piece::Rook => popcount(chess::get_rook_moves(sq, blockers) & !*own),
                    Piece::Queen => {
                        let bm = chess::get_bishop_moves(sq, *board.combined());
                        let rm = chess::get_rook_moves(sq, *board.combined());
                        popcount((bm | rm) & !own)
                    }
                    _ => 0,
                };
                score += sign * mobility * weight;
            }
        }
    }
    score
}

fn evaluate_king_safety(board: &Board, phase: f32) -> i32 {
    if phase < 0.3 {
        return 0;
    }

    let mut score = 0i32;

    for &(color, sign) in &[(Color::White, 1i32), (Color::Black, -1i32)] {
        let own_mask = if color == Color::White {
            board.color_combined(Color::White)
        } else {
            board.color_combined(Color::Black)
        };
        let king_bb = *board.pieces(Piece::King) & *own_mask;
        let king_sq = if king_bb != EMPTY { king_bb.to_square() } else { continue };
        let rank = king_sq.get_rank().to_index();
        let file = king_sq.get_file().to_index();

        let pawns = *board.pieces(Piece::Pawn) & *own_mask;

        // Castled king bonus
        if color == Color::White
            && (king_sq == Square::G1 || king_sq == Square::C1)
        {
            score += sign * CASTLED_KING_BONUS;
        } else if color == Color::Black
            && (king_sq == Square::G8 || king_sq == Square::C8)
        {
            score += sign * CASTLED_KING_BONUS;
        }

        // Pawn shield
        let shield_rank = if color == Color::White {
            if rank < 7 { rank + 1 } else { rank }
        } else {
            if rank > 0 { rank - 1 } else { rank }
        };

        if shield_rank != rank {
            for delta in [-1i32, 0, 1] {
                let sf = file as i32 + delta;
                if sf < 0 || sf > 7 {
                    continue;
                }
                let shield_sq = ALL_SQUARES[shield_rank * 8 + sf as usize];
                if (pawns & BitBoard::from_square(shield_sq)) != EMPTY {
                    score += sign * KING_SHIELD_BONUS;
                } else {
                    score -= sign * KING_SHIELD_PENALTY;
                }
            }
        }
    }

    (score as f32 * phase) as i32
}

fn evaluate_bishop_pair(board: &Board) -> i32 {
    let mut score = 0;
    let bishops = board.pieces(Piece::Bishop);
    if popcount(bishops & board.color_combined(Color::White)) >= 2 {
        score += BISHOP_PAIR_BONUS;
    }
    if popcount(bishops & board.color_combined(Color::Black)) >= 2 {
        score -= BISHOP_PAIR_BONUS;
    }
    score
}

fn evaluate_rook_files(board: &Board) -> i32 {
    let mut score = 0i32;
    let pawns = board.pieces(Piece::Pawn);

    for &(color, sign) in &[(Color::White, 1i32), (Color::Black, -1i32)] {
        let own_mask = if color == Color::White {
            board.color_combined(Color::White)
        } else {
            board.color_combined(Color::Black)
        };
        let enemy_mask = if color == Color::White {
            board.color_combined(Color::Black)
        } else {
            board.color_combined(Color::White)
        };
        let own_pawns = pawns & own_mask;
        let enemy_pawns = pawns & enemy_mask;
        let rooks = board.pieces(Piece::Rook) & own_mask;

        for sq in iter_bits(rooks) {
            let file = sq.get_file();
            let file_mask = chess::get_file(file);
            let own_on_file = (own_pawns & file_mask) != EMPTY;
            let enemy_on_file = (enemy_pawns & file_mask) != EMPTY;
            if !own_on_file && !enemy_on_file {
                score += sign * ROOK_OPEN_FILE_BONUS;
            } else if !own_on_file {
                score += sign * ROOK_SEMI_OPEN_FILE_BONUS;
            }
        }
    }
    score
}

/// Full position evaluation. Returns score from side-to-move perspective.
fn evaluate(board: &Board) -> i32 {
    match board.status() {
        BoardStatus::Checkmate => return -MATE_SCORE,
        BoardStatus::Stalemate => return DRAW_SCORE,
        BoardStatus::Ongoing => {}
    }

    let phase = game_phase(board);
    let (w_mat, b_mat) = evaluate_material(board);
    let material = w_mat - b_mat;

    let score = material
        + evaluate_pst(board, phase)
        + evaluate_pawns(board)
        + evaluate_mobility(board)
        + evaluate_king_safety(board, phase)
        + evaluate_bishop_pair(board)
        + evaluate_rook_files(board)
        + TEMPO_BONUS;

    if board.side_to_move() == Color::White {
        score
    } else {
        -score
    }
}

// ============================================================
// MOVE ORDERING
// ============================================================

struct MoveOrderer {
    killer_moves: Vec<[Option<ChessMove>; 2]>,
    history: HashMap<(Color, u8, u8), i32>,
}

impl MoveOrderer {
    fn new() -> Self {
        Self {
            killer_moves: vec![[None; 2]; MAX_DEPTH],
            history: HashMap::new(),
        }
    }

    fn record_killer(&mut self, mv: ChessMove, ply: usize) {
        if ply >= self.killer_moves.len() {
            return;
        }
        let killers = &mut self.killer_moves[ply];
        if killers[0] != Some(mv) {
            killers[1] = killers[0];
            killers[0] = Some(mv);
        }
    }

    fn record_history(&mut self, color: Color, mv: ChessMove, depth: i32) {
        let key = (color, mv.get_source().to_index() as u8, mv.get_dest().to_index() as u8);
        let entry = self.history.entry(key).or_insert(0);
        *entry += depth * depth;
    }

    fn score_move(
        &self,
        board: &Board,
        mv: ChessMove,
        tt_move: Option<ChessMove>,
        ply: usize,
    ) -> i32 {
        // TT move first
        if tt_move == Some(mv) {
            return 10_000_000;
        }

        let mut score = 0;

        // Promotions
        if let Some(promo) = mv.get_promotion() {
            score += 800_000 + piece_value(promo);
        }

        // Captures: MVV-LVA
        if let Some(victim) = board.piece_on(mv.get_dest()) {
            let attacker = board.piece_on(mv.get_source()).unwrap_or(Piece::Pawn);
            score += 500_000 + 16 * piece_value(victim) - piece_value(attacker);
            return score;
        }

        // Killer moves
        if ply < self.killer_moves.len() {
            let killers = &self.killer_moves[ply];
            if killers[0] == Some(mv) {
                return score + 300_000;
            }
            if killers[1] == Some(mv) {
                return score + 290_000;
            }
        }

        // History heuristic
        let key = (
            board.side_to_move(),
            mv.get_source().to_index() as u8,
            mv.get_dest().to_index() as u8,
        );
        score += self.history.get(&key).copied().unwrap_or(0);

        score
    }

    fn order_moves(
        &self,
        board: &Board,
        moves: &mut Vec<ChessMove>,
        tt_move: Option<ChessMove>,
        ply: usize,
    ) {
        moves.sort_unstable_by(|a, b| {
            let sa = self.score_move(board, *a, tt_move, ply);
            let sb = self.score_move(board, *b, tt_move, ply);
            sb.cmp(&sa)
        });
    }
}

// ============================================================
// SEARCH
// ============================================================

struct Searcher {
    nodes: u64,
    tt: TranspositionTable,
    orderer: MoveOrderer,
    stop: bool,
    deadline: Option<Instant>,
}

impl Searcher {
    fn new(tt_size: usize) -> Self {
        Self {
            nodes: 0,
            tt: TranspositionTable::new(tt_size),
            orderer: MoveOrderer::new(),
            stop: false,
            deadline: None,
        }
    }

    fn check_time(&mut self) -> bool {
        if let Some(deadline) = self.deadline {
            if Instant::now() >= deadline {
                self.stop = true;
            }
        }
        self.stop
    }

    fn is_repetition(&self, board: &Board, path_hashes: &[u64]) -> bool {
        let hash = board.get_hash();
        path_hashes.iter().any(|&h| h == hash)
    }

    fn quiescence(&mut self, board: &Board, mut alpha: i32, beta: i32, ply: usize) -> i32 {
        self.nodes += 1;
        if self.nodes % 4096 == 0 && self.check_time() {
            return 0;
        }

        match board.status() {
            BoardStatus::Checkmate => return -MATE_SCORE + ply as i32,
            BoardStatus::Stalemate => return DRAW_SCORE,
            BoardStatus::Ongoing => {}
        }

        let in_check = *board.checkers() != EMPTY;

        if !in_check {
            let stand_pat = evaluate(board);
            if stand_pat >= beta {
                return stand_pat;
            }
            alpha = alpha.max(stand_pat);
        }

        // Generate moves: all if in check, captures only otherwise
        let mut moves: Vec<ChessMove> = if in_check {
            MoveGen::new_legal(board).collect()
        } else {
            let mut mg = MoveGen::new_legal(board);
            mg.set_iterator_mask(*board.color_combined(!board.side_to_move()));
            let mut captures: Vec<ChessMove> = mg.collect();
            // Also include promotions
            let mut promo_gen = MoveGen::new_legal(board);
            promo_gen.set_iterator_mask(!EMPTY); // all squares
            for mv in promo_gen {
                if mv.get_promotion().is_some()
                    && !captures.contains(&mv)
                {
                    captures.push(mv);
                }
            }
            captures
        };

        self.orderer.order_moves(board, &mut moves, None, ply);

        for mv in &moves {
            // Delta pruning (skip captures that can't raise alpha)
            if !in_check && mv.get_promotion().is_none() {
                if let Some(victim) = board.piece_on(mv.get_dest()) {
                    let delta = piece_value(victim) + 200;
                    if evaluate(board) + delta < alpha {
                        continue;
                    }
                }
            }

            let new_board = board.make_move_new(*mv);
            let score = -self.quiescence(&new_board, -beta, -alpha, ply + 1);

            if self.stop {
                return 0;
            }
            if score >= beta {
                return score;
            }
            alpha = alpha.max(score);
        }

        alpha
    }

    fn alpha_beta(
        &mut self,
        board: &Board,
        mut depth: i32,
        mut alpha: i32,
        mut beta: i32,
        ply: usize,
        path_hashes: &mut Vec<u64>,
    ) -> i32 {
        self.nodes += 1;
        if self.nodes % 4096 == 0 && self.check_time() {
            return 0;
        }

        // Terminal checks
        match board.status() {
            BoardStatus::Checkmate => return -MATE_SCORE + ply as i32,
            BoardStatus::Stalemate => return DRAW_SCORE,
            BoardStatus::Ongoing => {}
        }

        // Repetition detection
        if self.is_repetition(board, path_hashes) {
            return DRAW_SCORE;
        }

        // Check extension
        let in_check = *board.checkers() != EMPTY;
        if in_check {
            depth += 1;
        }

        if depth <= 0 {
            return self.quiescence(board, alpha, beta, ply);
        }

        // TT probe
        let tt_key = board.get_hash();
        let mut tt_move = None;
        if let Some(entry) = self.tt.probe(tt_key) {
            tt_move = entry.get_move();
            if entry.depth as i32 >= depth {
                match entry.flag {
                    TT_FLAG_EXACT => return entry.score,
                    TT_FLAG_LOWER => alpha = alpha.max(entry.score),
                    TT_FLAG_UPPER => beta = beta.min(entry.score),
                    _ => {}
                }
                if alpha >= beta {
                    return entry.score;
                }
            }
        }

        // Null move pruning
        let null_r = NULL_MOVE_R_BASE + depth / NULL_MOVE_R_DIVISOR;
        if depth >= 3 && !in_check && ply > 0 {
            if let Some(null_board) = board.null_move() {
                path_hashes.push(tt_key);
                let score = -self.alpha_beta(
                    &null_board,
                    depth - 1 - null_r,
                    -beta,
                    -beta + 1,
                    ply + 1,
                    path_hashes,
                );
                path_hashes.pop();
                if self.stop {
                    return 0;
                }
                if score >= beta {
                    return score;
                }
            }
        }

        let alpha_orig = alpha;
        let mut best_move: Option<ChessMove> = None;
        let mut best_score = -INFINITY;

        let mut moves: Vec<ChessMove> = MoveGen::new_legal(board).collect();
        self.orderer.order_moves(board, &mut moves, tt_move, ply);

        for (i, mv) in moves.iter().enumerate() {
            // Late move reductions
            let mut reduction = 0;
            if i >= LMR_FULL_DEPTH_MOVES
                && depth >= LMR_REDUCTION_LIMIT
                && !in_check
                && board.piece_on(mv.get_dest()).is_none() // not a capture
                && mv.get_promotion().is_none()
            {
                reduction = 1;
                if i >= 8 {
                    reduction = 2;
                }
                if i >= 16 {
                    reduction = 3;
                }
            }

            let new_board = board.make_move_new(*mv);
            path_hashes.push(tt_key);

            let score;
            if reduction > 0 {
                // Reduced search
                let reduced = -self.alpha_beta(
                    &new_board,
                    depth - 1 - reduction,
                    -alpha - 1,
                    -alpha,
                    ply + 1,
                    path_hashes,
                );
                if reduced > alpha && !self.stop {
                    // Re-search at full depth
                    score = -self.alpha_beta(
                        &new_board,
                        depth - 1,
                        -beta,
                        -alpha,
                        ply + 1,
                        path_hashes,
                    );
                } else {
                    score = reduced;
                }
            } else {
                score = -self.alpha_beta(
                    &new_board,
                    depth - 1,
                    -beta,
                    -alpha,
                    ply + 1,
                    path_hashes,
                );
            }

            path_hashes.pop();

            if self.stop {
                return 0;
            }

            if score > best_score {
                best_score = score;
                best_move = Some(*mv);
            }

            if score > alpha {
                alpha = score;
            }

            if alpha >= beta {
                // Beta cutoff — record killer + history for quiet moves
                if board.piece_on(mv.get_dest()).is_none() {
                    self.orderer.record_killer(*mv, ply);
                    self.orderer.record_history(board.side_to_move(), *mv, depth);
                }
                break;
            }
        }

        if best_move.is_none() {
            return if in_check {
                -MATE_SCORE + ply as i32
            } else {
                DRAW_SCORE
            };
        }

        // TT store
        let flag = if best_score <= alpha_orig {
            TT_FLAG_UPPER
        } else if best_score >= beta {
            TT_FLAG_LOWER
        } else {
            TT_FLAG_EXACT
        };
        self.tt.store(tt_key, best_score, depth, flag, best_move);

        best_score
    }

    fn extract_pv(&self, board: &Board, depth: i32) -> Vec<String> {
        let mut pv = Vec::new();
        let mut seen = std::collections::HashSet::new();
        let mut probe = *board;

        for _ in 0..depth {
            let key = probe.get_hash();
            if seen.contains(&key) {
                break;
            }
            seen.insert(key);

            if let Some(entry) = self.tt.probe(key) {
                if let Some(mv) = entry.get_move() {
                    // Verify the move is legal
                    let legal: Vec<ChessMove> = MoveGen::new_legal(&probe).collect();
                    if legal.contains(&mv) {
                        pv.push(format!("{}", mv));
                        probe = probe.make_move_new(mv);
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            } else {
                break;
            }
        }
        pv
    }

    fn search(
        &mut self,
        board: &Board,
        movetime_ms: u64,
        max_depth: u32,
    ) -> SearchResultRs {
        self.nodes = 0;
        self.stop = false;
        self.orderer = MoveOrderer::new(); // reset killers/history per search

        if movetime_ms > 0 {
            self.deadline = Some(Instant::now() + std::time::Duration::from_millis(movetime_ms));
        } else {
            self.deadline = None;
        }

        let target_depth = if max_depth > 0 {
            max_depth as i32
        } else {
            MAX_DEPTH as i32
        };

        let start = Instant::now();
        let mut best_move: Option<ChessMove> = None;
        let mut best_score = -INFINITY;
        let mut completed_depth = 0i32;
        let mut path_hashes = Vec::new();

        for current_depth in 1..=target_depth {
            if self.stop {
                break;
            }

            let score;
            // Aspiration window (after depth 4)
            if current_depth >= 4 && best_score != -INFINITY {
                let mut alpha = best_score - ASPIRATION_WINDOW;
                let mut beta = best_score + ASPIRATION_WINDOW;
                let s = self.alpha_beta(board, current_depth, alpha, beta, 0, &mut path_hashes);

                if !self.stop && (s <= alpha || s >= beta) {
                    // Failed — re-search with full window
                    alpha = -INFINITY;
                    beta = INFINITY;
                    score = self.alpha_beta(board, current_depth, alpha, beta, 0, &mut path_hashes);
                } else {
                    score = s;
                }
            } else {
                score = self.alpha_beta(
                    board,
                    current_depth,
                    -INFINITY,
                    INFINITY,
                    0,
                    &mut path_hashes,
                );
            }

            if self.stop {
                break;
            }

            // Extract best move from TT
            if let Some(entry) = self.tt.probe(board.get_hash()) {
                if let Some(mv) = entry.get_move() {
                    let legal: Vec<ChessMove> = MoveGen::new_legal(board).collect();
                    if legal.contains(&mv) {
                        best_move = Some(mv);
                        best_score = score;
                        completed_depth = current_depth;
                    }
                }
            }
        }

        // Fallback: pick first legal move
        if best_move.is_none() {
            best_move = MoveGen::new_legal(board).next();
        }

        let elapsed = start.elapsed().as_secs_f64() * 1000.0;
        let pv = if completed_depth > 0 {
            self.extract_pv(board, completed_depth)
        } else {
            Vec::new()
        };

        SearchResultRs {
            best_move: best_move.map(|m| format!("{}", m)).unwrap_or_default(),
            score: best_score,
            depth: completed_depth,
            nodes: self.nodes,
            pv,
            time_ms: elapsed,
        }
    }
}

struct SearchResultRs {
    best_move: String,
    score: i32,
    depth: i32,
    nodes: u64,
    pv: Vec<String>,
    time_ms: f64,
}

// ============================================================
// GLOBAL STATE (persistent TT across calls)
// ============================================================

static SEARCHER: LazyLock<Mutex<Searcher>> = LazyLock::new(|| Mutex::new(Searcher::new(TT_SIZE)));

// ============================================================
// PYTHON INTERFACE
// ============================================================

#[pyfunction]
fn search_position(py: Python, fen: &str, movetime_ms: u64, max_depth: u32) -> PyResult<PyObject> {
    let board = Board::from_str(fen).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("Invalid FEN: {}", e))
    })?;

    // Check opening book first
    let book_move = OPENING_BOOK.get(&board.get_hash());
    if let Some(&mv) = book_move {
        let legal: Vec<ChessMove> = MoveGen::new_legal(&board).collect();
        if legal.contains(&mv) {
            let dict = PyDict::new(py);
            dict.set_item("move", format!("{}", mv))?;
            dict.set_item("score", 0)?;
            dict.set_item("depth", 0)?;
            dict.set_item("nodes", 0u64)?;
            dict.set_item("pv", Vec::<String>::new())?;
            dict.set_item("time_ms", 0.0)?;
            return Ok(dict.into());
        }
    }

    let mut searcher = SEARCHER.lock().unwrap();
    let result = searcher.search(&board, movetime_ms, max_depth);

    let dict = PyDict::new(py);
    dict.set_item("move", &result.best_move)?;
    dict.set_item("score", result.score)?;
    dict.set_item("depth", result.depth)?;
    dict.set_item("nodes", result.nodes)?;
    dict.set_item("pv", &result.pv)?;
    dict.set_item("time_ms", result.time_ms)?;

    Ok(dict.into())
}

#[pyfunction]
fn engine_info(py: Python) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    dict.set_item("name", "chess_engine_rs")?;
    dict.set_item("version", "0.1.0")?;
    dict.set_item("backend", "rust")?;
    Ok(dict.into())
}

#[pymodule]
fn chess_engine_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(search_position, m)?)?;
    m.add_function(wrap_pyfunction!(engine_info, m)?)?;
    Ok(())
}
