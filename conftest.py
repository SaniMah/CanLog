"""Pytest configuration: put the project root on sys.path so tests can do
`from src... import ...` regardless of where pytest is invoked.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
