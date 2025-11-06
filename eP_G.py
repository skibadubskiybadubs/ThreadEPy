"""
 gui
"""

import os
import sys
import glob
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from multiprocessing import cpu_count
import threading
import queue

from eP_C import APP_NAME, APP_NAME_ASCII, VERSION, DEFAULT_EPLUS_PATH, UI_COLORS
from eP_U import save_config_to_temp


class EnergyPlusGUI:
    """GUI for selecting simulation parameters"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{VERSION}")
        self.root.iconbitmap('eP_P.ico')
        self.root.geometry("600x600")

        # End Process on close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.setup_dark_theme()
        
        # Variables to store user selections
        self.idf_folder = tk.StringVar()
        self.epw_file = tk.StringVar()
        self.eplus_folder = tk.StringVar()
        self.max_workers = tk.IntVar(value=max(1, cpu_count() - 1))
        self.csv_output = tk.StringVar(value="simulation_results.csv")
        
        # Variables for IDF file selection
        self.idf_files = []
        self.idf_checkboxes = {}
        self.selected_files = []

        # Result variables
        self.result = None

        # Output display variables
        self.output_queue = queue.Queue()
        self.output_text = None
        self.output_frame = None
        self.simulation_running = False
        self.simulation_thread = None
        self.simulation_status = {}  # Track status of each simulation
        self.status_start_line = 4  # Line where simulation statuses start (after header)
        self.log_messages = []  # Store log messages separately
        self.total_simulations = 0  # Total number of simulations
        self.completed_simulations = 0  # Number of completed simulations

        self.create_widgets()

    def on_window_resize(self, event):
        if event.widget == self.root:
            # Update canvas scroll region when window is resized
            self.root.after_idle(lambda: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

    def setup_dark_theme(self):
        # Calculate responsive font sizes based on window size
        base_width = 900
        current_width = self.root.winfo_width() if self.root.winfo_width() > 1 else base_width
        scale_factor = current_width / base_width
        
        banner_font_size = max(24, int(32 * scale_factor)) 
        subtitle_font_size = max(10, int(12 * scale_factor))
        version_font_size = max(8, int(10 * scale_factor))
        
        # Configure root window
        self.root.configure(bg=UI_COLORS['bg'])
        
        # Configure ttk style
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Configure ttk styles for dark theme with responsive fonts
        self.style.configure('Dark.TFrame', background=UI_COLORS['bg'])
        self.style.configure('Dark.TLabel', background=UI_COLORS['bg'], foreground=UI_COLORS['fg'])
        self.style.configure('Dark.TButton',
                            background=UI_COLORS['button_bg'],
                            foreground=UI_COLORS['button_fg'],
                            borderwidth=1,
                            focuscolor=UI_COLORS['accent'],
                            padding=(8, 4),
                            relief='raised')
        self.style.configure('Dark.TEntry',
                            fieldbackground=UI_COLORS['entry_bg'],
                            background=UI_COLORS['entry_bg'],
                            foreground=UI_COLORS['entry_fg'],
                            insertcolor=UI_COLORS['entry_fg'],
                            bordercolor=UI_COLORS['select_bg'],
                            lightcolor=UI_COLORS['select_bg'],
                            darkcolor=UI_COLORS['select_bg'])
        self.style.configure('Dark.TCheckbutton', background=UI_COLORS['bg'], foreground=UI_COLORS['fg'])
        self.style.configure('Dark.TSpinbox',
                            fieldbackground=UI_COLORS['entry_bg'],
                            background=UI_COLORS['entry_bg'],
                            foreground=UI_COLORS['entry_fg'],
                            insertcolor=UI_COLORS['entry_fg'],
                            arrowcolor=UI_COLORS['entry_fg'],
                            bordercolor=UI_COLORS['select_bg'],
                            lightcolor=UI_COLORS['select_bg'],
                            darkcolor=UI_COLORS['select_bg'],
                            borderwidth=1,
                            relief='solid')

        # Configure LabelFrame with extremely thin border matching progress bar
        self.style.configure('Dark.TLabelframe',
                            background=UI_COLORS['bg'],
                            foreground=UI_COLORS['fg'],
                            bordercolor=UI_COLORS['select_bg'],
                            lightcolor=UI_COLORS['select_bg'],
                            darkcolor=UI_COLORS['select_bg'],
                            borderwidth=2,
                            relief='solid')
        self.style.configure('Dark.TLabelframe.Label', background=UI_COLORS['bg'], foreground=UI_COLORS['fg'], font=('Calibri', 10, 'bold'))

        # Map active states for buttons
        self.style.map('Dark.TButton',
                    background=[('active', UI_COLORS['button_active']),
                                ('pressed', UI_COLORS['accent'])],
                    foreground=[('active', '#ffffff')],
                    relief=[('pressed', 'sunken')])

        # Configure action button style (Start/Cancel buttons) - match progress bar height, no border
        self.style.configure('Action.TButton',
                            background=UI_COLORS['banner_bg'],
                            foreground='#bc6b6a',
                            borderwidth=0,
                            focuscolor='none',
                            padding=(3, 3),  # Reduced vertical padding to match progress bar height
                            relief='flat',
                            font=('Consolas', 8))
        self.style.map('Action.TButton',
                    background=[('active', '#252525'),
                                ('pressed', '#151515')],
                    foreground=[('active', '#bc6b6a')],
                    relief=[('pressed', 'flat')])

        # Configure browse button style - minimalistic with overall background and gray text
        self.style.configure('Browse.TButton',
                            background=UI_COLORS['bg'],
                            foreground='#9197AE',
                            borderwidth=0,
                            focuscolor='none',
                            padding=(1, 1),
                            relief='flat',
                            anchor='c',
                            width=9,  # Width in characters
                            font=('Consolas', 12))
        self.style.map('Browse.TButton',
                    background=[('active', UI_COLORS['select_bg']),
                                ('pressed', UI_COLORS['select_bg'])],
                    foreground=[('active', '#9197AE')],
                    relief=[('pressed', 'flat')])

        # Configure progress bar style - thin visible outline, green fill, chunked/segmented
        self.style.configure('Custom.Horizontal.TProgressbar',
                            background='#89a65e',  # Green progress color
                            troughcolor=UI_COLORS['bg'],  # Dark background
                            bordercolor=UI_COLORS['select_bg'],  # Visible thin border
                            lightcolor='#89a65e',  # Remove white highlight
                            darkcolor='#89a65e',  # Remove dark border
                            borderwidth=1,
                            thickness=25,
                            pbarrelief='flat')
        self.style.layout('Custom.Horizontal.TProgressbar',
                         [('Horizontal.Progressbar.trough',
                           {'children': [('Horizontal.Progressbar.pbar',
                                         {'side': 'left', 'sticky': 'ns'})],
                            'sticky': 'nswe'})])

        # Create chunked/segmented effect by setting element options
        self.style.element_create('Custom.Horizontal.trough', 'from', 'default')
        self.style.element_create('Custom.Horizontal.pbar', 'from', 'default')

        # Configure dark scrollbar style with thin visible outline
        self.style.configure('Dark.Vertical.TScrollbar',
                            background=UI_COLORS['select_bg'],  # Scrollbar handle
                            troughcolor=UI_COLORS['bg'],  # Scrollbar trough
                            bordercolor=UI_COLORS['select_bg'],  # Match other outlines
                            lightcolor=UI_COLORS['select_bg'],
                            darkcolor=UI_COLORS['select_bg'],
                            arrowcolor=UI_COLORS['fg'],
                            borderwidth=1,
                            relief='solid')
        self.style.map('Dark.Vertical.TScrollbar',
                      background=[('active', UI_COLORS['button_active']),
                                  ('pressed', UI_COLORS['accent'])])

        # Banner styles with responsive fonts
        self.style.configure('Banner.TFrame', background=UI_COLORS['banner_bg'])
        self.style.configure('Banner.TLabel', background=UI_COLORS['banner_bg'], foreground='yellow', 
                            font=('Calibri', banner_font_size, 'bold'))
        self.style.configure('Version.TLabel', background=UI_COLORS['banner_bg'], foreground=UI_COLORS['fg'], 
                            font=('Calibri', version_font_size))
        self.style.configure('Subtitle.TLabel', background=UI_COLORS['banner_bg'], foreground=UI_COLORS['fg'], 
                            font=('Calibri', subtitle_font_size, 'italic'))

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, style='Dark.TFrame')
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)  

        banner_frame = ttk.Frame(main_frame, style='Banner.TFrame')
        banner_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))
        banner_frame.columnconfigure(0, weight=1)

        banner_content = ttk.Frame(banner_frame, style='Banner.TFrame')
        banner_content.grid(row=0, column=0, sticky=(tk.W, tk.E))
        banner_content.columnconfigure(0, weight=1)

        # ASCII art title
        title_label = tk.Label(
            banner_content,
            text=APP_NAME_ASCII,
            fg='#6f9bd3',
            bg=UI_COLORS['banner_bg'],
            font=('Consolas', 6),
            justify=tk.LEFT
        )
        title_label.grid(row=0, column=0, pady=(5, 0))

        subtitle_label1 = tk.Label(
            banner_content,
            text="Multithreading EnergyPlus Simulator",
            fg='#bc6b6a',
            bg=UI_COLORS['banner_bg'],
            font=('Calibri', 12)
        )
        subtitle_label1.grid(row=1, column=0, pady=(2, 0))

        github_url = "https://github.com/skibadubskiybadubs/energyplus_multiprocessing"
        def open_github_link(event):
            os.startfile(github_url)

        # subtitle and version label
        subtitle_label = tk.Label(
            banner_content,
            text=f"by Misha Brovin  •  Version {VERSION}",
            fg="#9197AE",
            bg=UI_COLORS['banner_bg'],
            cursor="hand2",
            font=('Calibri', 8, 'italic')
        )
        subtitle_label.grid(row=2, column=0, pady=(0, 5))
        subtitle_label.bind("<Button-1>", open_github_link)




        self.content_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        self.content_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=15, pady=(0, 15))
        self.content_frame.columnconfigure(0, weight=0)
        self.content_frame.columnconfigure(1, weight=1)
        self.content_frame.columnconfigure(2, weight=0)
        self.content_frame.rowconfigure(4, weight=1) 

        row_pady = 3

        # IDF Folder Selection
        ttk.Label(self.content_frame, text="IDF Files Folder:", style='Dark.TLabel').grid(
            row=0, column=0, sticky=tk.W, pady=row_pady, padx=(0, 10))
        folder_entry = tk.Entry(self.content_frame, textvariable=self.idf_folder,
                                bg=UI_COLORS['entry_bg'], fg=UI_COLORS['entry_fg'],
                                insertbackground=UI_COLORS['entry_fg'],
                                highlightbackground=UI_COLORS['select_bg'],
                                highlightcolor=UI_COLORS['select_bg'],
                                highlightthickness=1,
                                borderwidth=0, relief='flat')
        folder_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=row_pady, padx=(5, 5))

        bt_enter = "⌞  🗁  ⌝"
        bt_exit = "⌞  🗀  ⌝"

        idf_browse_btn = ttk.Button(self.content_frame, text=bt_exit, command=self.select_idf_folder, style='Browse.TButton')
        idf_browse_btn.grid(row=0, column=2, pady=row_pady, sticky=tk.E)
        idf_browse_btn.bind('<Enter>', lambda _: idf_browse_btn.config(text=bt_enter))
        idf_browse_btn.bind('<Leave>', lambda _: idf_browse_btn.config(text=bt_exit))

        # Weather File Selection
        ttk.Label(self.content_frame, text="Weather File (.epw):", style='Dark.TLabel').grid(
            row=1, column=0, sticky=tk.W, pady=row_pady, padx=(0, 10))
        weather_entry = tk.Entry(self.content_frame, textvariable=self.epw_file,
                                 bg=UI_COLORS['entry_bg'], fg=UI_COLORS['entry_fg'],
                                 insertbackground=UI_COLORS['entry_fg'],
                                 highlightbackground=UI_COLORS['select_bg'],
                                 highlightcolor=UI_COLORS['select_bg'],
                                 highlightthickness=1,
                                 borderwidth=0, relief='flat')
        weather_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=row_pady, padx=(5, 5))

        epw_browse_btn = ttk.Button(self.content_frame, text=bt_exit, command=self.select_epw_file, style='Browse.TButton')
        epw_browse_btn.grid(row=1, column=2, pady=row_pady, sticky=tk.E)
        epw_browse_btn.bind('<Enter>', lambda _: epw_browse_btn.config(text=bt_enter))
        epw_browse_btn.bind('<Leave>', lambda _: epw_browse_btn.config(text=bt_exit))

        # EnergyPlus Folder Selection
        ttk.Label(self.content_frame, text="EnergyPlus Folder:", style='Dark.TLabel').grid(
            row=2, column=0, sticky=tk.W, pady=row_pady, padx=(0, 10))
        eplus_entry = tk.Entry(self.content_frame, textvariable=self.eplus_folder,
                               bg=UI_COLORS['entry_bg'], fg=UI_COLORS['entry_fg'],
                               insertbackground=UI_COLORS['entry_fg'],
                               highlightbackground=UI_COLORS['select_bg'],
                               highlightcolor=UI_COLORS['select_bg'],
                               highlightthickness=1,
                               borderwidth=0, relief='flat')
        eplus_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=row_pady, padx=(5, 5))

        eplus_browse_btn = ttk.Button(self.content_frame, text=bt_exit, command=self.select_eplus_folder, style='Browse.TButton')
        eplus_browse_btn.grid(row=2, column=2, pady=row_pady, sticky=tk.E)
        eplus_browse_btn.bind('<Enter>', lambda _: eplus_browse_btn.config(text=bt_enter))
        eplus_browse_btn.bind('<Leave>', lambda _: eplus_browse_btn.config(text=bt_exit))
        
        # Settings frame
        settings_frame = ttk.LabelFrame(self.content_frame, text="Simulation Settings", style='Dark.TLabelframe')
        settings_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=6)

        # Configure settings_frame grid to match content_frame proportions
        settings_frame.columnconfigure(0, weight=0)  # Labels
        settings_frame.columnconfigure(1, weight=0)  # Max workers spinbox
        settings_frame.columnconfigure(2, weight=0)  # CSV label
        settings_frame.columnconfigure(3, weight=1)  # CSV entry - expands
        settings_frame.columnconfigure(4, weight=0)  # Spacer to match Browse button column

        # Compact settings layout
        ttk.Label(settings_frame, text="Max Workers:", style='Dark.TLabel').grid(
            row=0, column=0, sticky=tk.W, padx=10, pady=6)
        ttk.Spinbox(settings_frame, from_=1, to=cpu_count(), textvariable=self.max_workers,
                    width=5, style='Dark.TSpinbox').grid(row=0, column=1, padx=5, pady=6, sticky=tk.W)

        ttk.Label(settings_frame, text="CSV Output:", style='Dark.TLabel').grid(
            row=0, column=2, sticky=tk.W, padx=(30, 10), pady=6)
        csv_entry = tk.Entry(settings_frame, textvariable=self.csv_output,
                             bg=UI_COLORS['entry_bg'], fg=UI_COLORS['entry_fg'],
                             insertbackground=UI_COLORS['entry_fg'],
                             highlightbackground=UI_COLORS['select_bg'],
                             highlightcolor=UI_COLORS['select_bg'],
                             highlightthickness=1,
                             borderwidth=0, relief='flat')
        csv_entry.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=(0, 0), pady=6)

        # Add a spacer frame in column 4 to reserve space matching the Browse button width
        # Create a dummy button to get exact width measurement (including padding)
        dummy_btn = ttk.Button(settings_frame, text=bt_exit, style='Browse.TButton')
        dummy_btn.grid(row=0, column=4, pady=row_pady, sticky=tk.E)
        self.root.update_idletasks()  # Force layout calculation
        button_width = dummy_btn.winfo_reqwidth()
        dummy_btn.grid_forget()  # Remove dummy button

        # Now create spacer with exact width matching the Browse button
        spacer = ttk.Frame(settings_frame, width=button_width, style='Dark.TFrame')
        spacer.grid(row=0, column=4, padx=1, sticky=(tk.N, tk.S, tk.E, tk.W))
        spacer.grid_propagate(False)
        
        # IDF Files Selection Frame
        self.files_frame = ttk.LabelFrame(self.content_frame, text="Select IDF Files to Run", style='Dark.TLabelframe')
        self.files_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=6)
        self.files_frame.columnconfigure(0, weight=1)
        self.files_frame.rowconfigure(0, weight=1)

        # Scrollable frame setup
        self.canvas = tk.Canvas(self.files_frame, bg=UI_COLORS['bg'], highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.files_frame, orient="vertical", command=self.canvas.yview, style='Dark.Vertical.TScrollbar')
        self.scrollable_frame = ttk.Frame(self.canvas, style='Dark.TFrame')

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=10, pady=10)
        self.scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S), padx=(0, 5), pady=10)

        # Default vals
        self.eplus_folder.set(DEFAULT_EPLUS_PATH)

        # Create output display (hidden initially)
        self.create_output_display(main_frame)

        # Action button and progress bar frame
        self.action_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        self.action_frame.grid(row=2, column=0, pady=(10, 15), padx=15, sticky=(tk.W, tk.E))
        self.action_frame.columnconfigure(1, weight=1)  # Progress bar column expands

        # Start/Cancel button on the left
        self.action_btn = ttk.Button(self.action_frame, text="⌞   ▶   ⌝", command=self.toggle_simulation, style='Action.TButton')
        self.action_btn.grid(row=0, column=0, padx=(0, 10), sticky=tk.W)

        # Chunked progress bar using Canvas (old Windows style)
        self.progress_bar = tk.Canvas(
            self.action_frame,
            height=25,
            bg=UI_COLORS['bg'],
            highlightbackground=UI_COLORS['select_bg'],
            highlightcolor=UI_COLORS['select_bg'],
            highlightthickness=1,
            borderwidth=0,
            relief='flat'
        )
        self.progress_bar.grid(row=0, column=1, sticky=(tk.W, tk.E))
        self.progress_value = 0
        self.progress_chunks = []  # Store chunk rectangles

        # Bind window resize event for dynamic updates
        self.root.bind('<Configure>', self.on_window_resize)

    def update_chunked_progress(self, percentage):
        """Update the chunked progress bar (old Windows style)"""
        # Clear existing chunks
        self.progress_bar.delete('all')

        # Get canvas dimensions
        width = self.progress_bar.winfo_width()
        height = self.progress_bar.winfo_height()

        if width <= 1:  # Canvas not yet rendered
            width = 300  # Default width

        # Chunk settings
        chunk_width = 20
        chunk_spacing = 2
        chunk_height = height - 4  # Leave 2px padding top and bottom

        # Calculate how many chunks to show based on percentage
        total_chunks = int(width / (chunk_width + chunk_spacing))
        filled_chunks = int((percentage / 100) * total_chunks)

        # Draw filled chunks
        x = 2  # Start with 2px padding
        for _ in range(filled_chunks):
            self.progress_bar.create_rectangle(
                x, 2,
                x + chunk_width, 2 + chunk_height,
                fill='#89a65e',  # Green color
                outline='',
                tags='chunk'
            )
            x += chunk_width + chunk_spacing

        self.progress_value = percentage

    def create_output_display(self, parent_frame):
        """Create output display area with Text widget for simulation output"""
        # Create output frame (will replace content area during simulation)
        self.output_frame = ttk.Frame(parent_frame, style='Dark.TFrame')
        self.output_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=15, pady=(0, 15))
        self.output_frame.columnconfigure(0, weight=1)
        self.output_frame.rowconfigure(0, weight=1)

        # Create Text widget for output with thin border matching other elements
        self.output_text = tk.Text(
            self.output_frame,
            bg='#1a1a1a',
            fg='#ffffff',
            font=('Consolas', 9),
            wrap=tk.WORD,
            height=30,
            state='disabled',  # Read-only
            highlightbackground=UI_COLORS['select_bg'],
            highlightcolor=UI_COLORS['select_bg'],
            highlightthickness=1,
            borderwidth=0,
            relief='flat'
        )

        # Create scrollbar with dark style
        output_scrollbar = ttk.Scrollbar(self.output_frame, command=self.output_text.yview, style='Dark.Vertical.TScrollbar')
        self.output_text.config(yscrollcommand=output_scrollbar.set)

        # Grid layout
        self.output_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        output_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # Configure tags for colored output
        # Colors: green=#89a65e, yellow=#ffd166, red=#bc6b6a, blue=#6f9bd3, grey=#9197AE
        self.output_text.tag_config('header', foreground='#6f9bd3', font=('Consolas', 10, 'bold'))
        self.output_text.tag_config('waiting', foreground='#ffd166')  # Yellow for awaiting
        self.output_text.tag_config('initializing', foreground='#ffd166')  # Yellow for initializing
        self.output_text.tag_config('running', foreground='#89a65e')  # Green for running
        self.output_text.tag_config('completed', foreground='#6f9bd3')  # Blue for completed
        self.output_text.tag_config('failed', foreground='#bc6b6a')  # Red for failed
        self.output_text.tag_config('warning', foreground='#ffd166')  # Yellow for warnings
        self.output_text.tag_config('error', foreground='#bc6b6a')  # Red for errors
        self.output_text.tag_config('info', foreground='#9197AE')  # Grey for info
        self.output_text.tag_config('progress', foreground='#6f9bd3')  # Blue for progress

        # Hide initially
        self.output_frame.grid_remove()

    def select_idf_folder(self):
        """Select folder containing IDF files"""
        folder = filedialog.askdirectory(title="Select folder containing IDF files")
        if folder:
            self.idf_folder.set(folder)
            self.load_idf_files()
            self.check_for_epw_file()
            
    def select_epw_file(self):
        """Select EPW weather file"""
        filename = filedialog.askopenfilename(
            title="Select weather file",
            filetypes=[("EPW files", "*.epw"), ("All files", "*.*")]
        )
        if filename:
            self.epw_file.set(filename)
            
    def select_eplus_folder(self):
        """Select EnergyPlus installation folder"""
        folder = filedialog.askdirectory(title="Select EnergyPlus installation folder")
        if folder:
            self.eplus_folder.set(folder)
            
    def load_idf_files(self):
        """Load IDF files from selected folder and create checkboxes"""
        folder = self.idf_folder.get()
        if not folder:
            return
            
        # Clear existing checkboxes
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.idf_checkboxes.clear()
        
        # Find IDF files
        self.idf_files = glob.glob(os.path.join(folder, "*.idf"))
        if not self.idf_files:
            no_files_label = ttk.Label(self.scrollable_frame, text="No IDF files found in selected folder", style='Dark.TLabel')
            no_files_label.pack(pady="1m")
            return
            
        # Create checkboxes for each IDF file with improved spacing
        for idf_file in self.idf_files:
            var = tk.BooleanVar(value=True)  # Default to selected
            filename = os.path.basename(idf_file)
            checkbox = ttk.Checkbutton(self.scrollable_frame, text=filename, variable=var, style='Dark.TCheckbutton')
            checkbox.pack(anchor=tk.W, pady=3, padx=10, fill=tk.X)
            self.idf_checkboxes[idf_file] = var
            
    def check_for_epw_file(self):
        """Check if EPW file exists in IDF folder and auto-select it"""
        folder = self.idf_folder.get()
        if not folder:
            return
            
        epw_files = glob.glob(os.path.join(folder, "*.epw"))
        if epw_files:
            self.epw_file.set(epw_files[0])  # Use first EPW file found

    def validate_inputs(self):
        """Validate user inputs"""
        if not self.idf_folder.get():
            messagebox.showerror("Error", "Please select a folder containing IDF files")
            return False
            
        if not self.epw_file.get():
            messagebox.showerror("Error", "Please select a weather file (.epw)")
            return False
            
        if not self.eplus_folder.get():
            messagebox.showerror("Error", "Please select EnergyPlus installation folder")
            return False
            
        if not os.path.exists(self.epw_file.get()):
            messagebox.showerror("Error", "Selected weather file does not exist")
            return False
            
        if not os.path.exists(self.eplus_folder.get()):
            messagebox.showerror("Error", "Selected EnergyPlus folder does not exist")
            return False
            
        # Check if EnergyPlus executable exists
        eplus_exe = os.path.join(self.eplus_folder.get(), 'energyplus.exe')
        if not os.path.exists(eplus_exe):
            messagebox.showerror("Error", f"EnergyPlus executable not found at {eplus_exe}")
            return False
            
        # Get selected IDF files
        self.selected_files = [idf for idf, var in self.idf_checkboxes.items() if var.get()]
        
        if not self.selected_files:
            messagebox.showerror("Error", "Please select at least one IDF file to run")
            return False
            
        return True
        
    def start_simulations(self):
        """Start the simulations with selected parameters"""
        if not self.validate_inputs():
            return

        if self.simulation_running:
            messagebox.showwarning("Simulation Running", "A simulation is already in progress.")
            return

        # Create configuration dictionary
        config = {
            'idf_files': self.selected_files,
            'epw_file': self.epw_file.get(),
            'eplus_path': self.eplus_folder.get(),
            'max_workers': self.max_workers.get(),
            'csv_output': self.csv_output.get()
        }

        # Hide input UI and show output display
        self.content_frame.grid_remove()
        self.output_frame.grid()

        # Mark simulation as running
        self.simulation_running = True
        self.simulation_status = {}
        self.log_messages = []  # Reset logs
        self.total_simulations = len(self.selected_files)
        self.completed_simulations = 0

        # Reset and show progress bar
        self.update_chunked_progress(0)

        # Update button to Cancel/Stop mode
        self.action_btn.config(text="⌞   ■   ⌝")  # Change to stop symbol

        # Start simulation in background thread
        self.simulation_thread = threading.Thread(target=self.run_simulations_thread, args=(config,), daemon=True)
        self.simulation_thread.start()

        # Start GUI update loop
        self.update_output_display()

    def update_output_display(self):
        """Update output display with messages from queue (thread-safe GUI updates)"""
        try:
            # Process all available messages from queue
            messages_processed = 0
            logs_buffer = []
            status_updated = False  # Track if any STATUS was updated

            while not self.output_queue.empty() and messages_processed < 100:
                try:
                    msg = self.output_queue.get_nowait()
                    msg_type = msg.get('type')

                    if msg_type == 'STATUS':
                        # Update simulation status in tracking dict
                        name = msg.get('name', 'Unknown')
                        status = msg.get('status', 'Unknown')
                        progress = msg.get('progress', 0)
                        cpu = msg.get('cpu', 0.0)
                        memory = msg.get('memory', 0.0)
                        warnings = msg.get('warnings', 0)
                        errors = msg.get('errors', 0)
                        runtime = msg.get('runtime', '0m 0s')

                        # Check if this is a NEW completion (transition from non-terminal to terminal state)
                        # Only count as complete when status changes TO Completed or Failed with progress=100
                        was_completed = False
                        if name in self.simulation_status:
                            old_status = self.simulation_status[name]['status']
                            old_progress = self.simulation_status[name]['progress']
                            # Consider completed if status was Completed/Failed AND progress was 100
                            was_completed = (old_status == 'Completed' or 'Failed' in old_status) and old_progress == 100

                        self.simulation_status[name] = {
                            'status': status,
                            'progress': progress,
                            'cpu': cpu,
                            'memory': memory,
                            'warnings': warnings,
                            'errors': errors,
                            'runtime': runtime
                        }

                        # Only increment if this is a NEW completion (status is terminal AND progress is 100)
                        is_now_completed = (status == 'Completed' or 'Failed' in status) and progress == 100
                        if is_now_completed and not was_completed:
                            self.completed_simulations += 1
                            # Update progress bar
                            if self.total_simulations > 0:
                                progress_pct = (self.completed_simulations / self.total_simulations) * 100
                                self.update_chunked_progress(progress_pct)

                        # Mark that status was updated
                        status_updated = True

                    elif msg_type == 'LOG':
                        # Buffer log messages
                        name = msg.get('name', '')
                        message = msg.get('message', '')
                        tag = msg.get('tag', 'info')
                        logs_buffer.append((name, message, tag))

                    elif msg_type == 'SUMMARY':
                        # Final summary (without extra separators)
                        summary = msg.get('summary', '')
                        logs_buffer.append(('', f"\n{summary}", 'header'))

                    elif msg_type == 'COMPLETE':
                        # Simulation complete
                        logs_buffer.append(('', f"\n{'='*100}\n  All Simulations Complete!\n{'='*100}\n", 'completed'))
                        self.simulation_running = False
                        # Change button back to Start mode
                        self.action_btn.config(text="⌞   ▶   ⌝")

                    messages_processed += 1

                except queue.Empty:
                    break

            # Store log messages first
            if logs_buffer:
                self.log_messages.extend(logs_buffer)
                # Keep only last 100 log messages to prevent memory issues
                if len(self.log_messages) > 100:
                    self.log_messages = self.log_messages[-100:]

            # Redraw if either status or logs were updated
            if (status_updated or logs_buffer) and self.simulation_status:
                self.redraw_all_simulations()

        except Exception as e:
            print(f"Error updating output display: {e}")

        # Schedule next update (4 FPS like Rich TUI)
        if self.simulation_running or not self.output_queue.empty():
            self.root.after(250, self.update_output_display)

    def redraw_all_simulations(self):
        """Redraw all simulation status lines AND logs (complete redraw)"""
        # Ensure text widget is editable
        self.output_text.config(state='normal')

        # Delete EVERYTHING to ensure clean redraw
        self.output_text.delete("1.0", tk.END)

        # Sort simulations by status (same order as TUI):
        # Failed first, Running/Initializing next, Waiting, then Completed last
        sorted_sims = sorted(
            self.simulation_status.items(),
            key=lambda x: (
                0 if 'Failed' in x[1]['status'] else
                1 if x[1]['status'] in ['Running', 'Initializing'] else
                2 if x[1]['status'] == 'Waiting' else
                3
            )
        )

        # Redraw each simulation
        for name, info in sorted_sims:
            # Get status symbol and tag
            status = info['status']
            if status == 'Completed':
                symbol = '✔'
                status_tag = 'completed'
            elif status == 'Running' or status == 'Initializing':
                symbol = '▶'
                status_tag = 'running'
            elif 'Failed' in status:
                symbol = '✖'
                status_tag = 'failed'
            else:
                symbol = '⏸'  # Waiting/paused
                status_tag = 'waiting'

            # Build progress bar (30 characters wide)
            progress = info['progress']
            bar_width = 30
            filled = int((progress / 100) * bar_width)
            empty = bar_width - filled
            progress_bar = f"[{'█' * filled}{'░' * empty}]"

            # Format memory
            memory = info['memory']
            if memory >= 1000:
                memory_str = f"{memory / 1024:.0f}gb"
            else:
                memory_str = f"{int(memory)}mb"

            # Build compact line
            # Format: name: symbol [progress_bar] percentage | CPU | Memory | Warnings | Errors | Runtime
            line = (f"{name[:50]}: {symbol} {progress_bar} {progress:>3}% | "
                    f"CPU {info['cpu']:>3.0f}% | Mem {memory_str:>6} | "
                    f"Warnings {info['warnings']} | Errors {info['errors']} | "
                    f"Runtime {info['runtime']}\n")

            # Append to end
            self.output_text.insert(tk.END, line, status_tag)

        # Add blank line after simulations
        self.output_text.insert(tk.END, "\n")

        # Re-add all stored log messages
        for name, message, tag in self.log_messages:
            if name:
                self.output_text.insert(tk.END, f"[{name}] ", 'info')
            self.output_text.insert(tk.END, f"{message}\n", tag)

        # Keep scroll at top to see failed/running simulations
        self.output_text.see("1.0")
        self.output_text.config(state='disabled')

    def run_simulations_thread(self, config):
        """Run simulations in background thread and send updates to queue"""
        try:
            # Import here to avoid circular imports
            from eP_S import run_simulations_for_gui

            # Send initial log
            self.output_queue.put({
                'type': 'LOG',
                'message': f"Starting {len(config['idf_files'])} simulations with {config['max_workers']} workers...",
                'tag': 'info'
            })

            # Run simulations with GUI queue
            run_simulations_for_gui(config, self.output_queue)

            # Send completion message
            self.output_queue.put({'type': 'COMPLETE'})

        except Exception as e:
            self.output_queue.put({
                'type': 'LOG',
                'message': f"Error running simulations: {str(e)}",
                'tag': 'error'
            })
            self.simulation_running = False

    def toggle_simulation(self):
        """Toggle between starting and stopping simulations"""
        if self.simulation_running:
            # Stop running simulations
            if messagebox.askyesno("Stop Simulations", "Are you sure you want to stop all running simulations?"):
                self.simulation_running = False
                self.output_queue.put({
                    'type': 'LOG',
                    'message': 'User requested simulation stop. Terminating processes...',
                    'tag': 'warning'
                })
                # Change button back to Start mode
                self.action_btn.config(text="⌞   ▶   ⌝")
                # Reset progress bar
                self.update_chunked_progress(0)
                # Show input UI again, hide output
                self.output_frame.grid_remove()
                self.content_frame.grid()
        else:
            # Start simulations
            self.start_simulations()

    def cancel(self):
        """Close the GUI (called on window close)"""
        self.result = None
        self.root.quit()
        self.root.destroy()
        sys.exit(0)
    
    def on_closing(self):
        """window closing event"""
        self.result = None
        self.root.quit()
        self.root.destroy()
        sys.exit(0)
        
    def show(self):
        """Show the GUI and return the result"""
        self.root.mainloop()
        return self.result


def show_gui():
    """Show the GUI and return user selections"""
    gui = EnergyPlusGUI()
    return gui.show()