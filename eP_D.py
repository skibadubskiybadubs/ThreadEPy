"""
 dependencies
 dependency management and Rich/psutil imports
"""

import os
import sys
import subprocess


def check_and_install_dependencies():
    """Check if dependencies are installed, if not, attempt to install them"""
    try:
        import rich
        import psutil
    except ImportError:
        print("Installing required dependencies (rich, psutil)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "rich", "psutil"])
        print("Dependencies installed successfully.")


def import_dependencies():
    """Import all required dependencies after ensuring they're installed"""
    check_and_install_dependencies()

    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich import box
    from rich.columns import Columns
    from rich.text import Text

    import psutil
    
    return {
        'Live': Live,
        'Table': Table,
        'Panel': Panel,
        'Layout': Layout,
        'box': box,
        'Columns': Columns,
        'Text': Text,
        'psutil': psutil
    }


def check_python_version():
    if sys.version_info < (3, 6):
        print("Error: Python 3.6 or higher is required")
        return False
    print(f"✓ Python version: {sys.version.split()[0]}")
    return True

def install_dependencies():
    """Install required dependencies"""
    dependencies = ['rich', 'psutil']
    
    print("Installing dependencies...")
    for dep in dependencies:
        try:
            __import__(dep)
            print(f"✓ {dep} is already installed")
        except ImportError:
            print(f"Installing {dep}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", dep])
            print(f"✓ {dep} installed successfully")

def verify_files():
    required_files = [
        'eP_P.py',
        'eP_C.py', 
        'eP_D.py',
        'eP_U.py',
        'eP_T.py',
        'eP_S.py',
        'eP_G.py'
    ]
    
    missing_files = []
    for file in required_files:
        if os.path.exists(file):
            print(f"✓ {file}")
        else:
            print(f"✗ {file} (missing)")
            missing_files.append(file)
    
    if missing_files:
        print(f"\nError: Missing files: {', '.join(missing_files)}")
        return False
    
    print("\n✓ All required files are present")
    return True

def main():
    print("ThreadEPy - Setup")
    print("=" * 40)
    
    # Check Python version
    if not check_python_version():
        return False
    
    # Check files
    if not verify_files():
        return False
    
    # Install dependencies
    try:
        install_dependencies()
    except Exception as e:
        print(f"Error installing dependencies: {e}")
        return False
    
    print("\n" + "=" * 40)
    print("✓ Setup completed successfully!")
    print("\nYou can now run the application with:")
    print("  python eP_P.py")
    print("  or")
    print("  run.bat")
    
    return True

if __name__ == "__eP_P__":
    success = main()
    if not success:
        input("\nPress Enter to exit...")
        sys.exit(1)
    else:
        input("\nPress Enter to exit...")