"""Tests for the settings poll scheduling.

``next_batch`` is deliberately a module level function of its arguments alone, so
the round robin that keeps a poll cycle bounded can be tested without a Home
Assistant instance.
"""

from collections import deque

from custom_components.sony_vpl.coordinator import next_batch
import pytest

LIMIT = 12


def test_empty_queue_and_nothing_wanted() -> None:
    """With nothing enabled there is nothing to read, which is the normal case."""
    queue: deque[int] = deque()
    assert next_batch(queue, set(), LIMIT) == []
    assert not queue


def test_fewer_items_than_the_limit_are_all_returned() -> None:
    """A handful of enabled settings is read in one cycle."""
    queue: deque[int] = deque()
    wanted = {0x0010, 0x0011, 0x0012}
    assert sorted(next_batch(queue, wanted, LIMIT)) == sorted(wanted)


def test_batch_is_capped_at_the_limit() -> None:
    """More enabled settings than the cap only yield one batch worth."""
    queue: deque[int] = deque()
    wanted = set(range(0x0100, 0x0100 + 34))
    batch = next_batch(queue, wanted, LIMIT)
    assert len(batch) == LIMIT
    assert set(batch) <= wanted


def test_rotation_covers_everything_within_the_expected_cycles() -> None:
    """Every one of 34 items is read within three cycles of twelve.

    This is what bounds the worst case: with the default two minute interval every
    setting is still refreshed within a few minutes, and no single cycle occupies
    the projector for long. The third cycle wraps round and re-reads two items,
    which is the point of the rotation rather than a flaw in it.
    """
    queue: deque[int] = deque()
    wanted = set(range(0x0100, 0x0100 + 34))

    seen: set[int] = set()
    for _ in range(3):
        batch = next_batch(queue, wanted, LIMIT)
        # No item may be read twice inside one cycle, which would waste a slot.
        assert len(set(batch)) == len(batch)
        seen.update(batch)

    assert seen == wanted


def test_two_cycles_are_not_enough_for_34_items() -> None:
    """Sanity check on the bound: 34 items genuinely need three cycles of twelve."""
    queue: deque[int] = deque()
    wanted = set(range(0x0100, 0x0100 + 34))

    seen: set[int] = set()
    for _ in range(2):
        seen.update(next_batch(queue, wanted, LIMIT))

    assert len(seen) == 24
    assert seen != wanted


def test_rotation_wraps_round_to_the_beginning() -> None:
    """Once every item has been read the rotation starts again."""
    queue: deque[int] = deque()
    wanted = set(range(0x0100, 0x0100 + 24))

    first = next_batch(queue, wanted, LIMIT)
    next_batch(queue, wanted, LIMIT)
    third = next_batch(queue, wanted, LIMIT)

    assert third == first


def test_newly_enabled_item_joins_the_rotation() -> None:
    """Enabling an entity adds its item without disturbing the others."""
    queue: deque[int] = deque()
    wanted = {0x0010, 0x0011}
    next_batch(queue, wanted, LIMIT)

    wanted.add(0x0012)
    assert 0x0012 in next_batch(queue, wanted, LIMIT)


def test_disabled_item_leaves_the_rotation() -> None:
    """Disabling an entity stops its item being read at all."""
    queue: deque[int] = deque()
    wanted = {0x0010, 0x0011, 0x0012}
    next_batch(queue, wanted, LIMIT)

    wanted.remove(0x0011)
    assert 0x0011 not in next_batch(queue, wanted, LIMIT)
    assert 0x0011 not in queue


def test_queue_never_grows_beyond_what_is_wanted() -> None:
    """Items come and go without the queue accumulating stale entries."""
    queue: deque[int] = deque()
    for generation in range(5):
        wanted = {0x0100 + generation * 10 + offset for offset in range(10)}
        next_batch(queue, wanted, LIMIT)
        assert set(queue) == wanted
        assert len(queue) == 10


@pytest.mark.parametrize("limit", [1, 2, 5, 12, 100])
def test_any_limit_eventually_covers_everything(limit: int) -> None:
    """Whatever the cap, repeated cycles still read every enabled item."""
    queue: deque[int] = deque()
    wanted = set(range(0x0100, 0x0100 + 20))

    seen: set[int] = set()
    for _ in range(20):
        seen.update(next_batch(queue, wanted, limit))

    assert seen == wanted
