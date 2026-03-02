"""
Allow the package to be run directly:
    python -m robocam_suite
    python -m robocam_suite --simulate
"""
# Delegate entirely to main.py so argument handling lives in one place.
import sys
import os

# Ensure the repo root is on the path when invoked as a module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import main  # noqa: E402

if __name__ == "__main__":
    main()
