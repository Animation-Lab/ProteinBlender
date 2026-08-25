"""Client for driving a *live, windowed* Blender over the BlenderMCP socket.

This is the transport for the ``tests/live`` lane. Unlike the rest of the suite,
which runs headless *inside* Blender's Python, this lane runs in ordinary system
Python and talks to a Blender that is already open on the user's desktop, with a
real window, a real 3D viewport, and the *deployed* add-on.

Why that matters: `--background` has no screen, so the headless lane can assert
node topology and Cycles pixel coverage but can never observe the viewport the
user actually looks at. This lane can.

Protocol (see the BlenderMCP add-on, `blender_mcp_addon.py`):
    TCP JSON, default localhost:9876.
    request  -> {"type": <command>, "params": {...}}
    response <- {"status": "success", "result": {...}}
             |  {"status": "error", "message": "..."}
The ``execute_code`` command runs Python in Blender's main thread and returns
whatever the code wrote to stdout. Everything here is built on that: we print a
sentinel-delimited JSON payload and parse it back out, which keeps us immune to
the unrelated `print()` noise the add-on and MolecularNodes emit.

Path translation: the live Blender may be a *Windows* process while the tests
run in WSL, so a repo path like ``/home/u/ProteinBlender`` is meaningless to it.
``remote_repo_path()`` resolves the path Blender should use (via ``wslpath -w``
when applicable), which is what lets the remote side import this repo's existing
``tests/helpers.py`` rather than duplicating it.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = TESTS_DIR.parent

DEFAULT_HOST = os.environ.get("PB_MCP_HOST", "localhost")
DEFAULT_PORT = int(os.environ.get("PB_MCP_PORT", "9876"))

# Sentinels delimiting our JSON payload inside captured stdout. They must not
# occur in ordinary Blender output.
_BEGIN = "<<<PB-LIVE-BEGIN>>>"
_END = "<<<PB-LIVE-END>>>"


class LiveBlenderError(RuntimeError):
    """A command failed inside the live Blender. Carries the remote traceback."""


class LiveBlenderUnavailable(RuntimeError):
    """No live Blender is listening. The lane skips rather than fails."""


def remote_repo_path() -> str:
    """The repo root as the *live Blender process* must spell it.

    On WSL the tests run in Linux while Blender is a Windows process, so the
    Linux path has to become a ``\\\\wsl.localhost\\...`` UNC path. Everywhere
    else the local path is already correct.
    """
    if shutil.which("wslpath"):
        try:
            out = subprocess.run(
                ["wslpath", "-w", str(REPO_ROOT)],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return str(REPO_ROOT)


# ---------------------------------------------------------------------------
# Remote prelude
# ---------------------------------------------------------------------------
#
# Runs once per connection. It puts this repo's ``tests/`` on the live Blender's
# sys.path and imports the *same* helpers module the headless lane uses, so both
# lanes import molecules, build DNA and build membranes through identical public
# operators. Divergence between lanes would defeat the point of having two.

_PRELUDE = r'''
import sys, os, json, traceback
__pb_tests = os.path.join(__PB_REPO__, "tests")
if __pb_tests not in sys.path:
    sys.path.insert(0, __pb_tests)
__pb_live = os.path.join(__pb_tests, "live")
if __pb_live not in sys.path:
    sys.path.insert(0, __pb_live)
import bpy
import helpers as H
import remote as R
'''


class BlenderMCP:
    """A connection to a live Blender. Prefer the ``blender`` fixture."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = 240.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._bootstrapped = False
        self.last_stdout = ""

    # -- raw protocol -------------------------------------------------------

    def _connect(self) -> socket.socket:
        if self._sock is not None:
            return self._sock
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
        except OSError as exc:
            raise LiveBlenderUnavailable(
                f"no BlenderMCP server on {self.host}:{self.port} ({exc}). "
                "Open Blender, then in the 3D view N-panel choose the "
                "'BlenderMCP' tab and press Connect."
            ) from exc
        self._sock = sock
        return sock

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._bootstrapped = False

    def send(self, command: str, params: dict | None = None) -> dict:
        """Send one raw BlenderMCP command and return its ``result``."""
        sock = self._connect()
        payload = json.dumps({"type": command, "params": params or {}})
        try:
            sock.sendall(payload.encode("utf-8"))
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                try:
                    response = json.loads(b"".join(chunks).decode("utf-8"))
                    break
                except json.JSONDecodeError:
                    continue
            else:
                raise LiveBlenderError("connection closed mid-response")
        except socket.timeout as exc:
            self.close()
            raise LiveBlenderError(
                f"live Blender did not answer {command!r} within "
                f"{self.timeout}s. It may be blocked on a modal dialog."
            ) from exc
        except OSError as exc:
            self.close()
            raise LiveBlenderError(f"socket error on {command!r}: {exc}") from exc

        if response.get("status") == "error":
            raise LiveBlenderError(response.get("message", "unknown error"))
        return response.get("result", {})

    def is_alive(self) -> bool:
        try:
            self.send("get_scene_info")
            return True
        except (LiveBlenderUnavailable, LiveBlenderError):
            return False

    # -- code execution -----------------------------------------------------

    def exec_raw(self, code: str) -> str:
        """Run code in Blender; return its captured stdout verbatim."""
        result = self.send("execute_code", {"code": textwrap.dedent(code)})
        return result.get("result", "") or ""

    def _bootstrap(self):
        if self._bootstrapped:
            return
        prelude = _PRELUDE.replace("__PB_REPO__", repr(remote_repo_path()))
        # Drop any copies a previous session left in the live Blender's module
        # cache. Without this the long-lived Blender keeps serving the version
        # of remote.py/helpers.py it first imported, and edits to the harness
        # appear to have no effect - a genuinely confusing failure mode, since
        # the tests change while the code under them does not.
        prelude = prelude.replace(
            "import helpers as H",
            "for __m in ('helpers', 'remote'):\n"
            "    sys.modules.pop(__m, None)\n"
            "import helpers as H",
        )
        # Bootstrap through the raw path: call() itself depends on the prelude.
        probe = prelude + (
            '\nprint("%s" + json.dumps({"ok": True, "value": R.env()}) + "%s")\n'
            % (_BEGIN, _END)
        )
        try:
            out = self.exec_raw(probe)
        except LiveBlenderError as exc:
            raise LiveBlenderError(
                "live Blender could not load the test harness. The most likely "
                "cause is that ProteinBlender is not enabled in that session, "
                f"or the repo is unreachable at {remote_repo_path()!r}.\n{exc}"
            ) from exc
        self._bootstrapped = True
        self.env = self._extract(out)

    def call(self, code: str, **params):
        """Run a remote snippet and return the JSON value it ``return``s.

        ``code`` is the *body of a function*: use ``return`` to send a value
        back. It runs with ``bpy``, ``H`` (this repo's tests/helpers.py) and
        ``R`` (tests/live/remote.py) already imported, plus any keyword
        arguments bound as local names.

            >>> bl.call("return len(bpy.data.objects)")

        A remote exception is re-raised locally as ``LiveBlenderError`` carrying
        the full remote traceback, so a failing test shows where it broke inside
        Blender rather than an opaque protocol error.
        """
        self._bootstrap()
        # The arguments are decoded OUTSIDE __pb_body and only indexed inside
        # it. Decoding them in the body with json.loads used to be enough to
        # break any snippet that carried its own ``import json``: the import
        # makes ``json`` a local for the whole function, so the binding lines
        # above it raised UnboundLocalError before a line of the test ran.
        binding = "\n".join(
            f"{name} = __pb_params[{json.dumps(name)}]" for name in params
        )
        body = textwrap.indent(textwrap.dedent(code).strip("\n"), "    ")
        program = (
            _PRELUDE.replace("__PB_REPO__", repr(remote_repo_path()))
            + f"\n__pb_params = json.loads({json.dumps(json.dumps(params))})\n"
            + "\ndef __pb_body():\n"
            + (textwrap.indent(binding, "    ") + "\n" if binding else "")
            + body
            + "\n    return None\n"
            "try:\n"
            "    __pb_value = __pb_body()\n"
            "    __pb_out = {'ok': True, 'value': __pb_value}\n"
            "except Exception:\n"
            "    __pb_out = {'ok': False, 'traceback': traceback.format_exc()}\n"
            f"print({_BEGIN!r} + json.dumps(__pb_out, default=str) + {_END!r})\n"
        )
        return self._extract(self.exec_raw(program))

    def _extract(self, stdout: str):
        self.last_stdout = stdout
        if _BEGIN not in stdout or _END not in stdout:
            raise LiveBlenderError(
                "no result payload came back from Blender. Raw output:\n"
                + stdout[-4000:]
            )
        blob = stdout.split(_BEGIN, 1)[1].split(_END, 1)[0]
        payload = json.loads(blob)
        if not payload.get("ok"):
            raise LiveBlenderError(
                "exception inside live Blender:\n" + payload.get("traceback", "")
            )
        return payload.get("value")

    # -- viewport observation ----------------------------------------------

    def screenshot(self, path: str | os.PathLike | None = None,
                   max_size: int = 1000) -> bytes:
        """PNG bytes of the literal Blender window area (UI chrome included).

        Transferred as base64 through stdout rather than via the MCP server's
        ``get_viewport_screenshot``, because that command writes the file on the
        *Blender* machine, which on WSL is a different filesystem from the one
        running the tests.
        """
        data = self.call(
            "return R.screenshot_b64(max_size=max_size)", max_size=max_size)
        raw = base64.b64decode(data)
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(raw)
        return raw

    def viewport(self, path: str | os.PathLike | None = None,
                 resolution: int = 480, transparent: bool = True) -> dict:
        """Render the 3D viewport offscreen and return measurements of it.

        This is the lane's core visual assertion. It is an OpenGL render of the
        viewport (so it observes the *viewport* shading path, unlike the
        headless lane's Cycles render), on a transparent film, which makes
        "how much geometry is on screen and where" directly measurable.

        Returns the dict documented in ``remote.viewport_metrics``.
        """
        metrics = self.call(
            "return R.viewport_metrics(resolution=resolution, "
            "transparent=transparent, want_png=want_png)",
            resolution=resolution, transparent=transparent,
            want_png=path is not None,
        )
        png = metrics.pop("png_b64", None)
        if path is not None and png:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(base64.b64decode(png))
            metrics["artifact"] = str(path)
        return metrics
