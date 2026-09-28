"""Run the existing recovered backend tests without overwriting their bytecode.

The original test source is absent from this workspace. Its pytest-rewritten
Python 3.14 artifact is preserved and executed unchanged.
"""
import marshal
from pathlib import Path

_cache = Path(__file__).parent / '__pycache__' / 'test_backend.cpython-314-pytest-9.0.3.pyc'
exec(marshal.loads(_cache.read_bytes()[16:]), globals())
