from .greenhouse import GreenhouseCollector

# To add a source later (Lever, Ashby, ...): write a class with fetch(board_token, company_name)
# returning a list of raw job dicts, then register it here. Nothing else changes.
COLLECTORS = {'greenhouse': GreenhouseCollector()}
