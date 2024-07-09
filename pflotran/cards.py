"""Define pflotran's input cards for parsing. Use a nesting doll strategy...
A card in this context is anything block of text in the input file that has an unindented 'END' associated with it.
We therefore insist that END must be used to end a block, rather than an unindented '/', which is also usable.
'Unindented' here is a bit ambiguous as PFLOTRAN does not actually read indentation and only uses '/' or 'END' to close
block.

We are therefore going to use the hierarchy used in the PFLOTRAN user documentation to determine what is a "top" block,
each of which is contained in the 6 top level categories (which are themselves technically blocks) which are called in
this script.
"""


def verbatim():
    cards = {'simulation': 'SIMULATION',
             'subsurface': 'SUBSURFACE'}

    return cards


def editable():
    cards = {'constraint': 'CONSTRAINT', }

    return cards


def simulation():
    cards = {'simulation_type': 'SIMULATION_TYPE',
             'subsurface_transport': 'SUBSURFACE_TRANSPORT',
             'subsurface_geophysics': 'SUBSURFACE_GEOPHYSICS',
             'subsurface_flow': 'SUBSURFACE_FLOW',
             'checkpoint': 'CHECKPOINT',
             'restart': 'RESTART'}
    return cards


def non_unique_cards():
    cards = {'region': 'REGION',
             'characteristic_curves': 'CHARACTERISTIC_CURVES',
             'flow_condition': 'FLOW_CONDITION',
             'material_property': 'MATERIAL_PROPERTY',
             'transport_condition': 'TRANSPORT_CONDITION',
             'constraint': 'CONSTRAINT',
             'numerical_methods': 'NUMERICAL_METHODS',
             }

    return cards


def condition_couplers():
    cards = {'initial_condition': 'INITIAL_CONDITION',
             'boundary_condition': 'BOUNDARY_CONDITION',
             'strata': 'STRATA'}

    return cards


def subsurface():
    cards = {'thermal_characteristic_curves': 'THERMAL_CHARACTERISTIC_CURVES',
             'dataset': 'DATASET',
             'eos': 'EOS',
             'fluid_property': 'FLUID_PROPERTY',
             'grid': 'GRID',
             'integral_flux': 'INTEGRAL_FLUX',
             'klinkenberg_effect': 'KLINKENBERG_EFFECT',
             'linear_solver': 'LINEAR_SOLVER',
             'newton_solver': 'NEWTON_SOLVER',
             'nuclear_waste_chemistry': 'NUCLEAR_WASTE_CHEMISTRY',
             'observation': 'OBSERVATION',
             'output': 'OUTPUT',
             'regression': 'REGRESSION',
             'source_sink': 'SOURCE_SINK',
             'source_sink_sandbox': 'SOURCE_SINK_SANDBOX',
             'specified_velocity': 'SPECIFIED_VELOCITY',
             'time': 'TIME',
             'timestepper': 'TIMESTEPPER',
             'chemistry': chemistry(),
             'region': 'REGION',
             'characteristic_curves': 'CHARACTERISTIC_CURVES',
             'flow_condition': 'FLOW_CONDITION',
             'material_property': 'MATERIAL_PROPERTY',
             'transport_condition': 'TRANSPORT_CONDITION',
             'constraint': 'CONSTRAINT',
             'numerical_methods': 'NUMERICAL_METHODS'}

    return cards


def chemistry():
    cards = {'primary_species': 'PRIMARY_SPECIES',
             'secondary_species': 'SECONDARY_SPECIES',
             'passive_gas_species': 'PASSIVE_GAS_SPECIES',
             'complex_kinetics': 'COMPLEX_KINETICS',
             'general_reaction': 'GENERAL_REACTION',
             'immobile_decay_reaction': 'IMMOBILE_DECAY_REACTION',
             'ion_exchange_rxn': 'ION_EXCHANGE_RXN',
             'isotherm_reactions': 'ISOTHERM_REACTIONS',
             'minerals': 'MINERALS',
             'microbial_reaction': 'MICROBIAL_REACTION',
             'output(chemistry)': 'OUTPUT(CHEMISTRY)',
             'radioactive_decay_reaction': 'RADIOACTIVE_DECAY_REACTION',
             'sorption': 'SORPTION',
             'surface_complexation_rxn': 'SURFACE_COMPLEXATION_RXN',
             'bioparticle': 'BIOPARTICLE',
             'clm-cn': 'CLM-CN',
             'reaction_sandbox': 'REACTION_SANDBOX'}

    return cards


def geomechanics():
    cards = ['GEOMECHANICS_BOUNDARY_CONDITION',
             'GEOMECHANICS_CONDITION',
             'GEOMECHANICS_GRID',
             'GEOMECHANICS_MATERIAL_PROPERTY',
             'GEOMECHANICS_OUTPUT',
             'GEOMECHANICS_REGION',
             'GEOMECHANICS_REGRESSION',
             'GEOMECHANICS_STRATA',
             'GEOMECHANICS_SUBSURFACE_COUPLING',
             'GEOMECHANICS_TIME']
    return cards


def geophysics():
    cards = ['GEOPHYSICS_CONIDTION',
             'SURVEY']
    return cards


def utility():
    cards = ['DBASE_FILENAME',
             'DEBUG',
             'EXTERNAL_FILE',
             'OVERWRITE_RESTART_TRANSPORT',
             'PROC',
             'SKIP',
             'WALLCLOCK_STOP']
    return cards


big_blocks = {'SIMULATION': simulation,
              'SUBSURFACE': subsurface,
              'GEOMECHANICS': geomechanics,
              'GEOPHYSICS': geophysics,
              'UTILITY': utility}
