import os
import sys

# Ensure the project root (parent of tests/) is importable so that
# `import island_pill` works when pytest is invoked from any directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
