import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

# Handles the Minesweeper graphical interface and renders the game
class MinesweeperGUI(tk.Tk):
    COUNT_COLORS = ["", "#00e5ff", "#69ff47", "#ff6b6b", "#ffe66d", "#ff9f43", "#fd79a8", "#a29bfe", "#dfe6e9"]

    def __init__(self, controller):
        super().__init__()
        self.title("Distributed Minesweeper")
        self.geometry('950x650')
        self.minsize(800, 500)
        self.config(bg="#0a0a0a")
        self.controller = controller
        self.rows = 0
        self.cols = 0
        self.mines = 0
        self.flags = 0
        self.time = 0
        self.status = "playing"
        self.started = False
        self.timer_id = None
        self.cells = []
        
        self.create_login_frame()

    def create_login_frame(self):
        self.login_frame = tk.Frame(self, bg="#0a0a0a")
        self.login_frame.pack(expand=True)

        title = tk.Label(self.login_frame, text="◈ MINESWEEPER ◈", font=("Courier", 24, "bold"), fg="#00e5ff", bg="#0a0a0a")
        title.pack(pady=20)

        tk.Label(self.login_frame, text="Username:", font=("Courier", 14), fg="white", bg="#0a0a0a").pack(pady=5)
        self.username_entry = tk.Entry(self.login_frame, font=("Courier", 14))
        self.username_entry.pack(pady=5)

        tk.Label(self.login_frame, text="Room Name:", font=("Courier", 14), fg="white", bg="#0a0a0a").pack(pady=5)
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TCombobox', fieldbackground='#111111', background='#00e5ff', foreground='white', arrowcolor='black')

        self.room_var = tk.StringVar()
        self.room_entry = ttk.Combobox(self.login_frame, textvariable=self.room_var, font=("Courier", 14), width=22)
        self.room_entry.pack(pady=5)
        self.room_entry.set('Escribe o selecciona...')

        join_btn = tk.Button(self.login_frame, text="Join / Create", font=("Courier", 14, "bold"), 
                             bg="#00e5ff", fg="black", activebackground="#69ff47", 
                             command=self.submit_login)
        join_btn.pack(pady=20)

    def update_room_list(self, rooms):
        if hasattr(self, 'room_entry') and self.room_entry.winfo_exists():
            self.room_entry['values'] = rooms
            if rooms and (not self.room_entry.get() or self.room_entry.get() == 'Escribe o selecciona...'):
                self.room_entry.set(rooms[0])

    def submit_login(self):
        username = self.username_entry.get().strip()
        room = self.room_entry.get().strip()
        
        if not username or not room or room == 'Escribe o selecciona...':
            messagebox.showerror('Error', 'Debes introducir un usuario y una sala')
            return
        
        self.login_frame.pack_forget()
        self.controller.join_game(username, room)
        self.create_game_widgets()
        self.title(f"Distributed Minesweeper - Room: {room} - User: {username}")

    def create_game_widgets(self):
        self.game_frame = tk.Frame(self, bg="#0a0a0a")
        self.game_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)

        # División principal
        self.left_frame = tk.Frame(self.game_frame, bg="#0a0a0a")
        self.left_frame.pack(side=tk.LEFT, expand=True, padx=10, pady=10)

        self.right_frame = tk.Frame(self.game_frame, bg="#111", bd=2, relief="sunken")
        self.right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)

        # Panel izquierdo (juego original)
        self.title_label = tk.Label(self.left_frame, text=f"◈ MINESWEEPER - {self.controller.room_name} ◈", font=("Courier", 24, "bold"), fg="#00e5ff", bg="#0a0a0a")
        self.title_label.pack(pady=10)

        self.panel = tk.Frame(self.left_frame, bg="#111")
        self.panel.pack(pady=10)
        self.mine_label = tk.Label(self.panel, text="Mines: 0", font=("Courier", 16), fg="#ff6b6b", bg="#111")
        self.mine_label.pack(side=tk.LEFT, padx=20)
        self.face_button = tk.Button(self.panel, text="🤖", command=self.reset, font=("Courier", 20), bg="#1a1a1a", fg="white", relief="raised", bd=2)
        self.face_button.pack(side=tk.LEFT)
        self.time_label = tk.Label(self.panel, text="Time: 000", font=("Courier", 16), fg="#69ff47", bg="#111")
        self.time_label.pack(side=tk.LEFT, padx=20)

        self.grid_frame = tk.Frame(self.left_frame, bg="#0a0a0a")
        self.grid_frame.pack()

        self.status_label = tk.Label(self.left_frame, text="Click left to reveal, right to flag", font=("Courier", 10), fg="#00e5ff", bg="#0a0a0a")
        self.status_label.pack(pady=5)
        
        # Panel derecho (usuarios)
        tk.Label(self.right_frame, text="Jugadores en sala", font=("Courier", 12, "bold"), fg="#00e5ff", bg="#111").pack(pady=10)
        self.users_listbox = tk.Listbox(self.right_frame, font=("Courier", 12), bg="#0a0a0a", fg="white", selectbackground="#16213e")
        self.users_listbox.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)

    def update_user_list(self, users):
        if hasattr(self, 'users_listbox'):
            self.users_listbox.delete(0, tk.END)
            for user in users:
                self.users_listbox.insert(tk.END, user)

    def create_grid(self, rows, cols):
        self.rows = rows
        self.cols = cols
        self.cells = [[None for _ in range(cols)] for _ in range(rows)]
        for r in range(rows):
            for c in range(cols):
                btn = tk.Button(self.grid_frame, text="?", width=2, height=1, font=("Courier", 12), bg="#1a1a2e", fg="white",
                                relief="flat", bd=0, highlightthickness=0, highlightbackground="#1a1a2e", highlightcolor="#1a1a2e",
                                activebackground="#16213e", activeforeground="white",
                                command=lambda r=r, c=c: self.reveal(r, c))
                btn.bind("<Button-3>", lambda e, r=r, c=c: self.flag(r, c))
                btn.bind("<Enter>", lambda e: e.widget.config(bg="#16213e") if e.widget['text'] == '?' else None)
                btn.bind("<Leave>", lambda e: e.widget.config(bg="#1a1a2e") if e.widget['text'] == '?' else None)
                btn.grid(row=r, column=c, padx=0, pady=0)
                self.cells[r][c] = btn

    def update_board(self, state):
        self._load_state_metadata(state)
        self._ensure_grid_exists()
        self._render_cells()
        self._render_mine_counter()
        self._render_game_status()
        self._stop_timer_if_finished()

    def _load_state_metadata(self, state):
        self.rows = state['rows']
        self.cols = state['cols']
        self.status = state['state']
        self.mines = sum(sum(row) for row in state['mines'])
        self.flags = sum(sum(row) for row in state['flags'])
        self._revealed = state['revealed']
        self._flags = state['flags']
        self._mines = state['mines']
        self._adjacent_mines = state['adjacent_mines']

    def _ensure_grid_exists(self):
        if not self.cells or len(self.cells) != self.rows or any(len(row) != self.cols for row in self.cells):
            for widget in self.grid_frame.winfo_children():
                widget.destroy()
            self.create_grid(self.rows, self.cols)

    def _render_cells(self):
        for r in range(self.rows):
            for c in range(self.cols):
                cell = self.cells[r][c]
                if self._revealed[r][c]:
                    self._render_revealed_cell(r, c, cell)
                elif self._flags[r][c]:
                    self._render_flagged_cell(cell)
                else:
                    self._render_hidden_cell(cell)

    def _render_revealed_cell(self, r, c, cell):
        cell.config(relief="flat", bd=0, highlightthickness=0, highlightbackground=cell['bg'], highlightcolor=cell['bg'])
        if self._mines[r][c]:
            cell.config(text="💣", bg="#ff6b6b", fg="white")
        else:
            adj = self._adjacent_mines[r][c]
            if adj > 0:
                cell.config(text=str(adj), fg=self.COUNT_COLORS[adj], bg="#1b1b1b")
            else:
                shade = "#232323" if (r + c) % 2 == 0 else "#181818"
                cell.config(text="", bg=shade)
        cell.unbind("<Enter>")
        cell.unbind("<Leave>")

    def _render_flagged_cell(self, cell):
        cell.config(text="🚩", bg="#ff9f43", fg="black")
        cell.unbind("<Enter>")
        cell.unbind("<Leave>")

    def _render_hidden_cell(self, cell):
        cell.config(text="?", bg="#1a1a2e", fg="white")
        cell.bind("<Enter>", lambda e: e.widget.config(bg="#16213e") if e.widget['text'] == '?' else None)
        cell.bind("<Leave>", lambda e: e.widget.config(bg="#1a1a2e") if e.widget['text'] == '?' else None)

    def _render_mine_counter(self):
        self.mine_label.config(text=f"Mines: {self.mines - self.flags}")

    def _render_game_status(self):
        if self.status == "won":
            self.face_button.config(text="😎", bg="#69ff47")
            self.status_label.config(text="CAMPO DESPEJADO — MISIÓN CUMPLIDA", fg="#69ff47")
        elif self.status == "lost":
            self.face_button.config(text="💀", bg="#ff6b6b")
            self.status_label.config(text="DETONACIÓN — GAME OVER", fg="#ff6b6b")
        else:
            self.face_button.config(text="🤖", bg="#1a1a1a")
            self.status_label.config(text="Click left to reveal, right to flag", fg="#00e5ff")

    def _stop_timer_if_finished(self):
        if self.status != "playing" and self.timer_id:
            self.after_cancel(self.timer_id)
            self.timer_id = None

    def reveal(self, r, c):
        self.controller.reveal_cell(r, c)

    def flag(self, r, c):
        self.controller.flag_cell(r, c)

    def reset(self):
        self.controller.restart_game()

    def reset_timer(self):
        self.time = 0
        self.started = False
        if self.timer_id:
            self.after_cancel(self.timer_id)
        self.timer_id = None
        self.time_label.config(text="Time: 000")

    def start_timer(self):
        self.update_timer()

    def update_timer(self):
        if self.status == "playing":
            self.time += 1
            self.time_label.config(text=f"Time: {self.time:03d}")
            self.timer_id = self.after(1000, self.update_timer)

    def show_error(self, message):
        messagebox.showerror("Error", message)
