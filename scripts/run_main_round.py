"""Run the original ten controlled inputs/images through the real main pipeline."""
from main_round_support import cli

if __name__ == "__main__":
    raise SystemExit(cli(live=True))
