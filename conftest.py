"""Make the repo root importable so tests can ``from core import ...`` /
``from seed import ...`` regardless of how pytest is invoked. (Also configured
via ``pythonpath`` in pyproject.toml; this is a belt-and-suspenders fallback.)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
