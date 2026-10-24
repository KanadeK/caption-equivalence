"""Run real example acceptance checks from a fresh installed wheel."""

import json
import os
import shutil
import subprocess
import tempfile
import venv
from pathlib import Path

root = Path(__file__).resolve().parents[1]
wheels = list((root / "dist").glob("*.whl"))
if len(wheels) != 1:
    raise SystemExit("Build exactly one wheel first.")
with tempfile.TemporaryDirectory(prefix="caption-equivalence-smoke-") as directory:
    work = Path(directory)
    venv.EnvBuilder(with_pip=True).create(work / "env")
    binary = work / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [str(binary), "-m", "pip", "install", str(wheels[0])], cwd=work, env=env, check=True
    )
    shutil.copytree(root / "examples", work / "examples")
    for candidate, code, duration in [
        ("resegmented.vtt", 0, 0),
        ("missing-tail.vtt", 1, 1000),
        ("empty.vtt", 1, 3000),
    ]:
        run = subprocess.run(
            [
                str(binary),
                "-m",
                "caption_equivalence",
                "examples/reference.srt",
                f"examples/{candidate}",
                "--json",
            ],
            cwd=work,
            env=env,
            text=True,
            capture_output=True,
        )
        if run.returncode != code:
            raise SystemExit(f"Unexpected smoke exit {run.returncode}: {run.stderr}")
        if json.loads(run.stdout)["different_ms"] != duration:
            raise SystemExit("Incorrect duration in installed-wheel smoke receipt")
    subprocess.run(
        [str(binary), "-m", "pip", "uninstall", "-y", "caption-equivalence"],
        cwd=work,
        env=env,
        check=True,
    )
print("Isolated install, equivalent/missing/empty fixtures and uninstall: PASS")
