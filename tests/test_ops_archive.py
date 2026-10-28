"""The archive must not publish internal reasoning, tool secrets or credentials."""
import importlib.util
import json
from pathlib import Path


def exporter():
    path=Path(__file__).resolve().parents[1]/'scripts/export_conversations.py'
    spec=importlib.util.spec_from_file_location('ops_archive',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_archive_keeps_user_corrections_and_final_without_internal_payloads(tmp_path):
    module=exporter()
    def message(role,text,phase=None):
        return {'type':'response_item','timestamp':'2026-10-28T01:02:03Z','payload':
                {'type':'message','id':role+text,'role':role,'phase':phase,'content':[{'type':'input_text','text':text}],
                 'internal_chat_message_metadata_passthrough':{'turn_id':'turn-1'}}}
    entries=[{'type':'session_meta','payload':{'id':'test-thread'}},
             message('user','<environment_context>not-a-request</environment_context>'),
             message('user','原需求'),message('assistant','处理中','commentary'),message('user','后续纠正'),
             {'type':'response_item','payload':{'type':'reasoning','text':'HIDDEN_REASONING'}},
             {'type':'response_item','payload':{'type':'function_call','arguments':'TOOL_SECRET'}},
             message('assistant','完成答复','final_answer')]
    source=tmp_path/'session.jsonl';source.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in entries),encoding='utf-8')
    result=module.export(source,'测试聊天',tmp_path/'archive')
    assert result['user_messages']==2 and result['final_replies']==1
    body=(tmp_path/'archive/001-2026-10-28.md').read_text(encoding='utf-8')
    assert all(x in body for x in ('原需求','后续纠正','处理中','完成答复','09:02:03+08:00'))
    assert all(x not in body for x in ('HIDDEN_REASONING','TOOL_SECRET','not-a-request'))


def test_archive_redacts_credentials_but_keeps_audit_identifiers():
    result=exporter().redact('app_secret="secret-value"\n密码：test-password\nAuthorization: Bearer bearer-secret\nhttps://example.invalid/callback?code=oauth-code&state=oauth-state\nREQ-20261019-002\n-----BEGIN OPENSSH PRIVATE KEY-----\nprivate-data\n-----END OPENSSH PRIVATE KEY-----')
    assert 'REQ-20261019-002' in result
    for secret in ('secret-value','test-password','bearer-secret','oauth-code','oauth-state','private-data'):
        assert secret not in result


def test_archive_does_not_overwrite_prior_evidence(tmp_path):
    import pytest
    source=tmp_path/'session.jsonl';source.write_text('',encoding='utf-8')
    output=tmp_path/'existing';output.mkdir();sentinel=output/'keep';sentinel.write_text('original')
    with pytest.raises(FileExistsError):exporter().export(source,'测试',output)
    assert sentinel.read_text()=='original'
