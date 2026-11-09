"""Durable continuation records: model claims beside independently observed source events."""

import json
import re
import subprocess
from pathlib import Path


def _text(content):
    if isinstance(content, str):
        return content
    return '\n'.join(block.get('text', '[image: recover with history_read]') for block in content or [])


def _workspace(folder):
    result = {'cwd': folder}
    if not folder or not Path(folder).is_dir():
        return result
    for key, args in (('root', ['rev-parse', '--show-toplevel']),
                      ('branch', ['branch', '--show-current']), ('head', ['rev-parse', 'HEAD']),
                      ('changes', ['status', '--short']), ('commits', ['log', '-5', '--oneline'])):
        try:
            done = subprocess.run(['git', '-C', folder, *args], capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=5,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.SubprocessError):
            break
        if done.returncode:
            if key == 'root':
                break
            continue  # a new repository has no HEAD or commits yet
        result[key] = done.stdout.strip()
    return result


def build(brain, run: dict, profile: dict, upto: int, summary: str) -> dict:
    """Rebuild facts from original events, never from a summary of an earlier summary."""
    events = brain.store.events(run['app'], run['session'])
    requests, commands, failures, files, loaded, skills, milestones = [], [], [], {}, [], [], []
    folder = profile.get('cwd')
    for event in events:
        kind, event_id = event['type'], event['id']
        if kind == 'input':
            requests.append({'event': event_id, 'text': _text(event['content'])})
            skills += event.get('skills') or []
        elif kind == 'tool':
            name, args = event['name'], event.get('arguments') or {}
            if name == 'tools_load' and event.get('status') == 'ok':
                loaded += args.get('names') or []
            if name == 'skill_use' and event.get('status') == 'ok':
                skills += [args['name']] if args.get('name') else []
            if name.startswith('files_') and args.get('path'):
                files[args['path']] = {'path': args['path'], 'operation': name, 'event': event_id,
                                       'status': event.get('status')}
            output = event.get('content') or ''
            if name == 'shell_run':
                if event.get('status') == 'ok' and args.get('cwd'):
                    base = Path(profile.get('cwd') or next(iter(profile.get('roots') or []), Path.home()))
                    folder = str((base / Path(args['cwd']).expanduser()).resolve())
                match = re.match(r'^\[exit code (-?\d+)\]', output)
                commands.append({'event': event_id, 'command': args.get('command', ''),
                                 'cwd': folder,
                                 'exit_code': int(match[1]) if match else None,
                                 'status': event.get('status'), 'output_tail': output[-1500:]})
            if event.get('status') == 'error':
                failures.append({'event': event_id, 'tool': name, 'error': output[-1000:]})
        elif kind == 'note' and event['text'].startswith('Continuation progress: '):
            milestones.append({'event': event_id, 'text': event['text']})
    progress = []
    run_ids = list(dict.fromkeys([e.get('run') for e in events if e.get('run')] + [run['id']]))
    for run_id in run_ids:
        path = brain.home / 'runs' / str(run_id) / 'progress.md'
        try:
            note = path.read_text(encoding='utf-8')
        except OSError:
            continue
        progress.append({'path': str(path), 'text': note[-12000:]})
    return {'version': 1, 'app': run['app'], 'session': run['session'], 'upto': upto,
            'observed_upto': events[-1]['id'] if events else 0,
            'summary': summary, 'objective': run['options'].get('goal') or (requests[0]['text'] if requests else ''),
            'requests': requests, 'todo': brain.store.session(
                run['app'], run['session'])['state'].get('todo', []),
            'workspace': _workspace(folder), 'files': list(files.values()),
            'commands': commands, 'failures': failures, 'progress': progress, 'milestones': milestones,
            'reload_tools': list(dict.fromkeys(loaded)), 'reload_skills': list(dict.fromkeys(skills))}


def save(brain, run: dict, record: dict) -> int:
    # Keep private history scoped and delete/rewind it atomically with its source session.
    return brain.store.add_event(run['app'], run['session'], run['id'], 'checkpoint',
                                 {'checkpoint': record})['id']


def render(record: dict, event: int, budget: int) -> str:
    """Bound prompt size; the JSON and original events retain the complete record."""
    requests = record['requests']
    selected = requests[:1] + requests[max(1, len(requests) - 4):]
    facts = {'original_requests': [{'event': r['event'], 'text': r['text'][:1200]} for r in selected],
             'workspace': record['workspace'], 'files': record['files'][-10:],
             'observed_commands': record['commands'][-5:], 'failures': record['failures'][-5:],
             'milestones': record['milestones'][-1:],
             'reload_tools': record['reload_tools'], 'reload_skills': record['reload_skills']}
    visible = {}
    omitted = False
    for key, value in facts.items():
        candidate = {**visible, key: value}
        if len(json.dumps(candidate, ensure_ascii=False, indent=1)) <= budget:
            visible = candidate
            continue
        omitted = True
        if isinstance(value, list):
            visible[key] = []
            for entry in value:
                candidate = {**visible, key: visible[key] + [entry]}
                if len(json.dumps(candidate, ensure_ascii=False, indent=1)) <= budget:
                    visible = candidate
    body = json.dumps(visible, ensure_ascii=False, indent=1)
    return (f'\n\n## Continuation checkpoint\nDurable record: history_read(event={event})\n'
            'Original messages, calls, results and images: history_search / history_read(event=ID). '
            'Read original requests when a constraint is unclear. Command exits below are observed; '
            'the summary and todo are claims, not proof of verification. Read current files before editing.\n'
            + body + ('\n[More in the durable record.]' if omitted else ''))
