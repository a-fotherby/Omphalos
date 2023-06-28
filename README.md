# Omphalos
### A tool for automating the design and running of geochemical modelling experiments in CrunchTope.

+ Simplify your geochemical modelling!
+ Test thousands of parameter combinations quickly. 
+ Collate all your results in a single python datastructure.

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
(e.g. change memory per node and such like) then the `.sbatch` can be found in `rhea/parallel.sbatch`.
- `local` will run CrunchTope simulations simultaneously on your local machine.
Because CrunchTope is single threaded, you can run as many simulations as you have cores.
I don't recommend submitting more runs than you have cores
as you are going to make your machine unresponsive until the simulations are done.

#### Collecting the results

Results come in the form of two files. 
`results.nc` is a netCDF4 file containing all the results from the various simulations.
Each different kind of CrunchTope spatial profile output (e.g. `volume`, `totcon`, etc.)
is the name of a [netCDF4 group](https://docs.xarray.dev/en/stable/user-guide/io.html#groups).
You can import it using `xarray.open_dataset()`, 
so if, for example, you wanted to import the mineral volume data for all your different simulations you would run
`xarray.open_dataset(results.nc, group='volume')`.
Data can be straight-forwardly analysed from the xarray format.

The data in the xarray object will have five dimensions. Three spatial dimension, `X`, `Y`, and 'Z', 
a temporal dimension, `time`. It will also have a dimension representing which run the data was collected from, `file_num`.

The second file, `inputs.pkl` is a pickled `dict` of the CrunchTope input files used to generate the data.
This is given so that there is a record of the parameters varied, and for debugging purposes.
There is an unpickle method in `omphalos.file_methods` that takes the path to the pickle as its argument
and will return the `dict` of `InputFile` objects. The original text file of an input file can be recovered using the `InputFile.print()` method.

## Usage

### Config specification
Omphalos reconfigures CrunchTope input files based on the options specified in the `.yaml` file given in the argument `config_name`.
An example config is given in `example.yaml`.
The config file is split into two parts
- The front matter, which specifies things like the database and the input file being used, etc.
- The specification, which details how to vary each of the input files.

The syntax is explained below. All keywords in the front matter must be present, even if they are left empty.

### Config file syntax

#### Frontmatter
All frontmatter keyword *must* be present in the config file.
If they are not applicable (e.g. no aqueous reactions are being used), then the keyword must remain but blank,
e.g. `aqueous_database:`.

- `template`: Path to the input file that will be used as a template and modified.
- `database`: Path to the thermodynamic database.
- `aqueous_database`: Path to the aqueous database.
- `catabolic_pathways`: Path to the catabolic pathways files.
- `timeout`: Maximum time for a run before it is cancelled and as much data as has been produced is collated.
- `conditions`: A list of the names of all the geochemical conditions (CONDITION blocks) that will be modified in the run.
- `number_of_files`: Number of files in the run.
- `nodes`: Number of slurm nodes (if in parallel mode) or cores (if in local mode) to allocate to a run.

#### Configuration
All configuration is optional and takes the form of nested lists in the config file
which identifies what parameter in the input file (`template`) to change and how to change it.
There are 4 major syntax groups in the input file that can be changed

1. Keyword blocks. These are any block in the main input file except `CONDITION` blocks. E.g. `FLOW` or `MINERALS`.
2. Condition blocks. These are the blocks that represent geochemical conditions in the input file 
with the syntax `CONDITION name` where name is a user chosen name for that condition, like 'seawater', for example.
<a name="namelist_info">
3. Namelists. These are the auxiliary files used by CrunchTope to define specific reaction pathways, 
and these can also be systematically altered by Omphalos. Currently in CrunchTope there exist two such files, 
    - the aqueous database
    - the catabolic pathways

    Each namelist can be indexed into and edited. The keywords for accessing each name list is given below 
    but the convention is to use the namelist name with the ampersand stripped in `snake_case`. 

    - `&Aqueous` which details the reaction stoichiometry in the aqueous database is referenced in the config file as `aqueous'
    - `&AqueousKinetics` which gives the reaction kinetics is accessed using `aqueous_kinetics`.
    - Entries in the catabolic pathways file are accessed using `catabolic_pathways`.
</a>
We now turn to each of these categories to explain the generic syntax that allows access to any variable in each of these cases,
detailing any exceptions. Significant exceptions in the case of "non-unique entries" are detailed [below](#Non-unique-entries).

##### Keyword blocks

To illustrate how this is done, we will take the example of wanting to modify the kinetic rate parameter of quartz 
by selecting random values between 1e-15 and 1e-16.
A use case for this kind of modification might be to do a basic form of sensitivity analysis.
In all cases the specification starts with identifying the block, which is the right keyword followed by a colon.
The keyword block names are *not* always just a `snake_case` version of the CrunchTope KEYWORD name due to some ambiguity.
A table is shown here:

| KEYWORD block name | Omphalos keyword |
|--------------------|------------------|
| TRANSPORT          | transport        |
| FLOW               | flow             |
| EROSION/BURIAL     | erosion/burial   |
| MINERALS           | mineral_rates    |
| AQUEOUS_KINETICS   | aqueous_kinetics |
| RUNTIME            | runtime          |
| OUTPUT             | output           |

But continuing with the example:

    mineral_kinetics:    

Any variable inside that keyword block can then be specified

    mineral_kinetics:
        Quartz(alpha):
            
We then have to specify how we wish to change the parameter in our input file. 
Omphalos has a number of built-in options for this (listed [here]), but in this case we want `random_uniform`.
Each option has its own syntax depending on what it is, but in general it consists of a name-array pair,
with the name specifying the option and the array containing any numerical data required, as shown below.

    mineral_kinetics:
        Quartz(alpha):
            - 'random_uniform'
            - [1e-16, 1e-15]

If we then wanted to modify the kinetics of a second mineral, we could do at the indent level as the Quartz.
The config file takes `#` as comments.

    mineral_kinetics:
        Quartz(alpha):
            - 'random_uniform'
            - [1e-16, 1e-15]
        Kaolinite:
            - 'random_uniform'
            # Scream If You Wanna Go Faster!
            - [1e-14, 1e-13]

##### Condition blocks

This is likely the functionality that most users are going to want out of this software.
Condition blocks are dealt with slightly differently to keyword blocks.
Because they refer to species listed in either GASES, MIENRALS, or PRIMARY_SPECIES blocks, 
as well as some generic physical parameters in the condition being described (e.g. temperature)
which all require different treatment when interpreting and modifying them, it has been prudent to split them into five sub-categories:

- `concentrations`: referring to the concentrations of primary species.
- `mineral_volumes`: referring to mineral volume fractions.
- `mineral_ssa`: referring to mineral surface areas (either bulk or specific)
- `gases`: referring gas species partial pressures.
- `parameters`: referring to any other parameters, such a temperature or pH.

So taking the example syntax given in the KEYWORD block explanation as an analogy,
to uniquely identify a species in a geochemical CONDITION block, we indentify the name of the condition,
then the sub-category (concentration, mineral volume, etc.) and then finally the species and new values.
An example of this might systematically changing the concentration of seawater sulfate to test some different paleo-ocean compositions,
which we will build up in the same way as before.
First, we give the name of the condition we want to modify (which you hopefully remembered to list in the Frontmatter!):

    seawater:

Then we specify we want to change primary species concentrations:

    seawater:
        concentrations:

Then we specify the species, in this case SO4--:

    seawater:
        concentrations:
            SO4--:

And finally we specify the way in which we want to change the variable. 
In this case lets do some different seawater states that might have existed in the past,
and do a linear sweep over that range 
(note that the units are set inside the input file, and here they are set to mM):

    seawater:
        concentrations:
            SO4--:
              - 'linspace'
              - [1,30,1]

Where the syntax for the 'linspace' is saying sweep values between 1 and 30, repeating each value 1 time
(you may wish to repeat values if you are varying multiple species at once).
The number of values actually generated is set by the `number_of_files` parameter in the front matter.

##### Namelists

Values that are in either `aqueous_kinetics.dbs` or `catabolic_pathways.in` are formatted as Fortran90 namelists,
and thus require some special consideration.
To access these files we start by indexing the top-level in the configuration file as `namelists`:

    namelists:

Then index the name list (using the name convention described [here](#namelist_info)). 
So if we take changing the equilibrium constant for sulfate reduction as our example we have:

    namelists:
        aqueous:
            sulfate_reduction:

Which gets us into the namelist for that particular reaction.
We can then change the rate by indexing the name for the equilibreum constant, in this case `keq`:
    
    namelist:
        aqueous:
            sulfate_reduction:
                keq:

This can then be modified in the usual way:

    namelists:
        aqueous:
            sulfate_reduction:
                keq:
                    - 'random_uniform'
                    - [14, 15]

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
