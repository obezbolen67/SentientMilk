import json
from types import SimpleNamespace

import pytest
from test_ai import FakeResponse, make_llm

from sentientmilk_framework import Conversation
from sentientmilk_framework.tools import read, read_files, replace_text, web_search


def tool_message(arguments='{}'):
    return {"role": "assistant", "content": None, "reasoning_content": "keep reasoning",
            "tool_calls": [{"id": "a", "type": "function",
                            "function": {"name": "probe", "arguments": arguments}}]}


def reply(message, usage=None):
    return FakeResponse(payload={"choices": [{"finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                                             "message": message}], "usage": usage})


def test_full_history_roundtrip_and_usage(monkeypatch, tmp_path):
    llm = make_llm(tmp_path)
    llm._loaded_tools['probe'] = SimpleNamespace(run=lambda: {"text": "日本語", "nested": [1, 2]})
    responses = iter([reply(tool_message(), {"prompt_tokens": 100, "completion_tokens": 10}),
                      reply({"role": "assistant", "content": "done"}, {"prompt_tokens": 150, "completion_tokens": 5})])
    payloads = []

    def post(*args, **kwargs):
        payloads.append(json.loads(kwargs['data']))
        return next(responses)

    monkeypatch.setattr('sentientmilk_framework.ai.requests.post', post)
    path = tmp_path / 'history.db'
    conversation = Conversation(path=path)
    user = {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]}
    conversation.append(user)
    llm.completion(conversation)
    assert Conversation(path=path) == conversation
    assert conversation[1] == tool_message()
    assert conversation[0] == user
    assert conversation[2]['content'] == '{"text":"日本語","nested":[1,2]}'
    assert payloads[1]['messages'][:-2] == payloads[0]['messages']
    assert llm.last_usage['prompt_tokens'] == 250
    assert llm.last_usage['completion_tokens'] == 15
    assert llm.last_usage['cached_tokens'] is None
    assert llm.last_usage['request_count'] == 2


def test_completed_side_effect_survives_later_network_failure(monkeypatch, tmp_path):
    llm = make_llm(tmp_path)
    performed = []
    llm._loaded_tools['probe'] = SimpleNamespace(run=lambda: performed.append(1) or 'done')
    responses = iter([reply(tool_message())])
    monkeypatch.setattr('sentientmilk_framework.ai.requests.post', lambda *a, **kw: next(responses))
    path = tmp_path / 'history.db'
    conversation = Conversation(path=path)
    conversation.append({"role": "user", "content": "do work"})
    with pytest.raises(StopIteration):
        llm.completion(conversation)
    restored = Conversation(path=path)
    assert restored[-1]['role'] == 'tool'
    assert restored[-1]['content'] == 'done'
    restored.recover_pending()
    assert restored == conversation
    assert performed == [1]


def test_interrupted_group_marks_unknown_before_next_user(tmp_path):
    path = tmp_path / 'history.db'
    conversation = Conversation(path=path)
    conversation.append(tool_message())
    restored = Conversation(path=path)
    restored.append({"role": "user", "content": "continue"})
    assert restored[-2]['tool_call_id'] == 'a'
    assert 'outcome unknown' in restored[-2]['content']
    assert len(Conversation(path=path)) == 3


def test_failed_persistence_stops_before_side_effect(monkeypatch, tmp_path):
    def fail(message):
        raise OSError('disk full')

    llm = make_llm(tmp_path)
    performed = []
    llm._loaded_tools['probe'] = SimpleNamespace(run=lambda: performed.append(1))
    monkeypatch.setattr('sentientmilk_framework.ai.requests.post', lambda *a, **kw: reply(tool_message()))
    with pytest.raises(OSError, match='disk full'):
        llm.completion(Conversation(on_append=fail))
    assert performed == []


@pytest.mark.parametrize('arguments', ['{bad', '[]', '1'])
def test_bad_arguments_become_tool_results(tmp_path, arguments):
    llm = make_llm(tmp_path)
    llm._loaded_tools['probe'] = SimpleNamespace(run=lambda: 'should not run')
    result = llm._execute_tool_calls(tool_message(arguments)['tool_calls'])
    assert 'error' in json.loads(result[0]['content'])


def test_read_and_replace_preserve_newlines_and_unicode(tmp_path):
    path = tmp_path / 'source.txt'
    source = 'a\r\n日本語\nlast'
    path.write_bytes(source.encode())
    assert read.run(str(path)).split('\n', 1)[1] == source
    replace_text.run(str(path), '日本語', 'changed')
    assert path.read_bytes() == b'a\r\nchanged\nlast'
    with pytest.raises(ValueError):
        replace_text.run(str(path), 'missing', 'x')
    path.write_bytes(b'')
    assert read.run(str(path)).endswith('lines: 0\n')


def test_batched_reads_preserve_errors_and_schema(tmp_path):
    path = tmp_path / 'x'
    path.write_bytes(b'hello')
    results = read_files.run([str(path), str(tmp_path / 'missing')])
    assert results[0]['content'].endswith('hello')
    assert results[1]['type'] == 'FileNotFoundError'
    schema = next(tool for tool in make_llm(tmp_path).get_all_tools() if tool['function']['name'] == 'read_files')
    assert schema['function']['parameters']['properties']['files']['items'] == {"type": "string"}


def test_search_keeps_extra_snippets():
    result = web_search._extract_results({"web": {"results": [{"extra_snippets": ['full extra fact']}]}})
    assert result['web_results'][0]['extra_snippets'] == ['full extra fact']


def test_stream_usage_and_reasoning_persist(monkeypatch, tmp_path):
    events = [
        {"choices": [{"delta": {"reasoning_content": "reason"}}]},
        {"choices": [{"delta": {"content": "hello"}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 80, "completion_tokens": 4,
                                  "prompt_tokens_details": {"cached_tokens": 64}}},
    ]
    llm = make_llm(tmp_path)
    llm.settings.stream_include_usage = True
    monkeypatch.setattr('sentientmilk_framework.ai.requests.post', lambda *a, **kw: FakeResponse(events=events))
    conversation = Conversation()
    list(llm.completion(conversation, stream=True))
    assert conversation[-1]['reasoning_content'] == 'reason'
    assert llm.last_usage['cached_tokens'] == 64
    assert llm._request_payload([], [], True)['stream_options']['include_usage'] is True


def test_truncated_stream_not_committed(monkeypatch, tmp_path):
    monkeypatch.setattr('sentientmilk_framework.ai.requests.post', lambda *a, **kw: FakeResponse(events=[
        {"choices": [{"delta": {"content": "partial"}}]}
    ]))
    conversation = Conversation()
    with pytest.raises(RuntimeError, match='finish reason'):
        list(make_llm(tmp_path).completion(conversation, stream=True))
    assert conversation == []


def test_stream_cancel_closes_connection(monkeypatch, tmp_path):
    response = FakeResponse(events=[{"choices": [{"delta": {"content": "partial"}}]}])
    closed = []
    response.close = lambda: closed.append(True)
    monkeypatch.setattr('sentientmilk_framework.ai.requests.post', lambda *a, **kw: response)
    conversation = Conversation()
    stream = make_llm(tmp_path).completion(conversation, stream=True)
    next(stream)
    stream.close()
    assert closed == [True]
    assert conversation == []


def test_indexed_reasoning_fragments_merge_without_duplicate_metadata(tmp_path):
    llm = make_llm(tmp_path)
    first = [{"index": 0, "type": "reasoning.text", "text": "日本", "id": "r1"}]
    second = [{"index": 0, "type": "reasoning.text", "text": "語", "id": "r1"}]
    assert llm._merge_response_field(first, second) == [
        {"index": 0, "type": "reasoning.text", "text": "日本語", "id": "r1"}
    ]


def test_message_transform_changes_transport_not_durable_history(monkeypatch, tmp_path):
    payloads = []
    monkeypatch.setattr('sentientmilk_framework.ai.requests.post', lambda *a, **kwargs:
                        payloads.append(json.loads(kwargs['data'])) or
                        reply({'role': 'assistant', 'content': 'done'}))
    conversation = Conversation([{'role': 'user', 'content': 'full'}])
    make_llm(tmp_path).completion(
        conversation,
        message_transform=lambda messages: [{'role': 'user', 'content': 'projected'}],
    )
    assert payloads[0]['messages'][-1]['content'] == 'projected'
    assert conversation[0]['content'] == 'full'
    assert conversation[-1]['content'] == 'done'
