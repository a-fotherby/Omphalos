# Omphalos
### A tool for automating the design and running of geochemical modelling experiments in CrunchTope.

+ Simplify your geochemical modelling!
+ Test thousands of parameter combinations with a single line of code. 
+ Collate all your results in a single simple to use database.

## Installation

1. Make sure conda is installed on your system: https://docs.conda.io/en/latest/
2. Run the installation script: `./install.sh`
   1. Make sure you provide the *absolute path* to your CrunchTope executable. 
   2. You can always change it later in `omphalos/settings.py`.
3. Activate the conda environment: `conda activate omphalos`

## Quick-start

To use Omphalos you need two things:

1. A working CrunchTope model
2. A `.yaml` file specifying the way in which the CrunchTope model parameters are to be varied.
    - An example `config.yaml` is shown in the top level of this repository.

### Commands
#### Running Omphalos
There are two main commands, each with two args. 
`ompahlos` runs CrunchTope simulations sequentially, as is as such a legacy mode
but forms the core functionality of the program. It's only recommended for extremely simple simulations.
`rhea` will run CrunchTope simulations in parallel, either locally or on a slurm managed cluster.
Most users are going to be using `rhea`, rather than `omphalos` as it is faster.
- `omphalos config_name output_name`
- `rhea config_name mode`

The argument `config_name` is the path to the `config.yaml` for the run. 
The arg `mode` takes one of two options, either `cluster` or `local`.
- In the case of `cluster`, CrunchTope simulations will be submitted to nodes on a slurm managed cluster.
This **should** work out of the box, but if you wish to tinker with the settings for the submission 
(e.g. change memory per node and such like) then the `.sbatch` can be found in `rhea/parrallel.sbatch`.
- `local` will run CrunchTope simulations simultaneously on your local machine.
Because CrunchTope is single threaded, you can run as many simulations as you have cores.
I don't recommend submitting more runs than you have cores
as you are going to make your machine unresponsive until the simulations are done.

#### Collecting the results

Results come in the form of two files. 
`results.nc` is a netCDF4 file containing all the results from the various simulations.
Each different kind of CrunchTope spatial profile output (e.g. `volume`, `totcon`, etc.)
is the name of a [netCDF4 group](https://docs.xarray.dev/en/stable/user-guide/io.html#groups).
You can import it using `xarrray.open_dataset()`, 
so if, for example, you wanted to import the mineral volume data for all your different simulations you would run
`xarray.open_dataset(results.nc, group='volume')`.
Data can be straight-forwardly analysed from the xarray format.

The second file, `inputs.pkl` is a pickled `dict` of the CrunchTope input files used to generate the data.
This is given so that there is a record of the parameters varied, and for debugging purposes.
There is an unpickle method in `omphalos.file_methods` that takes the path to the pickle as its argument
and will return the `dict` of `InputFile` objects. The original text file of an input file can be recovered using the `InputFile.print()` method.

## Usage

### Non-unique entries
Some CrunchTope inputs don't have unique left-most values.
In this case, special subroutines are required to handle this in the dictionary structure employed by Omphalos.
Notable cases include in the `FLOW` and `INITIAL_CONDITONS` blocks where the user may specify the same condition over non-contiguous regions,
as well as in the `ISOTOPE` block where `primary` or `mineral` are always the left most entry.

Most likely to be of interest to most users is the case in which one has parallel mineral reactions specified in the `MINERAL` block.
For example, this might be having both a neutral and acid mechanism for mineral dissolution.
Unlike in the previous cases where we can select a different unique keyword from a predictable location in the entry
(meaning that the issue can be handled internally by Omphalos), we are not guaranteed to have such an entry at our disposal.

As such, this **does** affect how the user specifies different parallel mineral reactions in the Omphalos `.yaml` format.
This ultimately makes good sense as the user would need to be able to differentiate between different mineral mechanism somehow in any case.


The way it is implemented is as follows:
  - By default, all mineral names will be compounded in the `MINERALS` block with their label in the format `{mineral_name}&{kinetics_label}`.
  - If the mineral does not have a kinetics label on the input file then the label name will be take as the CrunchTope default, which is 'default'.
    - For example, an entry in the input file of `Forsterite -rate -12.0` would be indexable in a `.yaml` file as `Foreterite&default`.
    - Similarly, an entry referring to the kinetics for an acidic mechanism of calcite dissolution, `Calcite -label h+ -ssa 4e-4` would be accessible with the key `Calcite&h+`.
  - Otherwise, the entries in the `MINERAL` block can be accessed and manipulated in the usual way.

**THIS MEANS THAT YOU CANNOT USE AMPERSANDS IN MINERAL NAMES IN YOUR INPUT FILES!**
This isn't a common naming scheme, so it shouldn't trip up many users, but I emphasise it just in case.

### About

&copy; Angus Fotherby (2019 - 2023). All rights reserved.
