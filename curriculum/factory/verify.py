"""Bounded offline acceptance suite, including existing authenticated SQLite tests."""
import os
from pathlib import Path
import resource
import signal
import socket
import unittest


def deny_network(*args, **kwargs):
    raise AssertionError("Network is prohibited during factory verification")


def main():
    resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024, 256*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (10*1024*1024, 10*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    signal.alarm(30)
    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    here = Path(__file__).parent
    suite = unittest.defaultTestLoader.discover(str(here), "test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("PASS: 30-second / 256 MiB offline acceptance suite; no human curriculum approval")


if __name__ == "__main__":
    main()
