"""
Loads all tests automatically from tests module

Recurses into tests directory and assumes all .py extensions to be
test files, except ones that start with _
"""
import os


def load_tests(loader, standard_tests, pattern):
    """unittest calls function to load tests from package"""
    pattern = "[!_]*.py"
    this_dir = os.path.dirname(__file__)
    package_tests = loader.discover(start_dir=this_dir, pattern=pattern)
    standard_tests.addTests(package_tests)
    return standard_tests
