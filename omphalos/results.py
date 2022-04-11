class Results():
    """An object containing the results of a given CrunchTope input file.

    Results objects contain objects refering to the contents of each type of CrunchTope output file,
    e.g. totcon, conc, pH, volume, etc.
    """

    def __init__(self):
        self.results_dict = {}

    def get_output(self, path_to_directory, output):
        """Get the spatial profile from an output file.

        Reads the first output file in an output file series, tecplot format only.
        Thus, the convention for this project is to only specify the final time step in the input file.
        This is justified because we are only interested in the final state of the system in this project.
        """
        import omphalos.file_methods as fm

        df = fm.read_tec_file(path_to_directory, output)
        self.results_dict.update({output: df})
