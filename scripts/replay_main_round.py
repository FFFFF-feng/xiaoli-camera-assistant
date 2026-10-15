"""Replay baseline raw content through current main website code without API calls."""
from main_round_support import cli

if __name__ == "__main__":
    raise SystemExit(cli(live=False))
