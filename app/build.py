"""What code this process is running.

Read from a file the unit stamps at start, not from git at request time.
Shelling out to `git` would make the API depend on a `.git` directory beside
it and on git being installed, to answer a question that cannot change while
the process is alive.

**A missing file is not an error.** Running uvicorn by hand in development
produces no stamp, and the honest answer there is that the build is unknown.
A version banner must never be the reason a service will not start.
"""

from app.config import settings

UNKNOWN = "unknown"


def read_build_info(path: str | None = None) -> dict[str, str]:
    """Parses the `key=value` file the unit writes before ExecStart.

    Deliberately not `configparser` or JSON: the writer is one `printf` in a
    systemd unit, and a format that a shell can emit correctly without
    quoting rules is the one least likely to be the thing that breaks.
    """
    target = path or settings.build_info_path
    info = {"sha": UNKNOWN, "branch": UNKNOWN}

    try:
        with open(target, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return info

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        # Only the two keys we know. An unrecognised line is ignored rather
        # than surfaced, so the file can grow without this needing to change.
        if key in info and value:
            info[key] = value

    return info


# Read once, at import. The answer cannot change while the process runs, and
# the file is written immediately before this process starts.
#
# Referenced through the module (`build.BUILD_INFO`) rather than imported by
# value, so a test can substitute it.
BUILD_INFO = read_build_info()
