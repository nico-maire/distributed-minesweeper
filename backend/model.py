import random
from typing import List, Dict, Any, Optional

class Minesweeper:
    def __init__(self, rows: int, cols: int, num_mines: int, seed: Optional[int] = None):
        self.rows = rows
        self.cols = cols
        self.num_mines = num_mines
        self.seed = seed
        self.state = 'playing'
        self.mines = [[False for _ in range(cols)] for _ in range(rows)]
        self.revealed = [[False for _ in range(cols)] for _ in range(rows)]
        self.flags = [[False for _ in range(cols)] for _ in range(rows)]
        self.adjacent_mines = [[0 for _ in range(cols)] for _ in range(rows)]

        self.mines_placed = False

    def _place_mines(self, first_r: int, first_c: int):
        rng = random.Random(self.seed) if self.seed is not None else random
        positions = [(r, c) for r in range(self.rows) for c in range(self.cols) if (r, c) != (first_r, first_c)]
        mine_positions = rng.sample(positions, min(self.num_mines, len(positions)))
        for r, c in mine_positions:
            self.mines[r][c] = True

        self._calculate_all_adjacent()
        self.mines_placed = True

    def _calculate_all_adjacent(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if not self.mines[r][c]:
                    self.adjacent_mines[r][c] = self.count_adjacent_mines(r, c)

    def count_adjacent_mines(self, r: int, c: int) -> int:
        count = 0
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < self.rows and 0 <= nc < self.cols:
                    if self.mines[nr][nc]:
                        count += 1
        return count

    def reveal(self, r: int, c: int):
        if self.state != 'playing':
            return
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return
        if self.revealed[r][c] or self.flags[r][c]:
            return

        if not self.mines_placed:
            self._place_mines(r, c)

        self.revealed[r][c] = True

        if self.mines[r][c]:
            self.state = 'lost'
            return

        if self.adjacent_mines[r][c] == 0:
            for dr in [-1, 0, 1]:
                for dc in [-1, 0, 1]:
                    if dr != 0 or dc != 0:
                        self.reveal(r + dr, c + dc)
                        
        self._check_win()

    def toggle_flag(self, r: int, c: int):
        if self.state != 'playing':
            return
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return
        if not self.revealed[r][c]:
            self.flags[r][c] = not self.flags[r][c]

    def _check_win(self):
        for r in range(self.rows):
            for c in range(self.cols):
                if not self.mines[r][c] and not self.revealed[r][c]:
                    return
        self.state = 'won'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'rows': self.rows,
            'cols': self.cols,
            'num_mines': self.num_mines,
            'seed': self.seed,
            'state': self.state,
            'mines_placed': self.mines_placed,
            'mines': self.mines,
            'revealed': self.revealed,
            'flags': self.flags,
            'adjacent_mines': self.adjacent_mines,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Minesweeper':
        instance = cls(data['rows'], data['cols'], data['num_mines'], seed=data.get('seed'))
        instance.state = data['state']
        instance.mines_placed = data['mines_placed']
        instance.mines = data['mines']
        instance.revealed = data['revealed']
        instance.flags = data['flags']
        instance.adjacent_mines = data['adjacent_mines']
        return instance
