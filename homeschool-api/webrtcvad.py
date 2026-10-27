"""MIT-licensed compatibility wrapper for the installed webrtcvad C extension.

Adapted from John Wiseman's py-webrtcvad/webrtcvad.py (MIT license),
https://github.com/wiseman/py-webrtcvad . See third_party/webrtcvad_LICENSE.

The upstream 2.0.10 wrapper uses pkg_resources only to read the package
version; setuptools >=82 removed that API. Keep the *webrtcvad* distribution
and its compiled _webrtcvad extension as Resemblyzer declares them. This
in-tree wrapper is deliberately the only import-path override: do NOT also
install webrtcvad-wheels (which owns the same module).
"""
from importlib.metadata import version as distribution_version

import _webrtcvad

__author__ = "John Wiseman jjwiseman@gmail.com"
__copyright__ = "Copyright (C) 2016 John Wiseman"
__license__ = "MIT"
__version__ = distribution_version("webrtcvad")


class Vad:
    def __init__(self, mode=None):
        self._vad = _webrtcvad.create()
        _webrtcvad.init(self._vad)
        if mode is not None:
            self.set_mode(mode)

    def set_mode(self, mode):
        _webrtcvad.set_mode(self._vad, mode)

    def is_speech(self, buf, sample_rate, length=None):
        length = length or int(len(buf) / 2)
        if length * 2 > len(buf):
            raise IndexError(
                "buffer has %s frames, but length argument was %s"
                % (int(len(buf) / 2.0), length)
            )
        return _webrtcvad.process(self._vad, sample_rate, buf, length)


def valid_rate_and_frame_length(rate, frame_length):
    return _webrtcvad.valid_rate_and_frame_length(rate, frame_length)
