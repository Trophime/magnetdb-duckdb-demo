"""
record_io.py
============
Retry record-file reads through the rclone mount on transient I/O errors.

The records tree is an rclone FUSE mount: when the network or the mount
drops, ``stat``/``open``/``read`` fail with ``EIO`` (or ``ENOTCONN`` once
the mount is gone). :func:`load_with_retry` retries a load after waiting;
the statistics scripts stop after :data:`MAX_CONSECUTIVE_IO_FAILURES` files
in a row still fail, as the mount is then most likely down.
"""

import errno
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

IO_RETRY_WAITS = (10, 60, 300)  # s — waits before the 2nd, 3rd and 4th attempt
MAX_CONSECUTIVE_IO_FAILURES = 3  # files in a row still failing → mount down

_IO_ERRNOS = {errno.EIO, errno.ENOTCONN, errno.ETIMEDOUT, errno.ESTALE}


def is_io_error(exc: BaseException) -> bool:
    """Tell whether *exc* is an I/O error from the records mount.

    Parameters
    ----------
    exc : BaseException
        Exception raised while reading a record file.

    Returns
    -------
    bool
        ``True`` for an :class:`OSError` with errno ``EIO``, ``ENOTCONN``,
        ``ETIMEDOUT`` or ``ESTALE``; ``False`` otherwise (e.g. a missing or
        unreadable-by-permission file, or a parse error).
    """
    return isinstance(exc, OSError) and exc.errno in _IO_ERRNOS


def load_with_retry(
    load: Callable[[Path], T],
    path: Path,
    waits: tuple[float, ...] = IO_RETRY_WAITS,
    verbose: bool = True,
) -> T:
    """Call ``load(path)``, retrying after each wait on an I/O error.

    Parameters
    ----------
    load : callable
        Loader taking the record path, e.g. ``load_file``.
    path : Path
        Record file to load.
    waits : tuple of float, optional
        Seconds to wait before each retry [s]; ``len(waits) + 1`` attempts
        in all. Defaults to :data:`IO_RETRY_WAITS`.
    verbose : bool, optional
        Print a ``[IOERR]`` line before each wait.

    Returns
    -------
    object
        Whatever *load* returns.

    Raises
    ------
    OSError
        The last I/O error, when every attempt failed; any other exception
        from *load* immediately, without retrying.
    """
    for wait in waits:
        try:
            return load(path)
        except OSError as exc:
            if not is_io_error(exc):
                raise
            if verbose:
                print(f"  [IOERR] {path.name}: {exc}; retrying in {wait:g} s")
            time.sleep(wait)
    return load(path)
