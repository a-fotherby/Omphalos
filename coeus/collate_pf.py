# Script to collate data from Rhea runs.
# Will return pickled file dict as usual, with as many timesteps as it can find in each directory.

if __name__ == "__main__":
    import sys
    import h5py
    import os
    import re
    import xarray as xr
    from pathlib import Path
    from datetime import datetime

    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    from coeus.pflotran import h5_to_xarray

    # Directory containing the run directories
    directory = os.getcwd()

    # List to hold all datasets
    datasets = []

    # Iterate over each run directory matching the pattern 'run{number}' in strictly ascending order
    run_dirs = sorted([subdir for subdir in os.listdir(directory) if re.match(r"run\d+", subdir)], key=lambda x: int(re.search(r"\d+", x).group()))
    for subdir in run_dirs:
        subdir_path = os.path.join(directory, subdir)
        if os.path.isdir(subdir_path):
            print(f"Processing {subdir_path}...")
            
            # Look for a file ending in .in within the run directory
            in_files = [f for f in os.listdir(subdir_path) if f.endswith(".in")]
            if in_files:
                # Strip the file ending from the .in file name to get the base name
                base_name = os.path.splitext(in_files[0])[0]
                
                # Look for a .h5 file matching the base name
                hdf5_filename = f"{base_name}.h5"
                hdf5_file_path = os.path.join(subdir_path, hdf5_filename)
                
                if os.path.exists(hdf5_file_path):
                    print(f"Found {hdf5_filename}!")
                    try:
                        with h5py.File(hdf5_file_path, "r") as hdf:
                            print(f"Successfully opened {hdf5_filename}")
                            
                            # Convert HDF5 data to xarray Dataset using the pflotran function
                            dataset = h5_to_xarray(hdf)
                            datasets.append(dataset)
                            print(f"xarray Dataset from {hdf5_filename} successfully created.")
                    except (OSError, KeyError) as e:
                        print(f"Failed to open or process {hdf5_filename}: {e}")

    # Combine all datasets along a new axis called 'file_number'
    if datasets:
        try:
            combined_dataset = xr.concat(datasets, dim="file_number", coords='minimal', compat='override', join='outer')
            print("Combined xarray Dataset successfully created.")

            # Write the combined dataset to a NetCDF file with date and time in the name
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"collated_runs_{timestamp}.nc"
            combined_dataset.to_netcdf(output_filename)
            print(f"Combined dataset written to {output_filename}")
        except ValueError as e:
            print(f"Failed to concatenate datasets: {e}")
    else:
        print("No datasets were found or processed.")

    print("Finished processing all files.")