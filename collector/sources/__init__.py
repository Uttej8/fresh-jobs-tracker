from .ashby import AshbyCollector
from .greenhouse import GreenhouseCollector
from .lever import LeverCollector
from .workable import WorkableCollector

# To add a source: write a class with fetch(board_token, company_name) returning raw job dicts,
# add a row to the `sources` table, and register it here. Nothing else changes.
COLLECTORS = {
    'greenhouse': GreenhouseCollector(),
    'lever': LeverCollector(),
    'ashby': AshbyCollector(),
    'workable': WorkableCollector(),
}
