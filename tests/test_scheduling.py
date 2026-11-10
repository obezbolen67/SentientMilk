import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from conftest import wait_for

from sentientmilk_framework import BrainError, scheduler
from sentientmilk_framework.store import Store
from sentientmilk_framework.testing import tool_call


def stamp(text):
    return datetime.fromisoformat(text).timestamp()


def test_calendar_rule_keeps_nine_am_across_daylight_saving():
    after = stamp('2027-03-27T08:00:00+00:00')
    due = scheduler.cron_next('0 9 * * *', after, timezone='Europe/Warsaw')
    assert datetime.fromtimestamp(due, timezone.utc).isoformat() == '2027-03-28T07:00:00+00:00'


def test_calendar_skips_nonexistent_time_and_does_not_repeat_fall_back_hour():
    due = scheduler.cron_next('30 2 * * *', stamp('2027-03-27T12:00:00+00:00'), timezone='Europe/Warsaw')
    assert due == stamp('2027-03-29T00:30:00+00:00')
    first = scheduler.cron_next('30 2 * * *', stamp('2027-10-30T12:00:00+00:00'), timezone='Europe/Warsaw')
    assert first == stamp('2027-10-31T00:30:00+00:00')
    following = scheduler.cron_next('30 2 * * *', first + 60, timezone='Europe/Warsaw')
    assert following == stamp('2027-11-01T01:30:00+00:00')


def test_one_off_time_is_validated_in_its_named_zone_and_keeps_seconds():
    now = stamp('2027-03-27T12:00:00+00:00')
    with pytest.raises(ValueError, match='does not exist'):
        scheduler.parse_when('2027-03-28T02:30', now, timezone='Europe/Warsaw')
    kind, spec = scheduler.parse_when('2027-03-28T09:00:35', now, timezone='Europe/Warsaw')
    assert kind == 'at'
    assert scheduler.next_fire(kind, spec, now, now, timezone='Europe/Warsaw') == stamp('2027-03-28T07:00:35+00:00')


def test_an_unknown_timezone_is_explained():
    with pytest.raises(ValueError, match='timezone'):
        scheduler.parse_when('0 9 * * *', stamp('2027-01-01T00:00:00+00:00'), timezone='Unknown/Place')


def app_schedule(brain):
    brain.brain.scheduler.stop()
    return brain.brain.scheduler.create('milk', 'main', '0 9 * * *', 'Find current news and report it.',
                                         mode='app', timezone='Europe/Warsaw', title='Morning news')


def test_app_schedule_creates_a_dedicated_session_and_preserves_its_owner(brain):
    brain.client.update_session('milk', 'main', instructions='Keep reports short.')
    schedule = app_schedule(brain)
    assert schedule['app'] == 'milk' and schedule['session'] == 'main'
    assert schedule['execution_session'] == f"schedule-{schedule['id']}"
    target = brain.client.session('milk', schedule['execution_session'])
    assert target['settings']['title'] == 'Morning news'
    assert target['settings']['instructions'] == 'Keep reports short.'
    assert schedule['timezone'] == 'Europe/Warsaw'


def test_due_occurrence_is_durable_deduplicated_and_coalesces_while_app_is_offline(brain):
    schedule = app_schedule(brain)
    due = time.time() - 120
    brain.store.update_schedule(schedule['id'], next_at=due)
    brain.brain.scheduler.tick(due + 1)
    first = brain.store.occurrences('milk', pending=True)
    assert len(first) == 1 and first[0]['status'] == 'pending'
    assert first[0]['session'] == schedule['execution_session']
    brain.brain.scheduler.tick(due + 1)
    assert len(brain.store.occurrences('milk')) == 1
    assert brain.store.schedule(schedule['id'])['next_at'] > due + 1
    brain.store.update_schedule(schedule['id'], next_at=due + 60)
    brain.brain.scheduler.tick(due + 61)
    latest = brain.store.occurrences('milk', pending=True)
    assert len(latest) == 1 and latest[0]['id'] == first[0]['id']
    assert latest[0]['scheduled_at'] == due + 60 and latest[0]['late']
    assert brain.store.occurrences('cli', pending=True) == []


def test_pausing_and_deleting_prevent_pending_delivery_but_keep_reports(brain):
    schedule = app_schedule(brain)
    due = time.time() - 1
    brain.store.update_schedule(schedule['id'], next_at=due)
    brain.brain.scheduler.tick(due + 1)
    brain.brain.scheduler.set_enabled(schedule['id'], False)
    assert not brain.store.occurrences('milk', pending=True)
    assert brain.store.occurrences('milk')[0]['status'] == 'cancelled'
    brain.brain.scheduler.delete(schedule['id'])
    assert brain.store.find_session('milk', schedule['execution_session'])


def test_deleted_schedule_ids_are_not_reused_for_a_new_task_or_its_history(brain):
    first = app_schedule(brain)
    brain.brain.scheduler.delete(first['id'])
    second = app_schedule(brain)
    assert second['id'] > first['id']
    assert second['execution_session'] != first['execution_session']
    assert brain.store.find_session('milk', first['execution_session'])


def test_deleting_the_source_chat_keeps_schedule_and_deleting_its_own_chat_disables_it(brain):
    schedule = app_schedule(brain)
    brain.brain.delete_session('milk', 'main')
    assert brain.store.schedule(schedule['id'])['enabled']
    brain.brain.delete_session('milk', schedule['execution_session'])
    assert not brain.store.schedule(schedule['id'])['enabled']


def queued_schedule(brain):
    brain.brain.scheduler.stop()
    schedule = brain.client.create_schedule('milk', '0 9 * * *', 'Remember report/news = done, then report.',
                                             timezone='Europe/Warsaw', title='Morning report')
    brain.store.update_schedule(schedule['id'], next_at=time.time() - 1)
    brain.brain.scheduler.tick()
    return schedule, brain.client.scheduled_occurrences('milk')[0]


def test_occurrence_uses_normal_turn_tools_and_a_duplicate_delivery_reuses_its_run(brain):
    schedule, occurrence = queued_schedule(brain)
    assert occurrence['session'] == schedule['execution_session']
    brain.provider.replies += [tool_call('memory_save', {'category': 'report', 'key': 'news', 'value': 'done'}),
                               '{"expression":"arms_down/smile"}\nThe report is ready.']
    events = []
    first = brain.client.turn('milk', occurrence['session'], occurrence=occurrence['id'], on_event=events.append)
    again = brain.client.turn('milk', occurrence['session'], occurrence=occurrence['id'])
    assert first['run'] == again['run'] and first['reply'] == again['reply'] == 'The report is ready.'
    assert [tool['name'] for tool in again['tools']] == ['memory_save']
    assert len(brain.provider.sent) == 2
    assert brain.store.run(first['run'])['kind'] == 'turn'
    assert brain.store.memories('milk')['report']['news'] == 'done'
    assert not brain.client.scheduled_occurrences('milk')
    assert any(event['type'] == 'context' for event in events)
    history = brain.client.history('milk', occurrence['session'])
    assert history[0]['text'] == occurrence['payload']['text']
    assert brain.client.history('milk', 'main') == []


def test_occurrence_cannot_be_claimed_by_another_app_or_wrong_session(brain):
    _, occurrence = queued_schedule(brain)
    assert brain.client.scheduled_occurrences('cli') == []
    with pytest.raises(BrainError):
        brain.client.turn('cli', occurrence['session'], occurrence=occurrence['id'])
    with pytest.raises(BrainError):
        brain.client.turn('milk', 'main', occurrence=occurrence['id'])
    assert not brain.provider.sent


def test_overlapping_occurrence_is_skipped_and_completed_occurrence_stays_auditable(brain):
    schedule, occurrence = queued_schedule(brain)
    run, _ = brain.store.start_scheduled_run('milk', occurrence['session'], occurrence['id'], {}, None)
    brain.store.update_run(run, status='working')
    due = time.time()
    brain.store.update_schedule(schedule['id'], next_at=due)
    brain.brain.scheduler.tick(due + 1)
    assert sorted(item['status'] for item in brain.store.occurrences('milk')) == ['skipped', 'started']
    brain.store.update_run(run, status='completed', result={'reply': 'done'})
    assert not brain.store.occurrences('milk', pending=True)


def test_concurrent_claims_create_only_one_normal_run(brain):
    _, item = queued_schedule(brain)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: brain.store.start_scheduled_run(
            'milk', item['session'], item['id'], {}, None), range(2)))
    assert len({run for run, created in claims}) == 1
    assert sorted(created for run, created in claims) == [False, True]


def test_due_work_waits_for_a_foreground_turn_without_cancelling_it(brain):
    _, item = queued_schedule(brain)
    foreground = brain.store.add_run('milk', item['session'], 'turn', {}, status='working')
    assert brain.client.scheduled_occurrences('milk') == []
    assert brain.store.occurrence('milk', item['id'])['status'] == 'pending'
    brain.store.update_run(foreground, status='completed', result={'reply': 'User work done.'})
    brain.brain.runs.finished(brain.store.run(foreground))
    assert brain.client.scheduled_occurrences('milk')[0]['id'] == item['id']
    assert any(n['type'] == 'schedule.ready' for n in brain.store.notifications('milk'))


def test_only_one_live_app_connection_may_consume_an_occurrence(brain):
    _, item = queued_schedule(brain)
    entered, release = threading.Event(), threading.Event()
    def slow_reply(payload):
        entered.set()
        assert release.wait(10)
        return 'Ready.'
    brain.provider.replies.append(slow_reply)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(brain.client.turn, 'milk', item['session'], occurrence=item['id'])
        assert entered.wait(5)
        try:
            with pytest.raises(BrainError, match='already has an app connection'):
                brain.client.turn('milk', item['session'], occurrence=item['id'])
        finally:
            release.set()
        assert first.result(timeout=10)['status'] == 'completed'


@pytest.mark.parametrize('readonly', [False, True])
def test_reconnect_restores_readonly_actions_and_does_not_blindly_repeat_mutations(brain, readonly, monkeypatch):
    brain.client.declare_app('milk', name='Milk', toolkits=['memory'], actions=[{
        'name': 'screen_action', 'readonly': readonly, 'policy': 'auto'}])
    _, item = queued_schedule(brain)
    run, _ = brain.store.start_scheduled_run('milk', item['session'], item['id'], {}, None)
    brain.store.add_event('milk', item['session'], run, 'input', {'content': 'Scheduled work', 'display': 'Scheduled work'})
    brain.store.add_event('milk', item['session'], run, 'assistant', {
        'message': tool_call('screen_action', {}, 'action-1')})
    brain.store.add_event('milk', item['session'], run, 'action_request', {
        'name': 'screen_action', 'arguments': {}, 'call_id': 'action-1'})
    brain.store.update_run(run, status='input_required')
    original = brain.brain.runs.waiting
    queued = []
    def racing_request(run_id):
        waiting = original(run_id)
        if waiting and not queued:
            queued.append(True)
            brain.brain.bus.publish(('run', run_id), {'type': 'action.requested', 'run': run_id,
                'call_id': 'action-1', 'name': 'screen_action', 'arguments': {}})
        return waiting
    monkeypatch.setattr(brain.brain.runs, 'waiting', racing_request)
    handled = []
    brain.provider.replies.append('Checked the state.')
    reply = brain.client.turn('milk', item['session'], occurrence=item['id'],
                               on_action=lambda event: handled.append(event) or 'A current picture.')
    assert reply['run'] == run and reply['reply'] == 'Checked the state.'
    assert len(handled) == int(readonly)
    result = next(e for e in brain.store.run_events(run) if e['type'] == 'tool')
    assert result['status'] == ('ok' if readonly else 'error')
    if not readonly:
        assert 'may or may not have happened' in result['content']


def test_failed_outbox_write_rolls_back_the_due_claim_and_retries_without_losing_work(brain, monkeypatch):
    schedule = app_schedule(brain)
    due = time.time() - 1
    brain.store.update_schedule(schedule['id'], next_at=due)
    original = brain.store._notify
    def unavailable(*args):
        raise RuntimeError('temporary write failure')
    monkeypatch.setattr(brain.store, '_notify', unavailable)
    brain.brain.scheduler.tick(due + 1)
    assert brain.store.schedule(schedule['id'])['next_at'] == due
    assert brain.store.occurrences('milk') == []
    monkeypatch.setattr(brain.store, '_notify', original)
    brain.brain.scheduler.tick(due + 2)
    assert len(brain.store.occurrences('milk', pending=True)) == 1
    assert brain.store.schedule(schedule['id'])['next_at'] > due + 2


def test_reconnect_restores_approval_and_executes_only_after_the_app_allows_it(brain):
    brain.client.update_app('milk', rules={'ask': ['memory_save']})
    _, item = queued_schedule(brain)
    run, _ = brain.store.start_scheduled_run('milk', item['session'], item['id'], {}, None)
    args = {'category': 'check', 'key': 'approved', 'value': 'yes'}
    brain.store.add_event('milk', item['session'], run, 'input', {'content': 'Scheduled work', 'display': 'Scheduled work'})
    brain.store.add_event('milk', item['session'], run, 'assistant', {'message': tool_call('memory_save', args, 'ask-1')})
    brain.store.add_event('milk', item['session'], run, 'approval_request', {
        'call_id': 'ask-1', 'name': 'memory_save', 'arguments': args})
    brain.store.update_run(run, status='input_required')
    approvals = []
    def approve(event):
        assert 'check' not in brain.store.memories('milk')
        approvals.append(event['call_id'])
        return 'allow'
    brain.provider.replies.append('Approved and saved.')
    result = brain.client.turn('milk', item['session'], occurrence=item['id'], on_approval=approve)
    assert result['run'] == run and result['status'] == 'completed'
    assert approvals == ['ask-1'] and brain.store.memories('milk')['check']['approved'] == 'yes'


def test_skip_catchup_records_a_skipped_slot_without_executing_it(brain):
    schedule = app_schedule(brain)
    due = time.time() - 3600
    brain.store.update_schedule(schedule['id'], next_at=due, catch_up='skip')
    brain.brain.scheduler.tick(startup=True)
    assert not brain.client.scheduled_occurrences('milk')
    assert brain.store.occurrences('milk')[0]['status'] == 'skipped'
    assert brain.store.schedule(schedule['id'])['next_at'] > time.time()


def test_update_cancels_obsolete_pending_work_and_reuses_the_conversation(brain):
    schedule, old = queued_schedule(brain)
    changed = brain.client.update_schedule(schedule['id'], when='0 10 * * 1-5', timezone='UTC',
                                            text='Write the updated report.', title='Updated report')
    assert changed['execution_session'] == schedule['execution_session']
    assert brain.store.occurrence('milk', old['id'])['status'] == 'cancelled'
    assert brain.store.occurrence('milk', old['id'])['payload']['text'] == old['payload']['text']
    brain.store.update_schedule(schedule['id'], next_at=time.time() - 1)
    brain.brain.scheduler.tick()
    new = brain.client.scheduled_occurrences('milk')[0]
    assert new['payload']['text'] == 'Write the updated report.' and new['payload']['timezone'] == 'UTC'
    assert brain.client.session('milk', new['session'])['settings']['title'] == 'Updated report'


def test_failed_scheduled_turn_is_visible_in_its_session_and_occurrence_history(brain):
    _, item = queued_schedule(brain)
    brain.provider.replies.append(401)
    with pytest.raises(BrainError):
        brain.client.turn('milk', item['session'], occurrence=item['id'])
    assert brain.store.occurrence('milk', item['id'])['status'] == 'failed'
    assert 'could not finish' in brain.client.history('milk', item['session'])[-1]['text']
    assert not brain.client.scheduled_occurrences('milk')


def test_returning_before_schedule_creation_undoes_its_triggered_work(brain):
    brain.brain.scheduler.stop()
    brain.provider.replies += [tool_call('schedule_create', {'when': 'every 1h', 'text': 'Write scheduled.txt'}),
                               'Scheduled.']
    brain.client.turn('cli', 'main', 'Schedule the file.', on_approval=lambda event: 'allow')
    target = brain.client.history('cli', 'main')[0]['id']
    schedule = brain.store.schedules('cli')[0]
    brain.store.update_schedule(schedule['id'], next_at=time.time() - 1)
    brain.brain.scheduler.tick()
    item = brain.client.scheduled_occurrences('cli')[0]
    brain.provider.replies += [tool_call('files_write', {'path': 'scheduled.txt', 'content': 'created'}), 'Written.']
    brain.client.turn('cli', item['session'], occurrence=item['id'], on_approval=lambda event: 'allow')
    assert (brain.work / 'scheduled.txt').exists()
    preview = brain.client.rewind_preview('cli', 'main', target)
    assert [entry['path'] for entry in preview['files']] == [str(brain.work / 'scheduled.txt')]
    brain.client.rewind('cli', 'main', target)
    assert not (brain.work / 'scheduled.txt').exists()
    assert brain.store.schedule(schedule['id']) is None


def test_existing_schedules_migrate_without_losing_rules_or_reusing_ids(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE schedules (id INTEGER PRIMARY KEY, app TEXT, session TEXT, kind TEXT, '
                   'spec TEXT, payload TEXT, next_at REAL, last_at REAL, catch_up TEXT, '
                   'created_by TEXT, enabled INTEGER, created REAL)')
        db.execute('INSERT INTO schedules VALUES (20, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 1, ?)',
                   ('legacy', 'main', 'every', '3600', json.dumps({'mode': 'wake', 'text': 'Keep this reminder'}),
                    2000000000, 'once', 'app', 1000000000))
    store = Store(path)
    assert store.schedule(20)['payload'] == {'mode': 'wake', 'text': 'Keep this reminder'}
    assert store.schedule(20)['spec'] == '3600'
    store.delete_schedule(20)
    added = store.add_schedule(app='legacy', session='main', kind='every', spec='3600',
        payload={'mode': 'wake', 'text': 'New reminder'}, next_at=2000000000, catch_up='once', created_by='app', enabled=1)
    assert added > 20


def test_recovery_resumes_the_same_occurrence_without_repeating_a_started_write(brain):
    _, item = queued_schedule(brain)
    run, _ = brain.store.start_scheduled_run('milk', item['session'], item['id'], {}, None)
    brain.store.add_event('milk', item['session'], run, 'input', {'content': 'Scheduled work', 'display': 'Scheduled work'})
    brain.store.add_event('milk', item['session'], run, 'assistant', {'message': tool_call(
        'memory_save', {'category': 'check', 'key': 'uncertain', 'value': 'do not repeat'}, 'write-1')})
    brain.store.add_event('milk', item['session'], run, 'tool_start', {'call_id': 'write-1', 'name': 'memory_save'})
    brain.store.update_run(run, status='working')
    brain.provider.replies.append('Inspected the interrupted operation.')
    brain.brain.runs.recover()
    wait_for(lambda: brain.store.run(run)['status'] == 'completed')
    assert 'check' not in brain.store.memories('milk')
    assert brain.store.occurrence('milk', item['id'])['run'] == run
    assert brain.store.occurrence('milk', item['id'])['status'] == 'completed'
    result = next(e for e in brain.store.run_events(run) if e['type'] == 'tool')
    assert 'check its effect before you repeat' in result['content']


@pytest.mark.parametrize('when,zone', [('every ' + '9' * 400 + 'd', 'UTC'), ('0 9 * * *', 7)])
def test_invalid_calendar_values_fail_before_any_schedule_is_saved(brain, when, zone):
    brain.brain.scheduler.stop()
    with pytest.raises(ValueError):
        brain.brain.scheduler.create('milk', 'main', when, 'Instructions', mode='app', timezone=zone)
    assert brain.store.schedules('milk') == []
