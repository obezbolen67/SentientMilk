"""Whether the user is at the computer: from what apps report, reusable by anything in the brain."""

from sentientmilk_framework.presence import ABSORBED, GAP, Presence

T = 1_000_000.0


def test_untouched_a_while_they_are_still_there_then_away_and_a_locked_screen_is_away_at_once():
    seen = Presence()
    assert seen.there(T) == 0.0 and not seen.here(T)  # nobody has said anything
    seen.report(idle=0, now=T)
    assert seen.here(T + 30) and seen.there(T + 60) == 1.0  # reading, watching
    seen.report(idle=300, now=T + 300)
    assert 0.3 < seen.there(T + 300) < 0.9
    seen.report(idle=700, now=T + 700)
    assert seen.there(T + 700) == 0.0 and not seen.here(T + 700)
    seen.report(idle=0, now=T + 800)
    assert seen.here(T + 800)
    seen.report(idle=1, locked=True, now=T + 810)
    assert seen.there(T + 810) == 0.0


def test_something_fullscreen_has_them_there_but_absorbed():
    seen = Presence()
    seen.report(idle=2, busy=True, now=T)
    assert seen.here(T) and seen.availability(T) == ABSORBED


def test_when_no_app_reports_nobody_can_tell_but_a_touch_still_counts():
    seen = Presence()
    seen.report(idle=0, now=T)
    assert not seen.here(T + 300)  # the app closed, the machine asleep: no report for minutes
    seen.touch(T + 400)  # they wrote
    assert seen.here(T + 420)


def test_its_clock_runs_only_while_they_could_answer():
    seen = Presence()
    seen.report(idle=0, now=T)
    mark = seen.now(T)
    for second in range(0, 600, 5):  # ten minutes at the computer, touching it
        seen.report(idle=0, now=T + second)
    assert 590 < seen.since(mark, T + 600) < 610
    seen.report(idle=0, busy=True, now=T + 600)
    for second in range(605, 1200, 5):  # ten minutes in a fullscreen game
        seen.report(idle=0, busy=True, now=T + second)
    assert 590 + 0.3 * 590 < seen.since(mark, T + 1200) < 610 + 0.4 * 600
    counted = seen.since(mark, T + 1200)
    seen.report(idle=0, now=T + 1200 + GAP + 3600)  # the machine slept an hour: nobody saw anything
    assert seen.since(mark, T + 1200 + GAP + 3600) == counted
