"""
Developed by: Mykhailo [Misha] Brovin

EnergyPlus Parallel Simulation Runner
This script runs multiple EnergyPlus simulations in parallel, displaying their status
It supports real-time updates, error handling, and CSV output for results.

If the .idf file contains OutputControl:Files object, the script will use them to determine the output files to generate,
otherwise it will generate the default output files (.err, .htm).

Developed for EnergyPlus version 23.2.0, but should work with other versions as well.
# Requirements:
- Python 3.7+
- Rich library for UI: `pip install rich`
- psutil for process monitoring: `pip install psutil`
- Windows OS (EnergyPlus is primarily supported on Windows)

How to use:
1. GUI Mode: Run without arguments: `python energyplus_parallel.py`
2. Command Line Mode: `python energyplus_parallel.py --eplus_path "C:\EnergyPlusV23-2-0"`

Alternatively, you can run it with command line arguments to limit the number of parallel simulations:
python energyplus_parallel.py --eplus_path "C:\EnergyPlusV23-2-0" --max_workers 4
You can also specify a custom CSV output file:
python energyplus_parallel.py --eplus_path "C:\EnergyPlusV23-2-0" --csv_output "results.csv"
You can also specify the weather file to use:
python energyplus_parallel.py --eplus_path "C:\EnergyPlusV23-2-0" --weather_file "USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw"
"""

"""
    main
    entry point
"""

import os
import sys
import glob
import signal
import argparse

from eP_C import APP_NAME, VERSION, DEFAULT_EPLUS_PATH
from eP_D import check_and_install_dependencies
from eP_U import load_config_from_temp, signal_handler, cleanup_and_exit
from eP_S import run_simulations
from eP_G import show_gui


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    check_and_install_dependencies()
    
    parser = argparse.ArgumentParser(description='Run EnergyPlus simulations in parallel with Rich UI')
    parser.add_argument('--eplus', type=str, default=DEFAULT_EPLUS_PATH, help='Path to EnergyPlus installation directory')
    parser.add_argument('--max-workers', type=int, default=None, help='Maximum number of parallel simulations')
    parser.add_argument('--csv', type=str, default="simulation_results.csv", help='Output CSV file for simulation results')
    parser.add_argument('--weather', type=str, default=None, help='Weather file to use')
    parser.add_argument('--run-simulations', type=str, default=None, help='Run simulations with config file (internal use)')
    
    args = parser.parse_args()
    
    # Check if this is a simulation run (launched from GUI)
    if args.run_simulations:
        print(f"{APP_NAME}{VERSION} - Simulation Console")
        print("=" * 50)
        
        # Load configuration from file
        config = load_config_from_temp(args.run_simulations)
        if not config:
            print("Error: Could not load simulation configuration")
            input("Press Enter to exit...")
            return
        
        # Run simulations with loaded config
        run_simulations(
            idf_files=config['idf_files'],
            weather_file=config['epw_file'],
            eplus_path=config['eplus_path'],
            max_workers=config['max_workers'],
            csv_output=config['csv_output']
        )
        return
    
    # Check if any command line arguments were provided (excluding defaults)
    # If no arguments provided, launch GUI mode
    if len(sys.argv) == 1: # GUI mode
        print("No command line arguments provided. Starting GUI mode...")
        show_gui()
        
    else: # Command line mode
        current_dir = os.getcwd()
        
        # Find all IDF files in the current directory
        idf_files = glob.glob(os.path.join(current_dir, "*.idf"))
        if not idf_files:
            print(f"No IDF files found in the current directory")
            return
        
        # Find weather files
        if args.weather:
            weather_file = args.weather
        else:
            epw_files = glob.glob(os.path.join(current_dir, "*.epw"))
            if not epw_files:
                print(f"No EPW weather files found in the current directory")
                return
            weather_file = epw_files[0]
        
        run_simulations(
            idf_files=idf_files,
            weather_file=weather_file,
            eplus_path=args.eplus,
            max_workers=args.max_workers,
            csv_output=args.csv
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        cleanup_and_exit()
    except Exception as e:
        print(f"Unexpected error: {e}")
        cleanup_and_exit()