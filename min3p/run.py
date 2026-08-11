"""Methods for invoking MIN3P on an InputFile object.

Unlike CrunchTope (which is driven interactively via ``pexpect``), MIN3P reads
its run name from ``root.dat`` in the working directory and runs to completion,
so a plain :func:`subprocess.run` suffices. Error detection is by return code
plus a scan of stdout for known failure markers.
"""

import shutil
import subprocess
from pathlib import Path

# MIN3P executable path. Resolution order:
#   1. per-run override via the config key `min3p_binary` (see run/main callers),
#   2. install-configured `min3p/settings.py` (git-ignored, written by install.sh
#      or copied from settings_default.py),
#   3. the built-in default below, so imports and out-of-the-box runs still work.
_DEFAULT_MIN3P_BINARY = '/path/to/MIN3P/MacOS/MIN3P-HPC-X64-V2.3.7.850-MacOS-x64'
try:
    from min3p.settings import min3p_binary as MIN3P_BINARY
except ImportError:
    MIN3P_BINARY = _DEFAULT_MIN3P_BINARY

# A completed MIN3P run prints this banner to stdout on success (verified with
# v2.4.0.852). Its ABSENCE is the primary failure signal -- more reliable than
# scanning for the word "error", which appears innocuously in normal output
# (e.g. "error tolerance").
MIN3P_SUCCESS_MARKER = 'normal exit'

# Additional Fortran/OS crash markers, scanned only for diagnostic reporting.
MIN3P_ERROR_MARKERS = (
    'forrtl:',            # Fortran runtime error prefix
    'segmentation fault',
)

# InputFile.error_code values.
SUCCESS = 0
TIMEOUT = 1
SOLVER_ERROR = 2


def _run_name(input_file):
    """Return the MIN3P run name (input file stem) for ``input_file``."""
    return Path(input_file.path).stem


def _write_root(tmp_path, run_name):
    """Write ``root.dat`` naming the run, as MIN3P expects.

    Args:
        tmp_path: Working directory (Path).
        run_name: The input-file stem MIN3P should use as the run name.
    """
    (tmp_path / 'root.dat').write_text(run_name + '\n')


def run_dataset(file_dict, tmp_dir, timeout, binary=MIN3P_BINARY):
    """Run every InputFile in ``file_dict`` through MIN3P sequentially.

    Args:
        file_dict: Dict of ``{file_num: InputFile}``.
        tmp_dir: Working directory for input/output files.
        timeout: Per-simulation timeout in seconds.
        binary: Path to the MIN3P executable.

    Returns:
        The updated ``file_dict`` (each InputFile carries its results/error code).
    """
    for file_num, entry in enumerate(file_dict):
        file_dict[entry] = input_file(file_dict[entry], file_num, tmp_dir, timeout, binary=binary)
    return file_dict


def input_file(input_file, file_num, tmp_dir, timeout, binary=MIN3P_BINARY):
    """Write and run a single InputFile through MIN3P.

    Args:
        input_file: The InputFile to run.
        file_num: File number (for logging).
        tmp_dir: Working directory.
        timeout: Timeout in seconds.
        binary: Path to the MIN3P executable.

    Returns:
        The InputFile, updated with results and error code.
    """
    tmp_path = Path(tmp_dir).resolve()
    tmp_path.mkdir(parents=True, exist_ok=True)

    # Write the input file into the working directory under its stem name.
    run_name = _run_name(input_file)
    input_file.path = tmp_path / f'{run_name}.dat'
    input_file.print()
    _write_root(tmp_path, run_name)

    min3p(input_file, file_num, timeout, tmp_path, binary=binary)
    return input_file


def min3p(input_file, file_num, timeout, tmp_dir, binary=MIN3P_BINARY):
    """Execute the MIN3P binary in ``tmp_dir`` and collect results.

    Args:
        input_file: InputFile to run (already written to disk).
        file_num: File number (for logging).
        timeout: Timeout in seconds.
        tmp_dir: Working directory (Path).
        binary: Path to the MIN3P executable.

    Returns:
        The InputFile with :attr:`results` populated on success, or an
        :attr:`error_code` set on failure.
    """
    try:
        result = subprocess.run(
            [str(binary)],
            cwd=str(tmp_dir),
            timeout=timeout,
            capture_output=True,
            text=True,
            errors='replace',
        )
    except subprocess.TimeoutExpired:
        print(f'File {file_num} timed out after {timeout}s.')
        input_file.error_code = TIMEOUT
        return input_file

    stdout = result.stdout or ''
    lowered = stdout.lower()
    succeeded = result.returncode == 0 and MIN3P_SUCCESS_MARKER in lowered
    crash_marker = next((m for m in MIN3P_ERROR_MARKERS if m in lowered), None)

    if not succeeded:
        if crash_marker is not None:
            reason = f'crash marker "{crash_marker}"'
        elif result.returncode != 0:
            reason = f'return code {result.returncode}'
        else:
            reason = f'"{MIN3P_SUCCESS_MARKER}" banner absent from output'
        print(f'Error in file {file_num}: {reason}.')
        # Surface the tail of stdout to aid debugging.
        tail = '\n'.join(stdout.splitlines()[-15:])
        if tail:
            print(f'--- MIN3P stdout (tail) ---\n{tail}\n---------------------------')
        input_file.error_code = SOLVER_ERROR
        return input_file

    input_file.get_results(str(tmp_dir))
    print(f'File {file_num} outputs recorded.')
    return input_file


# Restart state files written by MIN3P (see User Manual DB1 'restart').
_RESTART_FILES = ('restart.tmp1', 'restart.tmp2', 'restart.dat',
                  'restart.append.tmp1', 'restart.append.tmp2')


def _clean_restart_files(tmp_path):
    """Remove stale MIN3P restart artifacts before a fresh chain (stage 0)."""
    for name in _RESTART_FILES:
        p = tmp_path / name
        if p.is_file():
            p.unlink()


def _prepare_restart_dat(tmp_path):
    """Copy the latest ``restart.tmp{1,2}`` to ``restart.dat`` for a restart.

    MIN3P writes two rolling state files (at Nt and 2*Nt steps); the one with
    the greater recorded solution time (first token of its first line) is the
    most advanced and becomes ``restart.dat``.

    Raises:
        FileNotFoundError: If neither restart temp file is present.
    """
    candidates = []
    for name in ('restart.tmp1', 'restart.tmp2'):
        p = tmp_path / name
        if not p.is_file():
            continue
        try:
            first = p.read_text(errors='replace').splitlines()[0].split()[0]
            t = float(first.replace('D', 'E').replace('d', 'e'))
        except (IndexError, ValueError):
            t = -1.0
        candidates.append((t, p))
    if not candidates:
        raise FileNotFoundError(
            f'No restart.tmp1/tmp2 in {tmp_path}; cannot build restart.dat for the next stage.'
        )
    candidates.sort(key=lambda c: c[0])
    shutil.copyfile(candidates[-1][1], tmp_path / 'restart.dat')


def run_staged(stages_dict, run_num, tmp_dir, timeout, binary=MIN3P_BINARY):
    """Run a restart chain for one run: each stage continues the previous.

    All stages execute in the SAME working directory under the same run name,
    so MIN3P's ``restart.tmp`` state files carry over. Between stages the latest
    temp file is promoted to ``restart.dat`` (which the stage's ``'restart'``
    directive then consumes). Stale restart artifacts are cleared before stage 0
    so sequential runs in a shared directory don't cross-contaminate.

    Args:
        stages_dict: ``{stage_num: InputFile}`` for this run.
        run_num: The run (file) number.
        tmp_dir: Working directory.
        timeout: Per-stage timeout in seconds.
        binary: MIN3P executable path.

    Returns:
        The final-stage InputFile (carrying the appended results), with
        ``file_num`` preserved for dataset assembly.
    """
    tmp_path = Path(tmp_dir).resolve()
    tmp_path.mkdir(parents=True, exist_ok=True)
    num_stages = len(stages_dict)
    run_name = _run_name(stages_dict[0])

    for stage in range(num_stages):
        f = stages_dict[stage]
        f.path = tmp_path / f'{run_name}.dat'
        f.print()
        _write_root(tmp_path, run_name)

        if stage == 0:
            _clean_restart_files(tmp_path)
        else:
            _prepare_restart_dat(tmp_path)

        print(f'Running run {run_num}, stage {stage}')
        min3p(f, f'{run_num}.{stage}', timeout, tmp_path, binary=binary)

        if f.error_code != 0:
            print(f'Run {run_num} stage {stage} failed (error_code={f.error_code}); stopping chain.')
            break

    # The last successfully-run stage holds the cumulative (appended) results.
    last = max(s for s in stages_dict if stages_dict[s].results or s == 0)
    stages_dict[last].file_num = run_num
    return stages_dict[last]
