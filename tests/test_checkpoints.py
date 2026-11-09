import importlib.util
import subprocess
from pathlib import Path

import pytest
from conftest import turn

from sentientmilk_framework import context
from sentientmilk_framework.testing import tool_call


def test_checkpoint_records_original_requests_and_observed_command_evidence(brain):
    assert importlib.util.find_spec('sentientmilk_framework.checkpoint') is not None
    from sentientmilk_framework import checkpoint
    run_id = brain.store.add_run('cli', 'main', 'turn', {})
    request = brain.store.add_event('cli', 'main', run_id, 'input',
                                    {'content': 'Fix expiry; do not add dependencies.', 'display': 'Fix expiry'})
    result = brain.store.add_event('cli', 'main', run_id, 'tool', {
        'name': 'shell_run', 'call_id': 'test', 'arguments': {'command': 'pytest tests/test_auth.py'},
        'status': 'ok', 'content': '[exit code 1]\n2 failed, 18 passed'})
    profile = brain.brain.profile('cli', 'main')
    record = checkpoint.build(brain.brain, brain.store.run(run_id), profile, result['id'], 'Still fixing expiry.')
    assert record['requests'][0]['event'] == request['id']
    assert record['requests'][0]['text'] == 'Fix expiry; do not add dependencies.'
    assert record['commands'][0]['exit_code'] == 1
    assert record['commands'][0]['event'] == result['id']
    assert record['commands'][0]['command'] == 'pytest tests/test_auth.py'
    assert record['workspace']['cwd'] == str(brain.work)
    saved = checkpoint.save(brain.brain, brain.store.run(run_id), record)
    assert brain.store.event(saved)['checkpoint'] == record


def test_clearable_results_are_removed_before_a_summary_call(brain):
    run_id = brain.store.add_run('cli', 'main', 'turn', {})
    brain.store.add_event('cli', 'main', run_id, 'input', {'content': 'Read the results'})
    for index in range(15):
        call = tool_call('files_read', {'path': 'a.txt'}, str(index))
        brain.store.add_event('cli', 'main', run_id, 'assistant', {'message': call})
        brain.store.add_event('cli', 'main', run_id, 'tool', {
            'call_id': str(index), 'name': 'files_read', 'arguments': {'path': 'a.txt'},
            'content': 'x' * 4000 if index < 10 else 'done', 'status': 'ok'})
    profile = {**brain.brain.profile('cli', 'main'), 'context_window': 8000}
    messages = brain.brain.runs.loop._messages(brain.store.run(run_id), profile, '')
    assert not brain.provider.sent
    assert brain.store.events('cli', 'main', types=('clearing',))
    assert context.estimate_tokens(messages) < 4000


def test_automatic_compaction_uses_the_refreshed_memory_immediately(brain):
    brain.client.update_config(context_window=8000)
    brain.store.remember('cli', 'user', 'name', 'BeforeMarker')
    profile = brain.brain.profile('cli', 'main')
    brain.brain.session_snapshot(profile)
    brain.store.remember('cli', 'user', 'name', 'AfterMarker')
    run_id = brain.store.add_run('cli', 'main', 'turn', {})
    brain.store.add_event('cli', 'main', run_id, 'input', {'content': 'x' * 40000, 'display': 'long request'})
    brain.provider.replies += ['A continuation summary.', 'Continued.']
    brain.brain.runs.loop._think(brain.store.run(run_id), profile, brain.brain.toolset(profile, 'turn'), lambda _: None)
    system = brain.provider.sent[-1]['messages'][0]['content']
    assert 'AfterMarker' in system and 'BeforeMarker' not in system


def test_manual_compaction_keeps_the_latest_original_exchange(brain):
    brain.provider.replies += ['First answer.', 'Latest answer.']
    turn(brain, 'cli', 'First request.')
    turn(brain, 'cli', 'Latest request, keep its exact words.')
    brain.provider.replies += ['Earlier work.']
    brain.client.compact_session('cli', 'main')
    compacted = brain.store.last_compaction('cli', 'main')
    after = brain.store.events('cli', 'main', after=compacted['upto'])
    messages = context.project(after, compacted)
    assert any('Latest request, keep its exact words.' in str(m['content']) for m in messages)
    assert any(m['role'] == 'assistant' and m['content'] == 'Latest answer.' for m in messages)


def test_a_model_can_checkpoint_at_a_safe_tool_boundary(brain):
    brain.provider.replies += [tool_call('context_compact', {'note': 'Finished inspection; now implement.'}),
                               'Inspection done; implementation next.', 'Continuing implementation.']
    result = turn(brain, 'cli', 'Inspect then implement.')
    assert result['reply'] == 'Continuing implementation.'
    compacted = brain.store.last_compaction('cli', 'main')
    assert compacted
    assert 'Finished inspection; now implement.' in str(brain.provider.sent[-1]['messages'])
    assert brain.store.events('cli', 'main', types=('tool',))[0]['content'].startswith('Checkpoint requested')
    record = brain.store.event(compacted['checkpoint']['event'])['checkpoint']
    assert record['milestones'][-1]['text'].endswith('Finished inspection; now implement.')


def test_repeated_checkpoints_preserve_exact_sources_and_current_progress(brain):
    run_id = brain.store.add_run('cli', 'main', 'task', {'goal': 'Fix expiry'})
    run = brain.store.run(run_id)
    source = brain.store.add_event('cli', 'main', run_id, 'input', {
        'content': 'Original constraint: ' + 'x' * 2000 + ' DO NOT CHANGE API', 'display': 'Fix expiry'})
    profile = brain.brain.profile('cli', 'main')
    folder = brain.home / 'runs' / str(run_id)
    folder.mkdir(parents=True)
    (folder / 'progress.md').write_text('Parser done; expiry check next.', encoding='utf-8')
    brain.provider.replies += ['First summary.']
    assert brain.brain.runs.loop.compact(run, profile, keep=0)
    brain.store.add_event('cli', 'main', run_id, 'input', {'content': 'Continue without repeating parser.'})
    brain.store.update_session('cli', 'main', 'state', lambda s: {**s, 'todo': [{'text': 'expiry', 'status': 'doing'}]})
    brain.provider.replies += ['Second summary.']
    assert brain.brain.runs.loop.compact(run, profile, keep=0)
    last = brain.store.last_compaction('cli', 'main')
    record = brain.store.event(last['checkpoint']['event'])['checkpoint']
    assert record['requests'][0] == {'event': source['id'], 'text': source['content']}
    assert record['todo'] == [{'text': 'expiry', 'status': 'doing'}]
    assert 'Parser done; expiry check next.' in last['summary']


@pytest.mark.parametrize('content', [[{'type': 'text', 'text': 'bad shape'}], 'x' * 100000])
def test_malformed_or_oversized_summary_cannot_overflow_context(brain, content):
    brain.client.update_config(context_window=8000)
    run_id = brain.store.add_run('cli', 'main', 'turn', {})
    brain.store.add_event('cli', 'main', run_id, 'input', {'content': 'Preserve the actual requirement.'})
    brain.provider.replies += [{'role': 'assistant', 'content': content}]
    assert brain.brain.runs.loop.compact(brain.store.run(run_id), brain.brain.profile('cli', 'main'), keep=0)
    compacted = brain.store.last_compaction('cli', 'main')
    assert len(compacted['summary']) <= 16000
    assert 'history_read(event=' in compacted['summary']


def test_clearing_a_chat_removes_its_durable_checkpoint(brain):
    run_id = brain.store.add_run('cli', 'main', 'turn', {})
    brain.store.add_event('cli', 'main', run_id, 'input', {'content': 'private request marker'})
    brain.provider.replies.append('A private summary.')
    assert brain.brain.runs.loop.compact(brain.store.run(run_id), brain.brain.profile('cli', 'main'), keep=0)
    event = brain.store.last_compaction('cli', 'main')['checkpoint']['event']
    brain.store.clear_session('cli', 'main')
    assert brain.store.event(event) is None
    assert not list((brain.home / 'runs').glob('*/checkpoint-*.json'))


def test_checkpoint_metadata_alone_does_not_trigger_another_summary(brain):
    run_id = brain.store.add_run('cli', 'main', 'turn', {})
    brain.store.add_event('cli', 'main', run_id, 'input', {'content': 'Original request'})
    run, profile = brain.store.run(run_id), brain.brain.profile('cli', 'main')
    brain.provider.replies.append('One summary.')
    assert brain.brain.runs.loop.compact(run, profile, keep=0)
    assert not brain.brain.runs.loop.compact(run, profile, keep=0)
    assert len(brain.provider.sent) == 1


def test_checkpoint_uses_the_observed_command_workspace(brain):
    from sentientmilk_framework import checkpoint
    subprocess.run(['git', 'init', '-q', '-b', 'work', str(brain.work)], check=True)
    (brain.work / 'changed.py').write_text('x = 1\n', encoding='utf-8')
    run_id = brain.store.add_run('cli', 'main', 'turn', {})
    result = brain.store.add_event('cli', 'main', run_id, 'tool', {
        'name': 'shell_run', 'call_id': 'check', 'arguments': {'command': 'pytest', 'cwd': str(brain.work)},
        'status': 'ok', 'content': '[exit code 0]\n1 passed'})
    profile = {**brain.brain.profile('cli', 'main'), 'cwd': None}
    record = checkpoint.build(brain.brain, brain.store.run(run_id), profile, result['id'], 'Verified.')
    assert Path(record['workspace']['root']) == brain.work
    assert record['workspace']['branch'] == 'work'
    assert 'changed.py' in record['workspace']['changes']
