"""Compatibility test entry point backed by maintained, portable Python source.

Every historical test function exists in test_backend.py. Re-export that source
instead of executing interpreter-specific cached bytecode, which cannot run in
our Python 3.12 container and can silently exercise obsolete contracts.
"""
from test_backend import *  # noqa: F403
