# Put the full paths to your CrunchTope executables and your Omphalos directories in here.
# Then remove the _default from this file name.
crunch_dir = '/your/CrunchTope/path'
omphalos_dir = '/your/Omphalos/path'

# Optional. Omphalos identifies which spelling of the auxiliary-database RUNTIME keywords your
# CrunchTope reads by searching the executable, so this is normally unnecessary. Set it only for a
# build that contains neither spelling, where install.sh says it could not tell:
#
#   CrunchTope 1.x:  {'aqueous': 'kinetic_database', 'catabolic': 'catabolic_database'}
#   CrunchTope 2+:   {'aqueous': 'aqueousdatabase',  'catabolic': 'catabolicdatabase'}
#
# crunch_keywords = {'aqueous': 'kinetic_database', 'catabolic': 'catabolic_database'}
