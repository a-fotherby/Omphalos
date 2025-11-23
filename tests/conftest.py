"""Pytest configuration and shared fixtures for Omphalos tests."""

import os
import sys
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# Path Fixtures
# ============================================================================

@pytest.fixture
def project_root():
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture
def test_data_dir():
    """Return the test data directory."""
    return PROJECT_ROOT / "tests"


@pytest.fixture
def omphalos_test_dir(test_data_dir):
    """Return the omphalos test data directory."""
    return test_data_dir / "omphalos_test"


@pytest.fixture
def rhea_test_dir(test_data_dir):
    """Return the rhea test data directory."""
    return test_data_dir / "rhea_test"


@pytest.fixture
def pflotran_test_dir(test_data_dir):
    """Return the pflotran test data directory."""
    return test_data_dir / "pflotran"


# ============================================================================
# Configuration Fixtures
# ============================================================================

@pytest.fixture
def sample_config(omphalos_test_dir):
    """Load a sample configuration file."""
    import yaml
    config_path = omphalos_test_dir / "sukinda_cr.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def minimal_config():
    """Return a minimal configuration dictionary for testing."""
    return {
        'template': 'test_template.in',
        'database': 'test.dbs',
        'aqueous_database': None,
        'catabolic_pathways': None,
        'restart_file': '',
        'timeout': 60,
        'conditions': ['initial', 'boundary'],
        'number_of_files': 5,
        'nodes': 2,
    }


@pytest.fixture
def config_with_concentrations(minimal_config):
    """Return a config with concentration modifications."""
    minimal_config['concentrations'] = {
        'boundary': {
            'SO4--': ['linspace', [1, 30]],
            'Fe++': ['constant', 1e-6],
        }
    }
    return minimal_config


# ============================================================================
# KeywordBlock Fixtures
# ============================================================================

@pytest.fixture
def keyword_block():
    """Create a sample KeywordBlock for testing."""
    from core.keyword_block import KeywordBlock
    block = KeywordBlock('RUNTIME')
    block.contents = {
        'time_units': ['years'],
        'timestep_max': ['0.01'],
        'timestep_init': ['1.e-10'],
        'time_tolerance': ['0.001'],
        'correction_max': ['2.0'],
        'debye-huckel': ['true'],
        'database': ['SukindaCr53.dbs'],
    }
    return block


@pytest.fixture
def condition_block():
    """Create a sample ConditionBlock for testing."""
    from core.keyword_block import ConditionBlock
    block = ConditionBlock()
    block.concentrations = {
        'SO4--': ['1.0', 'mM'],
        'Fe++': ['1e-6', 'mol/L'],
        'H+': ['7.0', 'pH'],
    }
    block.mineral_volumes = {
        'Calcite': ['0.01', '1.0'],
        'Quartz': ['0.05', '0.1'],
    }
    block.parameters = {
        'temperature': ['25.0'],
    }
    block.gases = {}
    block.region = [[1, 10], [1, 1], [1, 1]]
    return block


# ============================================================================
# Template/InputFile Fixtures
# ============================================================================

@pytest.fixture
def sample_template(omphalos_test_dir, sample_config):
    """Create a Template object from test data."""
    import os
    original_dir = os.getcwd()
    os.chdir(omphalos_test_dir)
    try:
        from omphalos.template import Template
        # Suppress output during template creation
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            template = Template(sample_config)
        return template
    finally:
        os.chdir(original_dir)


# ============================================================================
# Temporary Directory Fixtures
# ============================================================================

@pytest.fixture
def temp_dir(tmp_path):
    """Create a temporary directory for test outputs."""
    return tmp_path


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create a temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


# ============================================================================
# Mock Data Fixtures
# ============================================================================

@pytest.fixture
def mock_raw_file_dict():
    """Return a mock raw file dictionary (line_num -> line content)."""
    return {
        0: 'TITLE',
        1: 'Test input file',
        2: 'END',
        3: '',
        4: 'RUNTIME',
        5: 'time_units  years',
        6: 'timestep_max  0.01',
        7: 'END',
        8: '',
        9: 'CONDITION initial',
        10: 'temperature 25.0',
        11: 'SO4--  1.0  mM',
        12: 'END',
    }


@pytest.fixture
def mock_tecplot_content():
    """Return mock TecPlot output content."""
    return '''TITLE = "Test Output"
VARIABLES = "X" "Y" "Z" "SO4--" "Fe++"
ZONE T="zone1"
0.5 0.5 0.5 1.0 1e-6
1.5 0.5 0.5 2.0 2e-6
2.5 0.5 0.5 3.0 3e-6
'''


# ============================================================================
# Utility Functions
# ============================================================================

@pytest.fixture
def assert_array_close():
    """Return a function to assert arrays are close."""
    import numpy as np
    def _assert_close(a, b, rtol=1e-5, atol=1e-8):
        np.testing.assert_allclose(a, b, rtol=rtol, atol=atol)
    return _assert_close
