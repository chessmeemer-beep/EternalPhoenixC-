import subprocess, sys, time, random, pathlib

try:
    import chess
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'python-chess'])
    import chess

ENGINES = [sys.argv[1], sys.argv[2]]
OPENINGS = [
    [],
    ['e2e4','e7e5','g1f3','b8c6'],
    ['d2d4','d7d5','c2c4','e7e6'],
    ['e2e4','c7c5','g1f3','d7d6'],
    ['c2c4','e7e5','b1c3','g8f6'],
    ['g1f3','d7d5','c2c4','e7e6'],
    ['e2e4','e7e6','d2d4','d7d5'],
    ['d2d4','g8f6','c2c4','g7g6'],
]
GAMES = 8
MOVE_MS = 75
MAX_PLIES = 180

class UCI:
    def __init__(self, path):
        self.p = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.send('uci'); self.wait('uciok')
        self.send('isready'); self.wait('readyok')
    def send(self, s):
        self.p.stdin.write(s+'\n'); self.p.stdin.flush()
    def wait(self, token):
        while True:
            line=self.p.stdout.readline()
            if not line: raise RuntimeError('engine exited')
            if token in line: return
    def bestmove(self, board):
        moves=' '.join(m.uci() for m in board.move_stack)
        if board.move_stack:
            self.send('position startpos moves '+moves)
        else:
            self.send('position startpos')
        self.send(f'go movetime {MOVE_MS}')
        while True:
            line=self.p.stdout.readline()
            if not line: raise RuntimeError('engine exited during search')
            if line.startswith('bestmove '):
                return line.split()[1]
    def close(self):
        try:
            self.send('quit')
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()

results=[]
with open('games.pgn','w',encoding='utf-8') as pg:
    for gi in range(GAMES):
        b=chess.Board()
        opening=OPENINGS[gi]
        for u in opening:
            b.push_uci(u)
        a=UCI(ENGINES[0]); c=UCI(ENGINES[1])
        order=[a,c] if gi%2==0 else [c,a]
        epWhite=(order[0] is a)
        reason=''
        try:
            while not b.is_game_over(claim_draw=True) and b.ply() < MAX_PLIES:
                eng=order[b.turn == chess.BLACK]
                mv=eng.bestmove(b)
                if mv in ('0000','(none)'):
                    reason='engine returned no move'; break
                try:
                    b.push_uci(mv)
                except Exception as e:
                    reason=f'illegal move {mv}: {e}'; break
            if reason:
                res='0-1' if b.turn else '1-0'
            elif b.is_checkmate():
                res='0-1' if b.turn == chess.WHITE else '1-0'
                reason='checkmate'
            elif b.is_stalemate():
                res='1/2-1/2'; reason='stalemate'
            elif b.is_insufficient_material() or b.is_seventyfive_moves() or b.is_fivefold_repetition():
                res='1/2-1/2'; reason='draw rule'
            else:
                res='1/2-1/2'; reason='move limit'
            white_name='EternalPhoenix' if epWhite else 'Stockfish'
            black_name='Stockfish' if epWhite else 'EternalPhoenix'
            game=f'''[Event "EternalPhoenix Benchmark"]\n[Round "{gi+1}"]\n[White "{white_name}"]\n[Black "{black_name}"]\n[Result "{res}"]\n[Termination "{reason}"]\n\n'''
            game += b.san(b.peek())+'\n' if False else ''
            # Rebuild SAN sequence from the stored UCI history.
            bb=chess.Board(); sans=[]
            for u in [m.uci() for m in b.move_stack]:
                sans.append(bb.san(chess.Move.from_uci(u))); bb.push_uci(u)
            tokens=[]
            for i in range(0,len(sans),2):
                x=f'{i//2+1}. {sans[i]}'
                if i+1<len(sans): x+=f' {sans[i+1]}'
                tokens.append(x)
            game += ' '.join(tokens)+' '+res+'\n\n'
            pg.write(game); pg.flush()
            results.append((res, epWhite, reason, b.ply()))
            print(f'game {gi+1}/{GAMES}: {res} EP_White={epWhite} plies={b.ply()} reason={reason}', flush=True)
        finally:
            a.close(); c.close()

score=0; ep_w=ep_l=ep_d=0
for r,epw,_,_ in results:
    ep_res=r if epw else ('1-0' if r=='0-1' else '0-1' if r=='1-0' else r)
    if ep_res=='1-0': score+=1; ep_w+=1
    elif ep_res=='1/2-1/2': score+=0.5; ep_d+=1
    else: ep_l+=1
print(f'\nSUMMARY games={GAMES} wins={ep_w} draws={ep_d} losses={ep_l} score={score/GAMES:.3f}')
