"""Which spelling of the auxiliary-database RUNTIME keywords a CrunchTope binary understands.

CrunchTope renamed the keywords that name the auxiliary databases, and the two generations are
mutually unintelligible:

    =====================  =====================  ========================
                           aqueous-kinetics file  catabolic-pathways file
    =====================  =====================  ========================
    CrunchTope 1.x         kinetic_database       catabolic_database
    CrunchTope 2+          aqueousdatabase        catabolicdatabase
    =====================  =====================  ========================

This matters more than a cosmetic difference, because CrunchTope does not complain about a keyword
it does not recognise -- StartTope.F90 reads each one with ``IF (parfind == ' ') THEN ... ! Use
default``. A 1.x-spelled deck run against a 2+ binary quietly proceeds *without* its aqueous
kinetics database and produces a plausible, wrong answer with no warning.

The spellings are compiled into the executable, so a string search over the binary identifies the
generation directly rather than having to ask.

Do not confuse these with Omphalos' own config keys, which is easily done: the config key
``aqueous_database`` corresponds to the deck keyword ``kinetic_database``/``aqueousdatabase``, and
the config key ``catabolic_pathways`` corresponds to ``catabolic_database``/``catabolicdatabase``.
"""

import functools
import os
import warnings

# Both spellings of each keyword, oldest generation first.
KEYWORD_GENERATIONS = (
    {'aqueous': 'kinetic_database', 'catabolic': 'catabolic_database'},
    {'aqueous': 'aqueousdatabase', 'catabolic': 'catabolicdatabase'},
)

# Assumed where a binary cannot be read or contains neither spelling.
DEFAULT_KEYWORDS = KEYWORD_GENERATIONS[0]

# Every spelling of every keyword, for recognising what a deck uses.
ALL_KEYWORDS = {
    keyword for generation in KEYWORD_GENERATIONS for keyword in generation.values()
}

# CrunchTope's default when the deck names no catabolic pathways file.
DEFAULT_CATABOLIC_FILE = 'CatabolicPathways.in'


def probe_binary(path):
    """Return the keyword pair a CrunchTope executable contains, or None.

    Args:
        path: Path to the CrunchTope executable.

    Returns:
        One of KEYWORD_GENERATIONS, or None where the binary cannot be read or holds neither pair --
        a stripped or unusual build.
    """
    try:
        with open(path, 'rb') as binary:
            contents = binary.read()
    except OSError:
        return None

    for generation in KEYWORD_GENERATIONS:
        if all(keyword.encode() in contents for keyword in generation.values()):
            return generation

    return None


@functools.lru_cache(maxsize=None)
def _cached_probe(path, mtime):
    """Probe once per build. mtime is part of the key so a rebuild is not missed."""
    return probe_binary(path)


def identify_build(binary=None):
    """Return the keyword pair a CrunchTope build understands, or None if it uses neither.

    Args:
        binary: Path to the executable. Defaults to the one settings.py records.

    Returns:
        One of KEYWORD_GENERATIONS, or None where the build cannot be found or read, or contains
        neither pair. Not every build has one: some read their aqueous kinetics by another route
        entirely and recognise no such keyword, in which case a deck naming one is ignored.
    """
    override = _configured_override()

    if override is not None:
        return override

    if binary is None:
        binary = _configured_binary()

    if binary is None:
        return None

    try:
        mtime = os.path.getmtime(binary)
    except OSError:
        return None

    return _cached_probe(str(binary), mtime)


def database_keywords(binary=None):
    """Return the keyword pair the configured CrunchTope understands.

    Args:
        binary: Path to the executable. Defaults to the one settings.py records.

    Returns:
        A dict with 'aqueous' and 'catabolic' keys. Falls back to the 1.x spellings where the build
        cannot be identified, which is what most builds in the wild use.
    """
    return identify_build(binary) or DEFAULT_KEYWORDS


def _configured_override():
    """Return the keyword pair settings.py names explicitly, or None.

    A build containing neither spelling -- stripped, or unusual -- cannot be probed, so install.sh
    reports that and points here.

    Raises:
        ValueError: If the override names something that is not a keyword pair.
    """
    try:
        from omphalos.settings import crunch_keywords
    except ImportError:
        return None

    if set(crunch_keywords) != {'aqueous', 'catabolic'}:
        raise ValueError(
            f"crunch_keywords in settings.py must have exactly 'aqueous' and 'catabolic' keys, "
            f'got {sorted(crunch_keywords)}.'
        )

    unknown = set(crunch_keywords.values()) - ALL_KEYWORDS

    if unknown:
        raise ValueError(
            f'crunch_keywords in settings.py names {sorted(unknown)}, which CrunchTope does not '
            f'read. Valid spellings: {sorted(ALL_KEYWORDS)}.'
        )

    return dict(crunch_keywords)


def binary():
    """Return the CrunchTope path to run, or None if nothing configures one.

    `OMPHALOS_CRUNCH_DIR` takes precedence over settings.py. That is what makes a build comparison
    safe: pointing one sweep at a different binary otherwise means editing the installed settings.py,
    which is a global mutation that an interrupted run would leave behind.

    Read on each call rather than at import, so setting the variable per subprocess works.

    settings.py is written by install.sh and is not tracked, so it is absent in a fresh checkout and
    in CI.
    """
    override = os.environ.get('OMPHALOS_CRUNCH_DIR')

    if override:
        return override

    try:
        from omphalos.settings import crunch_dir
    except ImportError:
        return None

    return crunch_dir


# Kept as the old private name so existing callers are unaffected.
_configured_binary = binary


def deck_keywords(runtime_contents):
    """Return the auxiliary-database keywords a deck's RUNTIME block actually uses.

    Args:
        runtime_contents: The contents dict of the deck's RUNTIME keyword block.

    Returns:
        A dict of role ('aqueous' or 'catabolic') to the keyword the deck spells it with.
    """
    found = {}

    for generation in KEYWORD_GENERATIONS:
        for role, keyword in generation.items():
            if keyword in runtime_contents:
                found[role] = keyword

    return found


def check_deck(runtime_contents, binary=None):
    """Fail if a deck names its auxiliary databases in a spelling this CrunchTope cannot read.

    Args:
        runtime_contents: The contents dict of the deck's RUNTIME keyword block.
        binary: Path to the executable. Defaults to the one settings.py records.

    Raises:
        ValueError: If the deck uses the other generation's spelling, naming the substitution
            required. Failing loudly is right here: the alternative is a simulation that runs to
            completion without the database it was supposed to read.
    """
    identified = identify_build(binary)
    supported = identified or DEFAULT_KEYWORDS
    used = deck_keywords(runtime_contents)

    if identified is None:
        if used:
            # Some builds read their aqueous kinetics by another route and recognise no such
            # keyword at all, so the deck's is ignored and the run proceeds without it.
            warnings.warn(
                f'Could not tell which auxiliary-database keywords this CrunchTope build reads, so '
                f'the CrunchTope 1.x spellings are assumed. The deck uses '
                f'{sorted(used.values())}. If the build recognises neither, it will ignore them '
                f'and run without those databases. Set crunch_keywords in omphalos/settings.py to '
                f'say which it reads.'
            )

        return supported

    wrong = {
        role: keyword for role, keyword in used.items() if keyword != supported[role]
    }

    if not wrong:
        return supported

    substitutions = ', '.join(
        f"this binary wants '{supported[role]}', the deck says '{keyword}'"
        for role, keyword in sorted(wrong.items())
    )

    raise ValueError(
        f'CrunchTope keyword mismatch: {substitutions}. CrunchTope ignores a keyword it does not '
        f'recognise and carries on with its default, so the run would finish without the database '
        f'it names. Edit the deck to use the spelling this build understands.'
    )
