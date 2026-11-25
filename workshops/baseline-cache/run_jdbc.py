"""Run a JDBC build with private dotenv values in the child environment."""

import argparse
import os
from pathlib import Path
import subprocess

from dotenv import dotenv_values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.env.is_file():
        parser.error("The private dotenv file does not exist")
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("Provide the Java/Maven command after --")
    environment = {name: value for name, value in dotenv_values(args.env).items() if value is not None}
    environment.update(os.environ)
    raise SystemExit(subprocess.call(command, env=environment))


if __name__ == "__main__":
    main()
