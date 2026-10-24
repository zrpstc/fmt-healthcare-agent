import json
from types import SimpleNamespace as NS

import pytest

from app.agent_chat import TOOLS
from app.model_protocol import ModelProtocolError, decode_message, visible_text


def msg(content='', calls=None):
    return NS(content=content, tool_calls=calls)


def test_qwen_xml_and_orphan_thinking_are_recovered():
    content = '不应显示的内部计划</think>\n<tool_call><function=get_sample_status><parameter=sample_id>test2</parameter></function></tool_call>'
    text, calls = decode_message(msg(content), TOOLS)
    assert text == ''
    assert calls[0]['function']['name'] == 'get_sample_status'
    assert json.loads(calls[0]['function']['arguments']) == {'sample_id': 'test2'}


def test_json_native_and_typed_xml_calls():
    for content in [
        '<tool_call>{"name":"list_samples","arguments":{"limit":3}}</tool_call>',
        '<tool_call><function=list_samples><parameter=limit>3</parameter></function></tool_call>',
    ]:
        _, calls = decode_message(msg(content), TOOLS)
        assert json.loads(calls[0]['function']['arguments'])['limit'] == 3
    call = NS(id='native-id', function=NS(name='list_samples', arguments='{"limit":2}'))
    _, calls = decode_message(msg('读取样本', [call]), TOOLS)
    assert calls[0]['id'] == 'native-id'


@pytest.mark.parametrize('content', [
    '<tool_call><function=get_sample_status><parameter=sample_id>test2</parameter>',
    '<tool_call>{"name":"bash","arguments":{"command":"id"}}</tool_call>',
    '<tool_call>{"name":"get_sample_status","arguments":{}}</tool_call>',
    '<tool_call>{"name":"list_samples","arguments":{"limit":true}}</tool_call>',
    '<tool_call>{"name":"list_samples","arguments":{"limit":500}}</tool_call>',
    '<tool_call>{"name":"list_samples","arguments":{"unknown":"x"}}</tool_call>',
    '<think>unfinished hidden thought',
])
def test_malformed_or_unavailable_calls_never_execute(content):
    with pytest.raises(ModelProtocolError):
        decode_message(msg(content), TOOLS)


def test_subagent_write_calls_are_not_recovered():
    tools = [t for t in TOOLS if t['function']['name'] == 'search_pubmed']
    with pytest.raises(ModelProtocolError):
        decode_message(msg('<tool_call>{"name":"request_report_generation","arguments":{"sample_id":"test2"}}</tool_call>'), tools)


def test_visible_answer_hides_reasoning_and_protocol_only():
    assert visible_text('hidden</think>结论') == '结论'
    assert visible_text('<think>hidden</think>结果') == '结果'
    assert visible_text('结果\n<think>unfinished') == '结果'
