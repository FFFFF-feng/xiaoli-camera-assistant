"""Independent, read-only evaluation tooling for the line-drawing repair.

The package never calls a model service. It only reads evidence produced by
another process (stored run directories), renders local replays, computes
timing, and enforces the cloud budget handed from A to E.
"""

SCHEMA_RUN = "line-drawing-eval-run-v1"
SCHEMA_LEDGER = "e-cloud-ledger-v1"
