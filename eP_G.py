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

from eP_C import APP_NAME, VERSION, DEFAULT_EPLUS_PATH, UI_COLORS
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
        
        self.create_widgets()

    def on_window_resize(self, event):
        """Handle window resize events for responsive design"""
        if event.widget == self.root:
            # Update canvas scroll region when window is resized
            self.root.after_idle(lambda: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

    def setup_dark_theme(self):
        """Configure dark theme for the application"""
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
        self.style.configure('Dark.TButton', background=UI_COLORS['button_bg'], foreground=UI_COLORS['button_fg'])
        self.style.configure('Dark.TEntry', background=UI_COLORS['entry_bg'], foreground=UI_COLORS['entry_fg'])
        self.style.configure('Dark.TCheckbutton', background=UI_COLORS['bg'], foreground=UI_COLORS['fg'])
        self.style.configure('Dark.TSpinbox', background=UI_COLORS['entry_bg'], foreground=UI_COLORS['entry_fg'])
        
        # Configure LabelFrame
        self.style.configure('Dark.TLabelframe', background=UI_COLORS['bg'], foreground=UI_COLORS['fg'])
        self.style.configure('Dark.TLabelframe.Label', background=UI_COLORS['bg'], foreground=UI_COLORS['fg'])
        
        # Map active states
        self.style.map('Dark.TButton',
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
        """Create the GUI widgets with responsive dark theme"""
        main_frame = ttk.Frame(self.root, style='Dark.TFrame')
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)  # Content area gets most space
        
        banner_frame = ttk.Frame(main_frame, style='Banner.TFrame')
        banner_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 2))
        banner_frame.columnconfigure(0, weight=1)
        
        padding_y = "0.5m"
        padding_x = "0.1m"
        
        banner_content = ttk.Frame(banner_frame, style='Banner.TFrame')
        banner_content.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=padding_x, pady=padding_y)
        banner_content.columnconfigure(0, weight=1)
        
        title_label = ttk.Label(banner_content, text=APP_NAME, style='Banner.TLabel')
        title_label.grid(row=0, column=0, pady=(0, 0))

        subtitle_label1 = tk.Label(
            banner_content,
            text="Embarrassingly Parallel EnergyPlus Python Simulator",
            fg="#0051FF",
            bg=UI_COLORS['banner_bg'],
            font=('Calibri', 12)
        )
        subtitle_label1.grid(row=1, column=0, pady=(0, 0))

        github_url = "https://github.com/skibadubskiybadubs/energyplus_multiprocessing"
        def open_github_link(event):
            os.startfile(github_url)
        subtitle_label = tk.Label(
            banner_content,
            text="by Misha Brovin",
            fg="#ffffff",
            bg=UI_COLORS['banner_bg'],
            cursor="hand2",
            font=('Calibri', 8, 'italic')
        )
        subtitle_label.grid(row=2, column=0, pady=(0, 0))
        subtitle_label.bind("<Button-1>", open_github_link)

        
        version_label = ttk.Label(banner_content, text=f"Version {VERSION}", style='Version.TLabel', font=('Calibri', 8, 'italic'))
        version_label.grid(row=3, column=0)
        
        content_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        content_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=padding_y, pady="1m")
        content_frame.columnconfigure(1, weight=1)
        content_frame.rowconfigure(4, weight=1)  # Files frame gets most space

        row_pady = "0.8m"
        
        # IDF Folder Selection
        ttk.Label(content_frame, text="IDF Files Folder:", style='Dark.TLabel').grid(
            row=0, column=0, sticky=tk.W, pady=row_pady, padx=(0, "1m"))
        folder_entry = ttk.Entry(content_frame, textvariable=self.idf_folder, style='Dark.TEntry')
        folder_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=row_pady, padx=(0, "1m"))
        ttk.Button(content_frame, text="Browse", command=self.select_idf_folder, style='Dark.TButton').grid(
            row=0, column=2, pady=row_pady)
        
        # Weather File Selection
        ttk.Label(content_frame, text="Weather File (.epw):", style='Dark.TLabel').grid(
            row=1, column=0, sticky=tk.W, pady=row_pady, padx=(0, "1m"))
        weather_entry = ttk.Entry(content_frame, textvariable=self.epw_file, style='Dark.TEntry')
        weather_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=row_pady, padx=(0, "1m"))
        ttk.Button(content_frame, text="Browse", command=self.select_epw_file, style='Dark.TButton').grid(
            row=1, column=2, pady=row_pady)
        
        # EnergyPlus Folder Selection
        ttk.Label(content_frame, text="EnergyPlus Folder:", style='Dark.TLabel').grid(
            row=2, column=0, sticky=tk.W, pady=row_pady, padx=(0, "1m"))
        eplus_entry = ttk.Entry(content_frame, textvariable=self.eplus_folder, style='Dark.TEntry')
        eplus_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=row_pady, padx=(0, "1m"))
        ttk.Button(content_frame, text="Browse", command=self.select_eplus_folder, style='Dark.TButton').grid(
            row=2, column=2, pady=row_pady)
        
        # Settings frame
        settings_frame = ttk.LabelFrame(content_frame, text="Simulation Settings", style='Dark.TLabelframe')
        settings_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady="1m")
        settings_frame.columnconfigure(2, weight=1)
        
        # Compact settings layout
        ttk.Label(settings_frame, text="Max Workers:", style='Dark.TLabel').grid(
            row=0, column=0, sticky=tk.W, padx="1m", pady="0.5m")
        ttk.Spinbox(settings_frame, from_=1, to=cpu_count(), textvariable=self.max_workers, 
                    width=5, style='Dark.TSpinbox').grid(row=0, column=1, padx="0.5m", pady="0.5m")
        
        ttk.Label(settings_frame, text="CSV Output:", style='Dark.TLabel').grid(
            row=0, column=2, sticky=tk.W, padx="1m", pady="0.5m")
        csv_entry = ttk.Entry(settings_frame, textvariable=self.csv_output, style='Dark.TEntry')
        csv_entry.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=("0.5m", "1m"), pady="0.5m")
        
        # IDF Files Selection Frame 
        self.files_frame = ttk.LabelFrame(content_frame, text="Select IDF Files to Run", style='Dark.TLabelframe')
        self.files_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady="1m")
        self.files_frame.columnconfigure(0, weight=1)
        self.files_frame.rowconfigure(0, weight=1)
        
        # Scrollable frame setup
        self.canvas = tk.Canvas(self.files_frame, bg=UI_COLORS['bg'], highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.files_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas, style='Dark.TFrame')
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx="1m", pady="1m")
        self.scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S), padx=(0, "0.5m"), pady="1m")
        
        # BUTTONS
        button_frame = ttk.Frame(self.files_frame, style='Dark.TFrame')
        button_frame.grid(row=1, column=0, columnspan=2, pady="0.5m")
        ttk.Button(button_frame, text="Select All", command=self.select_all_files, style='Dark.TButton').pack(
            side=tk.LEFT, padx="0.5m")
        ttk.Button(button_frame, text="Select None", command=self.select_no_files, style='Dark.TButton').pack(
            side=tk.LEFT, padx="0.5m")
        

        action_frame = ttk.Frame(content_frame, style='Dark.TFrame')
        action_frame.grid(row=5, column=0, columnspan=3, pady="1m")
        
        start_btn = ttk.Button(action_frame, text="Start Simulations", command=self.start_simulations, style='Dark.TButton')
        start_btn.pack(side=tk.LEFT, padx="1m")
        
        cancel_btn = ttk.Button(action_frame, text="Cancel", command=self.cancel, style='Dark.TButton')
        cancel_btn.pack(side=tk.LEFT, padx="0.5m")
        
        # Default vals
        self.eplus_folder.set(DEFAULT_EPLUS_PATH)
        
        # Bind window resize event for dynamic updates
        self.root.bind('<Configure>', self.on_window_resize)
        
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
            
        # Create checkboxes for each IDF file with responsive spacing
        for i, idf_file in enumerate(self.idf_files):
            var = tk.BooleanVar(value=True)  # Default to selected
            filename = os.path.basename(idf_file)
            checkbox = ttk.Checkbutton(self.scrollable_frame, text=filename, variable=var, style='Dark.TCheckbutton')
            checkbox.pack(anchor=tk.W, pady="0.3m", padx="1m", fill=tk.X)
            self.idf_checkboxes[idf_file] = var
            
    def check_for_epw_file(self):
        """Check if EPW file exists in IDF folder and auto-select it"""
        folder = self.idf_folder.get()
        if not folder:
            return
            
        epw_files = glob.glob(os.path.join(folder, "*.epw"))
        if epw_files:
            self.epw_file.set(epw_files[0])  # Use first EPW file found
            
    def select_all_files(self):
        """Select all IDF files"""
        for var in self.idf_checkboxes.values():
            var.set(True)
            
    def select_no_files(self):
        """Deselect all IDF files"""
        for var in self.idf_checkboxes.values():
            var.set(False)
            
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
            
        # Create configuration dictionary
        config = {
            'idf_files': self.selected_files,
            'epw_file': self.epw_file.get(),
            'eplus_path': self.eplus_folder.get(),
            'max_workers': self.max_workers.get(),
            'csv_output': self.csv_output.get()
        }
        
        # Save config to temporary file
        config_file = save_config_to_temp(config)
        
        # Close GUI
        self.root.quit()
        self.root.destroy()
        
        # Launch new process with console for simulations
        try:
            # Get the path to the current script
            script_path = os.path.abspath(__file__)
            # Get the main.py path (assuming it's in the same directory)
            main_script_path = os.path.join(os.path.dirname(script_path), 'main.py')
            
            # Launch new process with console and config file
            subprocess.Popen([
                sys.executable, main_script_path, 
                '--run-simulations', config_file
            ], creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
            
        except Exception as e:
            print(f"Error launching simulation process: {e}")
        
        # Exit current process
        sys.exit(0)
        
    def cancel(self):
        """Cancel and close the GUI"""
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