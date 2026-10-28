"""Browser edits follow database commit order, independent of client clocks.

Only old snapshots can be rebased. Future/invalid versions, idempotency and
business invariants still fail. Each caller holds its transaction/record locks.
"""
import os

def last_commit_wins():
    return os.environ.get('PUDU_CONCURRENT_EDIT_POLICY','strict') == 'last_commit_wins'

def check_version(expected, current, message):
    from .repository import VersionConflict
    if type(expected) is not int or expected < 0 or expected > current:
        raise VersionConflict(message)
    if expected != current and not last_commit_wins():
        raise VersionConflict(message)

def check_versions(expected, current, message):
    from .repository import VersionConflict
    if not isinstance(expected,dict) or any(type(value) is not int or value < 0 for value in expected.values()):
        raise VersionConflict(message)
    if last_commit_wins():
        for key in expected.keys() & current.keys():
            check_version(expected[key],current[key],message)
    elif expected != current:
        raise VersionConflict(message)
