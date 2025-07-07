# EnergyPlus Parallel Simulator

A Python utility for running multiple EnergyPlus simulations in parallel with real-time monitoring.

## Overview

This tool automates the process of running multiple EnergyPlus simulations concurrently, efficiently utilizing available CPU cores. It provides a rich terminal UI to monitor progress, resource usage, and simulation status in real-time.

![GUI](https://raw.githubusercontent.com/skibadubskiybadubs/energyplus_multiprocessing/main/img2.png)

![EnergyPlus Parallel Simulations](https://raw.githubusercontent.com/skibadubskiybadubs/energyplus_multiprocessing/main/img.png)

## Features

- **Parallel Processing**: Automatically detects available CPU cores and runs multiple simulations concurrently
- **Real-time Monitoring**: Live UI showing simulation progress, CPU and memory usage
- **Automatic Staging**: Queues simulations and starts new ones as others complete
- **Error Handling**: Detects and reports simulation failures in real-time
- **CSV Reporting**: Generates a detailed CSV report of all simulation runs
- **Resource Management**: Monitors and displays CPU and memory usage for each simulation

## Installation

### Prerequisites

- Python 3.8 or higher
- EnergyPlus 23.2.0 or higher (must be installed separately)

### Setup

1. Clone this repository:
   ```bash
   git clone https://github.com/skibadubskiybadubs/energyplus_multiprocessing.git
   cd energyplus-parallel
   ```

2. Install the required dependencies:
   ```bash
   pip install rich psutil
   ```

## Usage

1. Place your IDF files and weather file (EPW) in the same directory as the script.

2. Run the script:

   There are several ways to run the script. You can enable the built-in GUI by simply calling the script without any additional arguments:
   ```bash
   python energyplus_parallel.py
   ```

   Otherwise, you can skip the built-in GUI to immediately run the script. In this case, all the .idf and .epw files must be located in the root folder along with the script:
   ```bash
   python energyplus_parallel.py --eplus "C:\EnergyPlusV23-2-0"
   ```

### Command-line Arguments

- `--eplus`: Path to the EnergyPlus installation directory (required)
- `--max-workers`: Maximum number of parallel simulations (default: number of logical processors - 1)
- `--csv`: Output CSV file name (default: "simulation_results.csv")

### Example

```bash
python energyplus_parallel.py --eplus "C:\EnergyPlusV23-2-0" --max-workers 6 --csv "results.csv"
```

## How It Works

1. The script automatically finds all IDF files in the current directory.
2. It determines the optimal number of parallel simulations based on your computer's specifications.
3. It creates temporary directories for each simulation to prevent conflicts.
4. Simulations run in parallel, with new ones starting as others complete.
5. The script provides live monitoring of all running simulations.
6. Upon completion, a summary CSV file is generated with detailed results.

## CSV Output Format

The script generates a CSV file with the following columns:

| Column | Description |
|--------|-------------|
| # | Row ID |
| Job_ID | Simulation name (IDF filename without extension) |
| WeatherFile | Weather file used |
| ModelFile | IDF filename |
| Progress | 1 (Completed) or 0 (Failed) |
| Message | Success or failure message |
| Warnings | Number of warnings |
| Errors | Number of errors |
| Hours | Runtime hours |
| Minutes | Runtime minutes |
| Seconds | Runtime seconds |

## Troubleshooting

### Common Issues

1. **Error: EnergyPlus executable not found**
   - Ensure the path to EnergyPlus is correct
   - Verify EnergyPlus is properly installed

2. **Simulations start but fail immediately**
   - Check that your IDF files are valid
   - Verify that the weather file is in the same directory

3. **Script crashes with memory errors**
   - Reduce the number of parallel simulations using the `--max-workers` option

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- The Rich library for the terminal UI
- EnergyPlus for building energy modeling

## References
- https://unmethours.com/question/38548/simultaneously-run-a-number-of-independent-energyplus-simulations-on-multiple-cores-on-linux-via-a-script/
- https://bigladdersoftware.com/epx/docs/8-4/tips-and-tricks-using-energyplus/run-energyplus-in-parallel.html
- https://unmethours.com/question/4668/script-for-multiple-simulations/
- https://unmethours.com/question/31609/how-to-run-energyplus-in-multi-core-clusterlinux/
- https://github.com/santoshphilip/eppy/blob/55410ff7c11722f35bc4331ff5e00a0b86f787e1/eppy/runner/run_functions.py#L141
