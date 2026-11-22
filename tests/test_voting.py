from datetime import datetime, timedelta, timezone

import pytest

from core.voting import is_everyone, parse_deadline, tally, toggle_choice, winners

UTC = timezone.utc
NOW = datetime(2026, 11, 22, 3, 0, tzinfo=UTC)          # 한국 시간 12:00


@pytest.mark.parametrize("text, delta", [
    ("30분", timedelta(minutes=30)), ("2시간", timedelta(hours=2)), ("1일", timedelta(days=1)),
    ("30m", timedelta(minutes=30)), ("2h", timedelta(hours=2)), ("1.5h", timedelta(hours=1.5)),
    ("1d", timedelta(days=1)),
])
def test_relative_deadline(text, delta):
    assert parse_deadline(text, NOW) == NOW + delta


def test_clock_time_is_next_occurrence_in_kst():
    assert parse_deadline("18:00", NOW) == datetime(2026, 11, 22, 9, 0, tzinfo=UTC)
    assert parse_deadline("11:00", NOW) == datetime(2026, 11, 23, 2, 0, tzinfo=UTC)   # 이미 지났으면 내일


@pytest.mark.parametrize("text", ["11-25 18:00", "2026-11-25 18:00", "2026/11/25 18:00"])
def test_absolute_deadline_is_kst(text):
    assert parse_deadline(text, NOW) == datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("text", ["", "내일", "25:00", "11-25", "abc", "18:00:00"])
def test_bad_deadline(text):
    with pytest.raises(ValueError):
        parse_deadline(text, NOW)


def test_toggle_single_choice():
    assert toggle_choice(set(), 1, False) == {1}
    assert toggle_choice({1}, 2, False) == {2}          # 다른 항목으로 바꾸기
    assert toggle_choice({2}, 2, False) == set()        # 같은 항목이면 취소


def test_toggle_multiple_choice():
    assert toggle_choice({0}, 1, True) == {0, 1}
    assert toggle_choice({0, 1}, 0, True) == {1}


def test_tally_and_winners():
    counts = tally(3, [(1, 0), (2, 0), (3, 2), (4, 9)])        # 범위 밖(9)은 무시
    assert counts == [2, 0, 1]
    assert winners(counts) == [0]
    assert winners([2, 0, 2]) == [0, 2]
    assert winners([0, 0]) == []


def test_everyone():
    assert is_everyone(3, 3) and not is_everyone(2, 3)
    assert not is_everyone(0, 0)