"""Load an exact compiled KNEURA module while source recovery is pending."""
from importlib.machinery import SourcelessFileLoader
from pathlib import Path
import sys

def load_compiled(module_name: str, filename: str) -> None:
    path = Path(__file__).with_name('__pycache__') / filename
    if module_name == 'backend.app':
        path = Path(__file__).parents[1] / '.kneura' / 'recovery' / 'app-original.cpython-314.pyc'
    loader = SourcelessFileLoader(module_name, str(path))
    loader.exec_module(sys.modules[module_name])
