"""Install the self-contained Codex skill and an isolated Python environment."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, help="Override the Codex skills directory.")
    parser.add_argument("--update", action="store_true", help="Update an existing installation's skill files.")
    parser.add_argument("--skip-deps", action="store_true", help="Copy files only; manage Python dependencies yourself.")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / "skills" / "aicomp-results"
    codex = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    target = (args.skills_dir or codex / "skills").expanduser().resolve() / source.name
    if target == source or target.is_relative_to(source):
        parser.error("Installation directory must be outside the source skill.")
    if target.exists() and not args.update:
        parser.error(f"Already installed at {target}. Use --update to update its files.")
    # Copy only distributable files; never copy runtime receipts or credentials.
    relative_files = [Path("SKILL.md"), Path("requirements.txt"), Path("agents/openai.yaml")]
    relative_files += [p.relative_to(source) for p in (source / "scripts").glob("*.py")]
    for relative in relative_files:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
    if not args.skip_deps:
        environment = target / ".venv"
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(target / "requirements.txt")],
            check=True,
        )
    print(f"Installed: {target}")
    print("Invoke $aicomp-results in a session that discovers this skill.")


if __name__ == "__main__":
    main()
