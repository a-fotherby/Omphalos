#!/usr/bin/env python3
"""Keep the README's test counts in step with the test suite.

The README quotes the size of the test suite in two places: the badge at the top and the prose above
the Test Categories table. Both are hand-maintained numbers, so they drift the moment anyone adds a
test. This script rewrites them from the number of tests pytest actually collects.

Run it directly to update the README, or let the pre-commit hook run it with --pre-commit, which only
rewrites the file when doing so cannot disturb unstaged work.

It also reports test modules the Test Categories table does not mention. That check is a warning
only: adding a row means writing a description, which is a job for a human.
"""

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
README = REPO / 'README.md'
TESTS = REPO / 'tests'

# The two places the suite size is quoted. Group 2 is the number in each case.
BADGE = re.compile(r'(tests-)(\d+)(%20passed)')
PROSE = re.compile(r'(test suite with \*\*)(\d+)( tests\*\*)')
# Tolerate ANSI colour codes: pytest colourises even into a pipe in some environments, which
# defeated a plain start-of-line match and left the counts silently unchanged.
COLLECTED = re.compile(r'^(?:\x1b\[[\d;]*m)*(\d+) tests? collected', re.MULTILINE)


def declared_conda_env():
    """Return the conda environment name the project declares in requirements.yml, if any."""
    requirements = REPO / 'requirements.yml'
    if not requirements.exists():
        return None
    match = re.search(r'^name:\s*(\S+)', requirements.read_text(), re.MULTILINE)
    return match.group(1) if match else None


def collect_commands():
    """Candidate pytest invocations, cheapest and most likely to work first.

    A hook runs with whatever environment the commit was made from, which for a GUI git client or a
    shell with no environment active may be a bare interpreter without pytest. So fall back through
    the active conda environment, a pytest on PATH, and finally the environment the project itself
    declares in requirements.yml.
    """
    args = ['--collect-only', '-q', '--color=no', '-o', 'addopts=', '-p', 'no:cacheprovider']
    commands = [[sys.executable, '-m', 'pytest'] + args]

    conda_prefix = os.environ.get('CONDA_PREFIX')
    if conda_prefix:
        commands.append([str(pathlib.Path(conda_prefix) / 'bin' / 'python'), '-m', 'pytest'] + args)

    pytest_exe = shutil.which('pytest')
    if pytest_exe:
        commands.append([pytest_exe] + args)

    env_name = declared_conda_env()
    if env_name:
        for conda in conda_executables():
            commands.append([conda, 'run', '-n', env_name, 'python', '-m', 'pytest'] + args)

    return commands


def conda_executables():
    """Ways to reach conda, in order of confidence.

    A GUI git client may run hooks with a minimal PATH that has no conda on it at all, hence the
    look in the usual install locations as a last resort.
    """
    candidates = [os.environ.get('CONDA_EXE'), shutil.which('conda')]
    home = pathlib.Path.home()
    candidates += [str(home / name / 'bin' / 'conda') for name in ('miniconda3', 'anaconda3', 'miniforge3')]

    seen = []
    for candidate in candidates:
        if candidate and candidate not in seen and pathlib.Path(candidate).exists():
            seen.append(candidate)
    return seen


def collected_test_count():
    """Return the number of tests pytest collects, or None if pytest could not be run.

    addopts is cleared because the project sets -v, which turns collection into a tree rather than
    the one-line summary this parses.
    """
    for command in collect_commands():
        try:
            result = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
        except OSError:
            continue
        match = COLLECTED.search(result.stdout)
        if match:
            return int(match.group(1))
    return None


def unlisted_modules():
    """Return (on disk but unlisted, listed but absent) for the Test Categories table."""
    text = README.read_text()
    if '### Test Categories' not in text:
        return [], []
    # Split on a horizontal rule, not a bare '---', so the table's own separator row is kept.
    section = text.split('### Test Categories')[-1].split('\n---\n')[0]
    listed = set(re.findall(r'`(tests/[\w/]+\.py)`', section))
    on_disk = {path.relative_to(REPO).as_posix() for path in TESTS.rglob('test_*.py')}
    return sorted(on_disk - listed), sorted(listed - on_disk)


def has_unstaged_changes(path):
    """True if the working copy of path differs from the index."""
    result = subprocess.run(['git', 'diff', '--quiet', '--', str(path)], cwd=REPO)
    return result.returncode != 0


def update_counts(pre_commit):
    """Rewrite the README's test counts. Returns True if the file was changed."""
    original = README.read_text()
    updated = original
    changes = []

    count = collected_test_count()
    if count is None:
        print('update_test_counts: could not collect tests (is pytest installed?); README left alone')
        return False

    for label, pattern in (('badge', BADGE), ('prose', PROSE)):
        match = pattern.search(updated)
        if match is None:
            print(f'update_test_counts: no test count {label} found in README.md')
            continue
        if int(match.group(2)) != count:
            changes.append(f'{label} {match.group(2)} -> {count}')
            updated = pattern.sub(rf'\g<1>{count}\g<3>', updated)

    if not changes:
        return False

    summary = ', '.join(changes)
    if pre_commit and has_unstaged_changes(README):
        print(f'update_test_counts: README.md test count is stale ({summary}) but has unstaged '
              f'changes, so it has been left alone. Run .githooks/update_test_counts.py yourself.')
        return False

    README.write_text(updated)
    print(f'update_test_counts: README.md test count updated ({summary}).')
    if pre_commit:
        subprocess.run(['git', 'add', '--', str(README)], cwd=REPO, check=True)
        print('update_test_counts: staged README.md as part of this commit.')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--pre-commit', action='store_true',
                        help='hook mode: skip the README if it has unstaged changes, and stage it if rewritten')
    args = parser.parse_args()

    update_counts(args.pre_commit)

    missing, phantom = unlisted_modules()
    if missing:
        print('update_test_counts: WARNING - test modules missing from the Test Categories table:')
        for module in missing:
            print(f'    {module}')
    if phantom:
        print('update_test_counts: WARNING - Test Categories table lists modules that do not exist:')
        for module in phantom:
            print(f'    {module}')

    # Never block a commit: a stale count or an unlisted module is not worth refusing work over.
    return 0


if __name__ == '__main__':
    sys.exit(main())
