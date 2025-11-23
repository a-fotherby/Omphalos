"""Database parsing for CrunchTope"""

class Database:
    
    def __init__(self, path):
        self.path = path
        self.raw_database = []
        self.temp_points = None
        self.temp_field = None
        self.dh_params = []
        self.primary_species = {}
        self.secondary_species = {}
        self.gases = {}
        self.minerals = {}
        self.surface_complexation = {}    
        self.mineral_kinetics = {}
        self.aqueous_kinetics = {}   
        self.delim_lines = [4]
        
        import re
        import copy
        
        delim_strings = set(["'End of primary'", "'End of secondary'", "'End of gases'", "'End of minerals'", 'End of surface complexation', 'End of mineral kinetics', 'End of exchange', 'End surface complexation parameters'])
        assign_blocks = ['primary_species', 'secondary_species', 'gases', 'minerals', 'surface_complexation', 'mineral_kinetics', 'aqueous_kinetics']
        
        species_class = {0: Species, 1: SecondarySpecies, 2: Gas, 3: Mineral}
    
        with open(self.path, 'r') as f:
            for line_num, line in enumerate(f):
                # N.B. Line numbers in file start from 1, ennumerate starts from 0, so we are offset from "true" line number as reported by text file by 1.
                
                # Require line_num approach because some delimiter lines are non-unqiue.
                # Crunchfiles edited on UNIX systems have newline characters that must be stripped.
                # Also strip any trailing whitespace.
                
                
                line = line.rstrip('\r\n ')
                line = re.split("(?<![a-zA-Z])\s+", line) # Magic Regex!

                if line[0] in delim_strings:
                    self.delim_lines.append(line_num)
                
                self.raw_database.append(line)
            f.close
                        
        for i, line in enumerate(self.raw_database):
            for j, entry in enumerate(self.raw_database[i]):
                try:
                    self.raw_database[i][j] = float(entry)
                except Exception:
                    if entry.startswith('!'):
                        del self.raw_database[i][j]
                    else:
                        self.raw_database[i][j] = entry.strip("'")
        
        # Can take some liberties in using line num and position as they have to follow certain format to be compatible with CT.
        self.temp_points = self.raw_database[0][1]
        self.temp_field = self.raw_database[0][2:]
        self.dh_params = self.raw_database[1:4]
        
        for i, key in enumerate(assign_blocks):
            
            start = self.delim_lines[i]
            end = self.delim_lines[i+1]
            try:
                for entry in self.raw_database[start:end]:
                    if entry[0].startswith('End') or entry[0].startswith('Begin'):
                        continue
                    else:
                        vars(self)[key].update({entry[0]: species_class[i](entry)})
            except Exception:
                vars(self)[key] = copy.deepcopy(self.raw_database[start:end])
            
            #if key == 'mineral_kinetics':
            #    clean_mineral_kinetics


            
class Species:

    def __init__(self, database_entry):
        self.name = database_entry[0]
        self.dh_size = database_entry[1]
        self.charge = database_entry[2]
        self.weight = database_entry[3]
        
        
class SecondarySpecies(Species):
    
    def __init__(self, database_entry):
        self.name = database_entry[0]
        self.dh_size = database_entry[-3]
        self.charge = database_entry[-2]
        self.weight = database_entry[-1]
        self.log_k = database_entry[-11:-3]
        self.reaction_species_count = int(database_entry[1])
        reaction_end = 2 + (self.reaction_species_count*2)
        self.reaction = Reaction(self.name, database_entry[2:reaction_end])
        

class Reaction():
    # All CT databases are written in terms of the breakdown of the secondary species (/mineral/gas).
    # Therefore, negative stoichiometric coefficient indicates a reactant and positive indicates a product.
    # Reaction datastruct contains two dicts, one for products and one for reactions.
    
    def __init__(self, species_name, reaction_array):        
        # Check to make sure reaction_array is even.
        if len(reaction_array) % 2 == 1:
            raise Exception("Unpaired stoichiometric coefficient/species name in {} database entry".format(species_name))
        
        self.products = {}
        self.reactants = {species_name: 1.0}
                
        for i in range(int(len(reaction_array) / 2)):
            index = i*2
            if reaction_array[index] == 0:
                raise Exception("Stoichiometric coefficient = 0 in {} database entry".format(species_name))
            elif reaction_array[index] > 0:
                # Product.
                self.products.update({reaction_array[index+1]: reaction_array[index]})
            elif reaction_array[index] < 0:
                # Reactant. Multiply by -1 to flip sign on reactant so we don't imply negative reactant.
                self.reactants.update({reaction_array[index+1]: (reaction_array[index] * -1)})
        

class Gas(SecondarySpecies):
    
    def __init__(self, database_entry):
        self.name = database_entry[0]
        self.molecular_size = database_entry[1]
        self.dh_size = database_entry[-3]
        self.charge = database_entry[-2]
        self.weight = database_entry[-1]
        self.log_k = database_entry[-11:-3]
        self.reaction_species_count = int(database_entry[2])
        reaction_end = 3 + (self.reaction_species_count*2)
        self.reaction = Reaction(self.name, database_entry[3:reaction_end])
        
        
class Mineral(SecondarySpecies):
    rate_laws = set(['tst', 'monod', 'irreversible', 'PrecipitationOnly', 'DissolutionOnly', 'MonodBiomass'])
    
    def __init__(self, database_entry):
        self.name = database_entry[0]
        self.molar_volume = database_entry[1]
        self.weight = database_entry[-1]
        self.log_k = database_entry[-10:-2]
        self.reaction_species_count = int(database_entry[2])
        reaction_end = 3 + (self.reaction_species_count*2)
        self.reaction = Reaction(self.name, database_entry[3:reaction_end])
        #self.kinetic_params = associate_kinetics(name)
    
    def associate_kinetic(self):
        """Find kinetic database entry and assign to Mineral."""
        
        for line_num, line in enumerate(self.mineral_kinetics):
            if line[0] == name:
                label = self.mineral_kinetics[line_num + 1]
                law_type = self.mineral_kinetics[line_num + 2]
                default_rate = self.mineral_kinetics[line_num + 3]
                activation = self.mineral_kinetics[line_num + 4]
        self.label = None
        self.type = None
        self.rate25 = None
        self.activation = None
        self.dependence = None
        self.affinity_dependence = None
        self.monod_terms = {}
        self.inhibition = {}
        
if __name__ == "__main__":
    database = Database('test_database.dbs')
    print(type(database.temp_points))
    print(database.temp_field)
    print(database.dh_params)
    print(database.secondary_species)
    print(database.minerals["Uraninite"].reaction.__dict__)
    print(database.mineral_kinetics)

        
        
        