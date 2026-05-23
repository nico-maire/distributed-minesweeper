import unittest

from backend.model import Minesweeper


class TestMinesweeperModel(unittest.TestCase):

    def test_initial_state_is_playing(self):
        game = Minesweeper(rows=8, cols=8, num_mines=10, seed=7)
        self.assertEqual(game.state, 'playing')

    def test_first_click_is_never_a_mine(self):
        game = Minesweeper(rows=8, cols=8, num_mines=10, seed=7)

        first_r, first_c = 3, 4
        game.reveal(first_r, first_c)

        self.assertTrue(game.mines_placed)
        self.assertTrue(game.revealed[first_r][first_c])
        self.assertFalse(game.mines[first_r][first_c])

    def test_revealing_forced_mine_sets_lost_state(self):
        game = Minesweeper(rows=3, cols=3, num_mines=1, seed=1)

        game.mines_placed = True
        game.mines = [[False for _ in range(game.cols)] for _ in range(game.rows)]
        game.mines[1][1] = True

        game.reveal(1, 1)

        self.assertTrue(game.revealed[1][1])
        self.assertEqual(game.state, 'lost')

    def test_toggle_flag_does_not_reveal_cell(self):
        game = Minesweeper(rows=5, cols=5, num_mines=5, seed=2)

        game.toggle_flag(2, 2)

        self.assertTrue(game.flags[2][2])
        self.assertFalse(game.revealed[2][2])


if __name__ == '__main__':
    unittest.main(verbosity=2)
