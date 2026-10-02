"""Runs after test_driver.py (alphabetical): the recorder fixture must not
leak its forced backend or disabled safety into later modules."""
import importlib

from mcp_vroid.driver.backends import select_name


def test_driver_modules_are_clean():
    W = importlib.import_module("mcp_vroid.driver.window")
    I = importlib.import_module("mcp_vroid.driver.input")
    assert W.BACKEND == select_name()
    assert I._SAFE is True
