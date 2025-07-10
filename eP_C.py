"""
    constants
"""

VERSION = "1.3.0"
APP_NAME = "ThreadEPy"
DEFAULT_EPLUS_PATH = r"C:\EnergyPlusV23-2-0"

# UI Colors for dark theme
UI_COLORS = {
    'bg': '#2b2b2b',           # Dark background
    'fg': '#ffffff',           # White text
    'select_bg': '#404040',    # Selection background
    'select_fg': '#ffffff',    # Selection text
    'entry_bg': '#f0f0f0',     # Entry background - LIGHTER GRAY
    'entry_fg': '#000000',     # Entry text - BLACK
    'button_bg': '#505050',    # Button background
    'button_fg': '#ffffff',    # Button text
    'button_active': '#606060', # Button active
    'accent': '#0d7377',       # Accent color (teal)
    'banner_bg': '#1a1a1a',    # Banner background
    'banner_fg': '#00d4aa'     # Banner text (bright teal)
}

# Output file mapping for EnergyPlus
OUTPUT_FILE_MAP = {
    'Output CSV': '.csv',
    'Output MTR': '.mtr',
    'Output ESO': '.eso',
    'Output EIO': '.eio',
    'Output Tabular': 'Table.html',
    'Output SQLite': '.sqlite',
    'Output JSON': '.json',
    'Output AUDIT': '.audit',
    'Output Zone Sizing': 'Zsz.csv',
    'Output System Sizing': 'Ssz.csv',
    'Output DXF': '.dxf',
    'Output BND': '.bnd',
    'Output RDD': '.rdd',
    'Output MDD': '.mdd',
    'Output MTD': '.mtd',
    'Output END': '.end',
    'Output SHD': '.shd',
    'Output DFS': '.dfs',
    'Output GLHE': '.glhe',
    'Output DelightIn': '.delightin',
    'Output DelightELdmp': '.delighteldmp',
    'Output DelightDFdmp': '.delightdfdmp',
    'Output EDD': '.edd',
    'Output DBG': '.dbg',
    'Output PerfLog': '.perflog',
    'Output SLN': '.sln',
    'Output SCI': '.sci',
    'Output WRL': '.wrl',
    'Output Screen': '.screen',
    'Output ExtShd': '.extshd',
    'Output Tarcog': '.tarcog'
}

# CSV Headers for simulation results
CSV_HEADERS = [
    "#", "Job_ID", "WeatherFile", "ModelFile", "Progress(1-Completed/0-Failed)",
    "Message", "Warnings", "Errors", "Hours", "Minutes", "Seconds"
]