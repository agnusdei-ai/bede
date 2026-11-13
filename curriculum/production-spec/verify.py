"""Run the offline contract suite with enforced Linux process limits."""
import resource
import signal
import unittest


def main():
    # Apply after the host's Python launcher starts, before importing the checks.
    # Some wrapped launchers reserve more virtual space than the Python process.
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
    signal.alarm(30)
    from pathlib import Path
    from contract import check
    from example import example

    suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent), "test_contract.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    output_hash = check(example(), Path(__file__).parent / "fixtures")
    print(f"PASS fixture/export sha256={output_hash}; no approval or activation")


if __name__ == "__main__":
    main()
