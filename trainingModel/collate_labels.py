import numpy as np
import pandas as pd
import file_methods as fm

class Results(self):
    """An object containing the results of a given CrunchTope input file."""
    
    def __init__(self):
        self.results_dict = {}
        
    def get_output(self, path_to_directory, output):
        """Get the spatial profile from an output file.
        
        Reads the first output file in an output file series, tecplot format only.
        Thus, the convention for this project is to only specify the final time step in the input file.
        This is justified because we are only interested in the final state of the system in this project.
        """
        filePath = '{}{}1.tec'.format(path_to_directory, output)
        pd.read_csv(filePath, sep='\s+')
        
