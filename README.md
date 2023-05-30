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
