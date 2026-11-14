"""Scoped identities for single-threaded deployment commands and NFS file access."""
from contextlib import contextmanager
from pathlib import Path
import os
import pwd


class ProcessIdentity:
    def __init__(self, uid, gid, user):
        self.uid, self.gid, self.user = uid, gid, user
        real, effective, saved = os.getresuid()
        self.admin_authorized = real == 0 or effective == 0 or saved == 0
        self.admin_gid = os.getresgid()[1] if effective == 0 else 0
        self.admin_groups = os.getgroups() if effective == 0 else [0]

    @classmethod
    def configured(cls, root, environment):
        root = Path(root)
        owner = root.stat().st_uid or root.parent.stat().st_uid
        account = pwd.getpwnam(environment['WGS_RUN_USER']) if environment.get('WGS_RUN_USER') else pwd.getpwuid(owner)
        return cls(account.pw_uid, account.pw_gid, account.pw_name)

    @contextmanager
    def _assume(self, uid, gid, groups=None):
        previous_uid = os.getresuid()[1]
        previous_gid = os.getresgid()[1]
        previous_groups = os.getgroups()
        if previous_uid == uid and (previous_gid == gid or not self.admin_authorized):
            yield
            return
        if not self.admin_authorized:
            raise PermissionError('Application identity differs from the current account')
        try:
            os.seteuid(0)
            if groups is None:
                os.initgroups(self.user, gid)
            else:
                os.setgroups(groups)
            os.setegid(gid)
            os.seteuid(uid)
            yield
        finally:
            os.seteuid(0)
            os.setgroups(previous_groups)
            os.setegid(previous_gid)
            os.seteuid(previous_uid)

    def application(self):
        return self._assume(self.uid, self.gid)

    @contextmanager
    def administrator(self):
        if not self.admin_authorized:
            # Preserve ordinary Docker-group access without attempting elevation.
            yield
            return
        with self._assume(0, self.admin_gid, self.admin_groups):
            yield


def filesystem_type(path):
    path = Path(path).absolute()
    matches = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left, right = line.split(' - ', 1)
        field = left.split()[4]
        for escaped, value in (('\\040', ' '), ('\\011', '\t'), ('\\012', '\n'), ('\\134', '\\')):
            field = field.replace(escaped, value)
        point = Path(field)
        if path.is_relative_to(point):
            matches.append((len(str(point)), right.split()[0]))
    return max(matches)[1] if matches else 'unknown'


def application_owned_filesystem(path):
    kind = filesystem_type(path)
    return kind in {'nfs', 'nfs4', 'cifs', 'fuse', 'fuseblk'} or kind.startswith('fuse.')
