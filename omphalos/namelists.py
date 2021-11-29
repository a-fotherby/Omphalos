"""Read in F90 namelist files describing reaction parameters."""


def format_namelist(namelist):
    """Convert an imported CrunchTope namelist to a reaction-name indexed format."""
    namelist_dict = {}
    for reaction in namelist:
        reaction_name = reaction['name']
        namelist_entry = dict(reaction)
        namelist_entry.pop('name')
        namelist_dict.update({reaction_name: namelist_entry})

    return namelist_dict


def read_namelist(path):
    """Imports a namelist file describing reaction parameters and returns a nested dictionary, organised by
    category/reaction name.
    """
    import f90nml

    namelist = {}
    with open(path) as file:
        nml = f90nml.read(file)

    for category in nml:
        namelist.update({category: format_namelist(nml[category])})

    return namelist
