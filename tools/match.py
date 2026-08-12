import subprocess
import sys
import time
import pathlib
import chess

ENGINES = [pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()]
GAMES = int(sys.argv[3]) if len(sys.argv) > 3 else 8
MOVE_MS = int(sys.argv[4]) if len(sys.argv) > 4 else 300
MAX_PLIES = 180

OPENINGS = [
    [],
    ["e2e4", "e7e5", "g1f3", "b8c6"],
    ["d2d4", "d7d5", "c2c4", "e7e6"],
    ["e2e4", "c7c5", "g1f3", "d7d6"],
    ["c2c4", "e7e5", "b1c3", "g8f6"],
    ["g1f3", "d7d5", "c2c4", "e7e6"],
    ["e2e4", "e7e6", "d2d4", "d7d5"],
    ["d2d4", "g8f6", "c2c4", "g7g6"],
]

class UCI:
    def __init__(self, path: pathlib.Path):
        self.path = str(path)
        self.p = subprocess.Popen([self.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1)
        self.send("uci"); self.wait_for("uciok", 5.0)
        self.send("isready"); self.wait_for("readyok", 5.0)

    def send(self, line: str):
        if self.p.poll() is not None:
            raise RuntimeError(f"engine exited: {self.path}; stderr={self.p.stderr.read()!r}")
        self.p.stdin.write(line + "\n"); self.p.stdin.flush()

    def wait_for(self, token: str, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.p.stdout.readline()
            if line:
                if token in line: return line.strip()
            elif self.p.poll() is not None:
                raise RuntimeError(f"engine exited waiting for {token}: {self.path}; stderr={self.p.stderr.read()!r}")
            else:
                time.sleep(0.002)
        raise RuntimeError(f"timeout waiting for {token}: {self.path}; stderr={self.p.stderr.read()!r}")

    def bestmove(self, board: chess.Board, limit_ms: int):
        self.send("position fen " + board.fen())
        self.send(f"go movetime {limit_ms}")
        deadline = time.monotonic() + max(5.0, limit_ms / 1000.0 + 3.0)
        while time.monotonic() < deadline:
            line = self.p.stdout.readline()
            if line:
                line = line.strip()
                if line.startswith("bestmove "):
                    parts = line.split(); return parts[1] if len(parts) > 1 else "0000"
            elif self.p.poll() is not None:
                raise RuntimeError(f"engine exited during search: {self.path}; stderr={self.p.stderr.read()!r}")
            else:
                time.sleep(0.001)
        raise RuntimeError(f"timeout during search: {self.path}; stderr={self.p.stderr.read()!r}")

    def close(self):
        if self.p.poll() is None:
            try:
                self.send("quit"); self.p.wait(timeout=2)
            except Exception: self.p.kill()

def ep_result(result: str, ep_white: bool) -> str:
    return result if ep_white else ("1-0" if result == "0-1" else "0-1" if result == "1-0" else result)

results, failures = [], []
with open("games.pgn", "w", encoding="utf-8") as pg:
    for gi in range(GAMES):
        board = chess.Board()
        for u in OPENINGS[gi % len(OPENINGS)]: board.push_uci(u)
        a = c = None
        try:
            a, c = UCI(ENGINES[0]), UCI(ENGINES[1])
            ep_white = gi % 2 == 0
            ep_engine, sf_engine = (a, c) if ep_white else (c, a)
            while not board.is_game_over(claim_draw=True) and board.ply() < MAX_PLIES:
                engine = ep_engine if board.turn == chess.WHITE else sf_engine
                if not ep_white: engine = sf_engine if board.turn == chess.WHITE else ep_engine
                move = engine.bestmove(board, MOVE_MS)
                try:
                    if move in ("0000", "(none)"):
                        raise ValueError(f"null/empty move {move}")
                    board.push_uci(move)
                except Exception as first:
                    print(f"RETRY game={gi+1} engine={engine.path} move={move} reason={first}", flush=True)
                    move = engine.bestmove(board, 1000)
                    if move in ("0000", "(none)"):
                        raise RuntimeError(f"retry returned {move}")
                    try: board.push_uci(move)
                    except Exception as second: raise RuntimeError(f"illegal move {move} after retry: {second}") from second

            if board.is_checkmate(): result, reason = (("0-1", "checkmate") if board.turn == chess.WHITE else ("1-0", "checkmate"))
            elif board.is_stalemate() or board.is_insufficient_material() or board.is_seventyfive_moves() or board.is_fivefold_repetition(): result, reason = "1/2-1/2", "draw-rule"
            else: result, reason = "1/2-1/2", "move-limit"

            white_name = "EternalPhoenix" if ep_white else "Stockfish"; black_name = "Stockfish" if ep_white else "EternalPhoenix"
            pg.write(f'[Event "EternalPhoenix Benchmark"]\n[Round "{gi+1}"]\n[White "{white_name}"]\n[Black "{black_name}"]\n[Result "{result}"]\n[Termination "{reason}"]\n\n')
            tmp = chess.Board(); sans=[]
            for m in board.move_stack: sans.append(tmp.san(m)); tmp.push(m)
            for i in range(0,len(sans),2):
                pg.write(f"{i//2+1}. {sans[i]}")
                if i+1<len(sans): pg.write(f" {sans[i+1]}")
                pg.write(" ")
            pg.write(result+"\n\n"); pg.flush()
            ep_res=ep_result(result,ep_white); results.append((ep_res,board.ply(),reason))
            print(f"GAME {gi+1}/{GAMES} RESULT={result} EP_RESULT={ep_res} PLIES={board.ply()} REASON={reason}",flush=True)
        except Exception as exc:
            failures.append(f"GAME {gi+1}: {type(exc).__name__}: {exc}"); print(f"FAIL GAME {gi+1}: {type(exc).__name__}: {exc}",flush=True)
        finally:
            if a: a.close()
            if c: c.close()

if failures:
    print("\nMATCH FAILED")
    for f in failures: print(f)
    sys.exit(2)
wins=sum(r=="1-0" for r,_,_ in results); draws=sum(r=="1/2-1/2" for r,_,_ in results); losses=sum(r=="0-1" for r,_,_ in results)
score=(wins+0.5*draws)/len(results) if results else 0.0
print(f"\nSUMMARY games={len(results)} wins={wins} draws={draws} losses={losses} score={score:.3f}")
if len(results)!=GAMES: print("MATCH INCOMPLETE"); sys.exit(3)
