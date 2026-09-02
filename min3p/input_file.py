"""Top-level object representing a single MIN3P ``.dat`` input file."""

import glob
import re
from pathlib import Path

import pandas as pd
import xarray as xr

from min3p import file_methods as fm


class InputFile:
    """A single MIN3P input file: an ordered sequence of blocks and passthrough lines.

    Attributes:
        path: Path the file is/will be written to.
        elements: Ordered list of file elements. Each element is either a
            ``keyword_block.Line`` (comment/blank passthrough between blocks) or
            a ``keyword_block.Min3pBlock``.
        keyword_blocks: ``dict`` mapping normalised block name -> ``Min3pBlock``
            (the same objects referenced in ``elements``). Duplicate block names
            are disambiguated as ``name#2``, ``name#3`` ...
        newline: The line terminator to write (``'\\r\\n'`` or ``'\\n'``),
            matching what was read.
        results: Dict of parsed output datasets, keyed by category.
        error_code: 0 = success, 1 = timeout, 2 = solver/convergence error.
        file_num: Index within a generated dataset.
        later_inputs: Restart-chain inputs (unused for MIN3P at present).
    """

    def __init__(self, path, elements, keyword_blocks, newline='\r\n'):
        self.path = path
        self.elements = elements
        self.keyword_blocks = keyword_blocks
        self.newline = newline
        self.results = dict()
        self.error_code = 0
        self.file_num = 0
        self.stage_num = None  # set for restart-chain stages
        self.later_inputs = {}

    def print(self):
        """Write the input file to :attr:`path` in MIN3P ``.dat`` format."""
        from min3p.keyword_block import Min3pBlock

        lines = []
        for element in self.elements:
            if isinstance(element, Min3pBlock):
                lines.extend(element.render())
            else:  # a passthrough Line
                lines.append(element.render())

        with open(self.path, 'w', newline='') as f:
            f.write(''.join(line + self.newline for line in lines))

    def _discover_time_indices(self, path, run_name, category):
        """Return the sorted list of timestep indices available for a category.

        Args:
            path: Output directory.
            run_name: MIN3P run name.
            category: Output extension without the dot.

        Returns:
            Sorted list of integer indices ``N`` from ``{run_name}_{N}.{ext}``.
        """
        pattern = str(Path(path) / f'{run_name}_*.{category}')
        indices = []
        matcher = re.compile(rf'{re.escape(run_name)}_(\d+)\.{re.escape(category)}$')
        for f in glob.glob(pattern):
            m = matcher.search(Path(f).name)
            if m:
                indices.append(int(m.group(1)))
        return sorted(indices)

    def get_results(self, tmp_dir):
        """Parse MIN3P output files in ``tmp_dir`` and store them in :attr:`results`.

        Each spatial-output category is concatenated over the available timestep
        indices along an ``output`` dimension (integer output index; MIN3P does
        not record a uniform time value across all output categories).

        Args:
            tmp_dir: Directory containing the MIN3P output files.
        """
        run_name = fm._read_run_name(tmp_dir)
        if run_name is None:
            print(f'WARNING: no root.dat in {tmp_dir}; cannot locate outputs.')
            return

        for category in fm.data_cats(tmp_dir, run_name=run_name):
            indices = self._discover_time_indices(tmp_dir, run_name, category)
            if not indices:
                continue

            print(f'Parsing {category} ({len(indices)} output(s))')
            ds_list = []
            parsed_indices = []
            for i in indices:
                try:
                    ds_list.append(fm.parse_output(tmp_dir, category, i, run_name=run_name))
                    parsed_indices.append(i)
                except Exception as exc:  # noqa: BLE001 - report and skip bad outputs
                    print(f'WARNING: output {run_name}_{i}.{category} not parsed. ({exc})')

            if not ds_list:
                continue

            dim = pd.Index(parsed_indices, name='output')
            self.results[category] = xr.concat(ds_list, dim=dim, join='outer')
