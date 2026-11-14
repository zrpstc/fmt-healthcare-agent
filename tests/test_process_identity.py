from pathlib import Path

import pytest

from wgs_fmt_platform import process_identity as identity


@pytest.fixture
def identity_state(monkeypatch):
    state = {'uid': 0, 'gid': 0, 'groups': [0, 27], 'real': 0, 'saved': 0, 'calls': []}
    monkeypatch.setattr(identity.os, 'getresuid', lambda: (state['real'], state['uid'], state['saved']))
    monkeypatch.setattr(identity.os, 'getresgid', lambda: (0, state['gid'], 0))
    monkeypatch.setattr(identity.os, 'geteuid', lambda: state['uid'])
    monkeypatch.setattr(identity.os, 'getgroups', lambda: list(state['groups']))
    def uid(value):
        state['calls'].append(('uid', value))
        state['uid'] = value
    def gid(value):
        state['calls'].append(('gid', value))
        state['gid'] = value
    def groups(value):
        state['calls'].append(('groups', list(value)))
        state['groups'] = list(value)
    def initialize(user, value):
        assert state['uid'] == 0
        state['groups'] = [value, 999]
    monkeypatch.setattr(identity.os, 'seteuid', uid)
    monkeypatch.setattr(identity.os, 'setegid', gid)
    monkeypatch.setattr(identity.os, 'setgroups', groups)
    monkeypatch.setattr(identity.os, 'initgroups', initialize)
    return state


def test_application_identity_restores_root_and_groups_after_failure(identity_state):
    account = identity.ProcessIdentity(1030, 1030, 'application')
    with pytest.raises(RuntimeError):
        with account.application():
            assert identity_state['uid'] == 1030 and identity_state['gid'] == 1030
            assert identity_state['groups'] == [1030, 999]
            raise RuntimeError('synthetic failure')
    assert identity_state['uid'] == 0 and identity_state['gid'] == 0
    assert identity_state['groups'] == [0, 27]


def test_privileged_docker_scope_restores_application_identity(identity_state):
    account = identity.ProcessIdentity(1030, 1030, 'application')
    with account.application():
        with account.administrator():
            assert identity_state['uid'] == 0 and identity_state['groups'] == [0, 27]
        assert identity_state['uid'] == 1030 and identity_state['groups'] == [1030, 999]
    assert identity_state['uid'] == 0 and identity_state['groups'] == [0, 27]


def test_ordinary_account_never_attempts_to_elevate(identity_state):
    identity_state.update(uid=1030, gid=1030, real=1030, saved=1030, groups=[1030])
    account = identity.ProcessIdentity(1030, 1030, 'application')
    with account.application(), account.administrator():
        assert identity_state['uid'] == 1030
    assert not identity_state['calls']
    other = identity.ProcessIdentity(2000, 2000, 'other')
    with pytest.raises(PermissionError):
        with other.application():
            raise AssertionError('must not switch accounts')


def test_mount_parser_uses_longest_mount_and_handles_escaped_paths(monkeypatch):
    mounts = '1 0 1:1 / / rw - ext4 local rw\n2 1 1:2 / /storage\\040data rw - nfs4 remote rw\n'
    monkeypatch.setattr(Path, 'read_text', lambda self: mounts)
    assert identity.filesystem_type('/home/project') == 'ext4'
    assert identity.filesystem_type('/storage data/workspace/run') == 'nfs4'
    assert identity.application_owned_filesystem('/storage data/workspace')
    assert not identity.application_owned_filesystem('/home/project')
