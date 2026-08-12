import subprocess
import sys
import time
import pathlib

try:
    import chess
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-chess"], stdout=subprocess.DEVNULL)
    import chess

ENGINES = [pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()]
GAMES = int(sys.argv[3]) if len(sys.argv) > 3 else 8
MOVE_MS = int(sys.argv[4]) if len(sys.argv) > 4 else 100
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
        self.p = subprocess.Popen(
            [self.path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.send("uci")
        self.wait_for("uciok", 5.0)
        self.send("isready")
        self.wait_for("readyok", 5.0)

    def send(self, line: str):
        if self.p.poll() is not None:
            stderr = self.p.stderr.read()
            raise RuntimeError(f"engine exited before command: {self.path}; stderr={stderr!r}")
        assert self.p.stdin is not None
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def wait_for(self, token: str, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.p.stdout.readline()
            if line:
                if token in line:
                    return line.strip()
            elif self.p.poll() is not None:
                stderr = self.p.stderr.read()
                raise RuntimeError(f"engine exited waiting for {token}: {self.path}; stderr={stderr!r}")
            else:
                time.sleep(0.005)
        stderr = self.p.stderr.read()
        raise RuntimeError(f"timeout waiting for {token}: {self.path}; stderr={stderr!r}")

    def bestmove(self, board: chess.Board, limit_ms: int):
        move_list = " ".join(m.uci() for m in board.move_stack)
        if move_list:
            self.send("position startpos moves " + move_list)
        else:
            self.send("position startpos")
        self.send(f"go movetime {limit_ms}")
        deadline = time.monotonic() + max(5.0, limit_ms / 1000.0 + 2.0)
        while time.monotonic() < deadline:
            line = self.p.stdout.readline()
            if line:
                line = line.strip()
                if line.startswith("bestmove "):
                    parts = line.split()
                    return parts[1] if len(parts) > 1 else "0000"
            elif self.p.poll() is not None:
                stderr = self.p.stderr.read()
                raise RuntimeError(f"engine exited during search: {self.path}; stderr={stderr!r}")
            else:
                time.sleep(0.002)
        stderr = self.p.stderr.read()
        raise RuntimeError(f"timeout during search: {self.path}; stderr={stderr!r}")

    def close(self):
        if self.p.poll() is None:
            try:
                self.send("quit")
                self.p.wait(timeout=2)
            except Exception:
                self.p.kill()


def ep_result(result: str, ep_white: bool) -> str:
    if ep_white:
        return result
    if result == "1-0":
        return "0-1"
    if result == "0-1":
        return "1-0"
    return result

results = []
failures = []
with open("games.pgn", "w", encoding="utf-8") as pg:
    for gi in range(GAMES):
        board = chess.Board()
        for u in OPENINGS[gi % len(OPENINGS)]:
            board.push_uci(u)

        a = c = None
        try:
            a = UCI(ENGINES[0])
            c = UCI(ENGINES[1])
            order = [a, c] if gi % 2 == 0 else [c, a]
            ep_white = gi % 2 == 0
            ep_engine = a
            sf_engine = c
            if not ep_white:
                ep_engine, sf_engine = c, a

            reason = ""
            while not board.is_game_over(claim_draw=True) and board.ply() < MAX_PLIES:
                engine = ep_engine if board.turn == chess.WHITE else sf_engine
                # Swap engines when EternalPhoenix is Black.
                if not ep_white:
                    engine = sf_engine if board.turn == chess.WHITE else ep_engine
                move = engine.bestmove(board, MOVE_MS)
                if move in ("0000", "(none)"):
                    raise RuntimeError(f"{engine.path} returned {move}")
                try:
                    board.push_uci(move)
                except Exception as e:
                    raise RuntimeError(f"illegal move {move} from {engine.path}: {e}")

            if board.is_checkmate():
                result = "0-1" if board.turn == chess.WHITE else "1-0"
                reason = "checkmate"
            elif board.is_stalemate():
                result = "1/2-1/2"
                reason = "stalemate"
            elif board.is_insufficient_material() or board.is_seventyfive_moves() or board.is_fivefold_repetition():
                result = "1/2-1/2"
                reason = "draw-rule"
            else:
                result = "1/2-1/2"
                reason = "move-limit"

            sans = []
            bb = chess.Board()
            for u in [m.uci() for m in board.move_stack]:
                sans.append(bb.san(chess.Move.from_uci(u)))
                bb.push_uci(u)
            tokens = []
            for i in range(0, len(sans), 2):
                s = f"{i // 2 + 1}. {sans[i]}"
                if i + 1 < len(sans):
                    s += f" {sans[i + 1]}"
                tokens.append(s)

            white_name = "EternalPhoenix" if ep_white else "Stockfish"
            black_name = "Stockfish" if ep_white else "EternalPhoenix"
            pg.write(
                f'[Event "EternalPhoenix Benchmark"]\n'
                f'[Round "{gi + 1}"]\n'
                f'[White "{white_name}"]\n'
                f'[Black "{black_name}"]\n'
                f'[Result "{result}"]\n'
                f'[Termination "{reason}"]\n\n'
                + " ".join(tokens) + f" {result}\n\n"
            )
            pg.flush()
            results.append((ep_result(result, ep_white), board.ply(), reason))
            print(f"GAME {gi + 1}/{GAMES} RESULT={result} EP_RESULT={results[-1][0]} PLIES={board.ply()} REASON={reason}", flush=True)
        except Exception as e:
            failures.append(f"GAME {gi + 1}: {type(e).__name__}: {e}")
            print(f"FAIL GAME {gi + 1}: {type(e).__name__}: {e}", flush=True)
        finally:
            if a:
                a.close()
            if c:
                c.close()

if failures:
    print("\nMATCH FAILED")
    for f in failures:
        print(f)
    sys.exit(2)

wins = draws = losses = 0
for r, _, _ in results:
    if r == "1-0": wins += 1
    elif r == "1/2-1/2": draws += 1
    else: losses += 1

score = (wins + 0.5 * draws) / len(results) if results else 0.0
print(f"\nSUMMARY games={len(results)} wins={wins} draws={draws} losses={losses} score={score:.3f}")
if len(results) != GAMES:
    print("MATCH INCOMPLETE")
    sys.exit(3)
