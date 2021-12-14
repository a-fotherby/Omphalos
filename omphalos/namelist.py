"""Read in F90 namelist files describing reaction parameters."""

class CrunchNameList():

    def __init__(self, path):
        self.path = path
        self.namelist = self.read_namelist()

    def read_namelist(self):
        """Imports a namelist file describing reaction parameters and returns a nested dictionary, organised by
        category/reaction name.
        """
        import f90nml

        with open(self.path) as file:
            nml = f90nml.read(file)

        return nml

    def print(self, path):
        import f90nml

        f90nml.write(self.namelist, path, force=True)

    def modify_namelist(self, input_file, config, nml_type):
        """Change the parameters of a namelist associated with an InputFile.

        Args:
        nml -- the namelist attribute of the InputFile
        config -- the run configuration file, stored in the Template
        """
        from omphalos.generate_inputs import get_config_value

        # Get the attribute corresponding to the namelist file in the InputFile.
        nml = self.namelist
        # This NameList will be composed of a list of NameLists, each referring to one reaction. In the case of the
        # aqueous_database, there will be two NameLists of reactions, each reaction having an entry in each.
        for list in nml:
            # We then iterate over the reaction NameLists inside.
            for reaction in nml[list]:
                # We extract the reaction name for indexing in the config.
                reaction_name = reaction['name']
                # Then iterate over each parameter inside the reaction NameList and try to get a value to assign for
                # each parameter. Only those with a valid entry in the config will return non-None values and be
                # assigned. We need the extra try-except statement to catch indexing errors due to indexing reaction
                # names that aren't in the config.
                for parameter in reaction:
                    try:
                        value_to_assign = get_config_value(parameter, config,
                                                           config['namelists'][nml_type][reaction_name],
                                                           input_file.file_num, config['namelists'][nml_type])
                    except:
                        value_to_assign = None

                    if value_to_assign is None:
                        continue

                    reaction[parameter] = value_to_assign
