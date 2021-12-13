"""Read in F90 namelist files describing reaction parameters."""


def read_namelist(path):
    """Imports a namelist file describing reaction parameters and returns a nested dictionary, organised by
    category/reaction name.
    """
    import f90nml

    with open(path) as file:
        nml = f90nml.read(file)

    return nml


def print_namelist(nml, path):
    import f90nml

    f90nml.write(nml, path, force=TRUE)

def search(nml_list, name):
    """Search for a Namelist by reaction name."""
    for nml in nml_list:
        if nml['name'] == name:
            return nml
        else:
            continue

    raise Exception(f"No Namelist with name matching {name} found.")