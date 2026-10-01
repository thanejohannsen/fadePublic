"""Settings, and the two bounds that must not be allowed to contradict each other.

Both failures here would otherwise be silent: a bad watch band shows up as a missing
section on the page, and a staleness cap below the lock window shows up as a record
that is smaller than it should be. Neither looks like an error from the outside.
"""

from __future__ import annotations

import pathlib

import pytest

from fadepublic.config import Config, load_config


def test_the_real_config_round_trips_its_new_keys():
    """config.toml is the file the job actually runs with, so it is the one worth
    asserting against rather than a fixture."""
    cfg = load_config(pathlib.Path(__file__).parent.parent / "config.toml")

    assert cfg.threshold == 80
    assert cfg.watch_threshold == 70
    assert cfg.lock_lead_hours == 2
    assert cfg.max_staleness_hours == 12


def test_a_missing_file_is_still_a_valid_config():
    """The defaults have to stand on their own: load_config returns a bare Config()
    when there is nothing on disk, which is the path a fresh clone takes."""
    cfg = load_config("does-not-exist.toml")

    assert cfg.watch_threshold < cfg.threshold
    assert cfg.max_staleness_hours >= cfg.lock_lead_hours


def test_a_watch_band_that_is_not_below_the_threshold_is_refused():
    """The band is the gap between the two numbers. Equal or inverted bounds make it
    empty, and an empty band renders as no section at all rather than an error."""
    with pytest.raises(ValueError, match="watch_threshold"):
        Config(threshold=80, watch_threshold=80)
    with pytest.raises(ValueError, match="watch_threshold"):
        Config(threshold=80, watch_threshold=85)


def test_a_staleness_cap_inside_the_lock_window_is_refused():
    """Dropping a bet for staleness before the window that would have confirmed it
    has even closed is incoherent -- nothing could ever be confirmed."""
    with pytest.raises(ValueError, match="max_staleness_hours"):
        Config(lock_lead_hours=4, max_staleness_hours=2)


def test_validation_is_not_bypassable_by_constructing_config_directly():
    """The checks live in __post_init__ rather than load_config precisely so that
    every route into a Config goes through them."""
    with pytest.raises(ValueError):
        Config(threshold=50, watch_threshold=60)


def test_fractional_hours_are_allowed():
    """A 90-minute lock window is a reasonable thing to want, and an int-only read
    would silently floor it to an hour."""
    cfg = Config(lock_lead_hours=1.5)

    assert cfg.lock_lead_hours == 1.5
