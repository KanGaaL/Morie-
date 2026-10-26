"""Runs a customer's Python code in a locked-down child process."""
import os, sys, signal, subprocess, tempfile, resource

TIMEOUT = 5            # seconds of real time
MAX_OUT = 10_000       # bytes of output returned
NOBODY = 65534


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 2**20, 256 * 2**20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2**20, 2**20))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if os.geteuid() == 0:                       # drop to an unprivileged user
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
        os.setgid(NOBODY)
        os.setuid(NOBODY)


def run_python(code: str) -> str:
    # Safe by default: only run customer code as root-in-a-container (so it can be
    # dropped to 'nobody' and cannot read MORIE's secrets). ALLOW_UNSAFE=1 is for local tests only.
    if os.geteuid() != 0 and os.environ.get("ALLOW_UNSAFE") != "1":
        return "Runner is not configured safely (must run inside the Docker container)."
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "main.py")
        with open(path, "w") as f:
            f.write(code)
        if os.geteuid() == 0:
            os.chown(d, NOBODY, NOBODY)
            os.chown(path, NOBODY, NOBODY)
        proc = subprocess.Popen(
            [sys.executable, "-I", path], cwd=d, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": d, "PYTHONIOENCODING": "utf-8"},
            preexec_fn=_limits, start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=TIMEOUT)
            note = ""
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, _ = proc.communicate()
            note = f"\n[stopped: took longer than {TIMEOUT} seconds]"
        text = out[:MAX_OUT].decode("utf-8", "replace")
        if len(out) > MAX_OUT:
            text += "\n[output cut short]"
        return (text + note) or "(no output)"
