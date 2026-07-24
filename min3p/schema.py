"""Sub-keyword vocabulary for MIN3P data blocks.

This is a *vocabulary* schema, not a full positional transcription. For each
data block it lists the single-quoted sub-keywords that MIN3P recognises, so the
parser can group positional data lines under the sub-keyword that owns them (see
``keyword_block.Min3pBlock.group``). All names are stored normalised (lowercase,
quotes stripped, whitespace collapsed) to match ``keyword_block.normalise``.

Because the parser preserves every line regardless, an incomplete vocabulary
only limits which parameters can be addressed by name -- it never affects
round-trip fidelity. Blocks absent from the schema (or sub-keywords absent from
a block's set) simply have their data lines fall under the synthetic
``'_header'`` group, where they remain positionally addressable.

Block names use the spelling that appears in the input *files* (verified ground
truth), which occasionally differs from the manual's (e.g. files write
``variably saturated``, the manual ``variably-saturated``); alias keys bridge
the common variants.

Sources: MIN3P_THCm User Manual (Draft, 2019) section 3 data-block grammar, and
the ``batch/appelo`` (0-D batch) and ``reactran/MCD-2`` (1-D transport)
benchmark input files.
"""

# Canonical (normalised) names of the data blocks that open a top-level block.
# NB: block detection does NOT rely on this set -- MIN3P blocks never nest and
# always close with 'done', so the opener is simply the first quoted line after
# each terminator. This set is provided for validation and documentation.
BLOCK_OPENERS = {
    'global control parameters',                       # Data Block 1
    'geochemical system',                              # Data Block 2
    'spatial discretization',                          # Data Block 3
    'potential reference coordinates',                 # Data Block A (electromigration)
    'time step control - global system',               # Data Block 4
    'control parameters - local geochemistry',         # Data Block 5
    'control parameters - variably saturated flow',    # Data Block 6
    'control parameters - energy balance',             # Data Block 6b
    'control parameters - reactive transport',         # Data Block 7
    'output control',                                  # Data Block 8
    'physical parameters - porous medium',             # Data Block 9
    'physical parameters - variably saturated flow',   # Data Block 10
    'physical parameters - energy balance',            # Data Block 10b
    'physical parameters - reactive transport',        # Data Block 11
    'initial condition - variably saturated flow',     # Data Block 12
    'initial condition - energy balance',              # Data Block 12b
    'boundary conditions - variably saturated flow',   # Data Block 13
    'boundary conditions - energy balance',            # Data Block 13b
    'initial condition - local geochemistry',          # Data Block 14 (batch)
    'initial condition - reactive transport',          # Data Block 15
    'boundary conditions - reactive transport',        # Data Block 16
    'ice sheet loading/unloading',                     # Data Block 17
    'plant transpiration and passive/rejective uptake',# Data Block 18
    'control parameters - water flow',                 # older name for DB6 control
    'control parameters - evaporation',                # evaporation control
    'control parameters - bubble model',               # gas-bubble control
}

# Sub-keyword sets shared by the zone-structured physical/IC/BC blocks.
_ZONE_KEYS = {'number and name of zone', 'extent of zone', 'end of zone'}

# Per-block sub-keyword vocabularies. Keys are normalised block names.
MIN3P_SCHEMA = {
    # Data Block 1 -- title + positional logicals, then optional process flags.
    'global control parameters': {
        'multicomponent diffusion',
        'poisson',
        'electromigration',
        'self potential',
        'energy balance',
        'density dependent flow',
        # Restart-chain directives (see run.run_staged / generate_inputs).
        'restart',
        'append results',
        'append results in legacy mode',
        'number of skipped output times',
    },

    # Data Block 2 -- geochemical system definition.
    'geochemical system': {
        'use new database format',
        'database directory',
        'define input units',
        'define temperature',
        'define temperature field',
        'compute alkalinity',
        'components',
        'non-aqueous components',
        'secondary aqueous species',
        'sorbed species',
        'redox reactions',
        'redox couples',
        'intra-aqueous kinetic reactions',
        'scaling for intra-aqueous kinetic reactions',
        'minerals',
        'gases',
        'surface sites of ion-exchange',
        'define sorption type',
        'specify output unit for scm sorbed species concentration',
        'combine mineralogical parameters',
        'define minimum reaction rate',
        'excluded minerals',
        'use pitzer model',
        'use macinnes convention',
        'use sit model',
    },

    # Data Block 3 -- spatial discretization: mostly positional; structured /
    # radial / unstructured-grid options.
    'spatial discretization': {
        'radial coordinates',
        'structured spatial discretization',
        'control volume method',
        'allow obtuse cells',
        'read unstructured grid from file',
    },

    # Data Block A -- potential reference coordinates: positional.
    'potential reference coordinates': set(),

    # Data Block 4 -- time step control, global system: positional, one option.
    'time step control - global system': {
        'periodic maximum time step',
    },

    # Data Block 5 -- control parameters, local geochemistry.
    'control parameters - local geochemistry': {
        'finite minerals',
        'newton iteration settings',
        'activity update settings',
        'maximum ionic strength',
        'minimum activity for h2o',
        'output time unit',
        'sparse block matrices',
        'dense block matrices',
        'solver settings',
    },

    # Data Block 6 -- control parameters, variably saturated flow.
    'control parameters - variably saturated flow': {
        'mass balance',
        'iterative solver',
        'input units for boundary and initial conditions',
        'input units for media permeability',
        'variable density parameters',
        'non-linear density',
        'reference tds',
        'reference temperature for density',
        'compute underrelaxation factor',
        'newton iteration settings',
        'solver settings',
    },

    # Data Block 6b -- control parameters, energy balance.
    'control parameters - energy balance': {
        'update viscosity',
        'viscosity model',
        'non-storage term in flow equation',
        'reference temperature for density',
        'energy balance parameters',
        'thermal conductivity model',
        'newton iteration settings',
        'solver settings',
    },

    # Data Block 7 -- control parameters, reactive transport.
    'control parameters - reactive transport': {
        'mass balance',
        'charge balance',
        'charge conservation',
        'output fluxes',
        'output electric field',
        'averaging diffusion',
        'spatial averaging - diffusion',
        'harmonic average in porosity',
        'spatial weighting',
        'species dependent diffusion',
        'new viscosity derivative',
        'activity update settings',
        'tortuosity correction',
        'update porosity',
        'update permeability',
        'newton iteration settings',
        'solver settings',
    },

    # Data Block 8 -- output control.
    'output control': {
        'output of spatial data',
        'output of transient data',
        'coordinate output',
        'output in terms of depth',
        'output of mass through specified boundary',
        'output activity coefficients',
        'isotope output',
    },

    # Data Block 9 -- physical parameters, porous medium.
    'physical parameters - porous medium': _ZONE_KEYS | set(),

    # Data Block 10 -- physical parameters, variably saturated flow.
    'physical parameters - variably saturated flow': {
        'hydraulic conductivity in x-direction',
        'hydraulic conductivity in y-direction',
        'hydraulic conductivity in z-direction',
        'specific storage coefficient',
        'soil hydraulic function parameters',
        'residual gas saturation',
        'end of zone',
    },

    # Data Block 10b -- physical parameters, energy balance.
    'physical parameters - energy balance': _ZONE_KEYS | {
        'read energy balance parameters from file',
        'specific heat of water',
        'specific heat of solid',
        'specific heat of air',
        'water thermal conductivity in x-direction',
        'water thermal conductivity in y-direction',
        'water thermal conductivity in z-direction',
        'solid thermal conductivity in x-direction',
        'solid thermal conductivity in y-direction',
        'solid thermal conductivity in z-direction',
        'gas thermal conductivity',
        'solid bulk density',
        'longitudinal dispersivity',
        'transverse horizontal dispersivity',
        'transverse vertical dispersivity',
    },

    # Data Block 11 -- physical parameters, reactive transport.
    'physical parameters - reactive transport': {
        'diffusion coefficients',
        'longitudinal dispersivity',
        'transverse horizontal dispersivity',
        'transverse vertical dispersivity',
        'tortuosity correction',
        'end of zone',
    },

    # Data Block 12 -- initial condition, variably saturated flow.
    'initial condition - variably saturated flow': _ZONE_KEYS | {
        'initial condition',
        'read initial condition from file',
    },

    # Data Block 12b -- initial condition, energy balance.
    'initial condition - energy balance': _ZONE_KEYS | {
        'initial condition',
        'read initial condition from file',
        'geothermic gradient',
    },

    # Data Block 13 -- boundary conditions, variably saturated flow.
    'boundary conditions - variably saturated flow': _ZONE_KEYS | {
        'boundary type',
    },

    # Data Block 13b -- boundary conditions, energy balance.
    'boundary conditions - energy balance': _ZONE_KEYS | {
        'boundary type',
    },

    # Data Block 14 -- initial condition, local geochemistry (batch reactions).
    'initial condition - local geochemistry': {
        'number and name of zone',
        'kinetic batch simulation',
        'kinetically controlled dissolution-precipitation reactions',
        'concentration input',
        'guess for ph',
        'mineral input',
        'linear sorption input',
        'sorption parameter input',
        'redox reactions',
        'end of zone',
    },

    # Data Block 15 -- initial condition, reactive transport.
    'initial condition - reactive transport': _ZONE_KEYS | {
        'concentration input',
        'guess for ph',
        'mineral input',
        'linear sorption input',
        'sorption parameter input',
        'sorption parameter input of ion-exchange',
        'cec fraction of multisite ion exchange',
        'equilibrate with fixed solution composition of ion-exchange',
        'initial condition for isotope components',
    },

    # Data Block 16 -- boundary conditions, reactive transport.
    'boundary conditions - reactive transport': _ZONE_KEYS | {
        'boundary type',
        'concentration input',
        'guess for ph',
        'use background chemistry for boundary zone',
        'start of target read time input',
        'end of target read time input',
    },

    # Data Block 17 -- ice sheet loading/unloading (positional; add as needed).
    'ice sheet loading/unloading': set(),

    # Data Block 18 -- plant transpiration and passive/rejective uptake.
    'plant transpiration and passive/rejective uptake': set(),

    # Evaporation / gas-bubble control blocks (positional; add vocab as needed).
    'control parameters - evaporation': set(),
    'control parameters - bubble model': set(),
}

# Bridge common block-name spelling variants (manual vs files) to the same
# vocabulary, so vocab_for() works regardless of which spelling a file uses.
_ALIASES = {
    'control parameters - variably-saturated flow': 'control parameters - variably saturated flow',
    'physical parameters - variably-saturated flow': 'physical parameters - variably saturated flow',
    'initial condition - variably-saturated flow': 'initial condition - variably saturated flow',
    'boundary conditions - variably-saturated flow': 'boundary conditions - variably saturated flow',
    # Older/alternate spelling of the variably-saturated-flow control block.
    'control parameters - water flow': 'control parameters - variably saturated flow',
}


def vocab_for(block_name):
    """Return the recognised sub-keyword set for a block name.

    The name is normalised defensively (lowercased, quotes stripped, en-dashes
    folded to hyphens) so callers may pass either a raw or pre-normalised name.
    Unknown blocks return an empty set, so their data lines all fall under the
    synthetic ``'_header'`` group and remain addressable positionally.

    Args:
        block_name: Block name (raw or normalised).

    Returns:
        Set of normalised sub-keyword strings (possibly empty).
    """
    from min3p.keyword_block import normalise
    key = normalise(block_name)
    key = _ALIASES.get(key, key)
    return MIN3P_SCHEMA.get(key, set())
