"""Project-scoped ownership repair; reads file bytes only to isolate external hard links."""
import os
from pathlib import Path
import shutil
import stat
import uuid

class OwnershipFailure(Exception):
    pass

def repair_tree(root, uid, gid):
    root = Path(root).resolve(strict=True)
    device = root.stat().st_dev
    links = {}
    # Count aliases inside the requested tree before changing shared inodes.
    for directory, dirs, files, fd in os.fwalk(root, follow_symlinks=False):
        if os.fstat(fd).st_dev != device:
            raise OwnershipFailure('PROJECT_MOUNT_REQUIRES_EXPLICIT_SCOPE')
        for name in files:
            try:info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:continue
            if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                key = (info.st_dev, info.st_ino)
                links[key] = links.get(key, 0) + 1
    counts = {'directories_checked': 0, 'files_checked': 0, 'symlinks_checked': 0,
              'ownership_updates': 0, 'permission_updates': 0, 'external_hardlinks_isolated': 0}

    def desired_mode(info, directory):
        original = stat.S_IMODE(info.st_mode)
        required = 0o700 if directory else 0o600 | (0o100 if original & 0o111 else 0)
        return (original | required) & ~(stat.S_ISUID | stat.S_ISGID)

    def same_entry(fd, name, expected):
        current = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino):
            raise OwnershipFailure('PROJECT_ENTRY_CHANGED_DURING_REPAIR')

    def isolate(fd, parent_fd, name, info, mode):
        # No ownership/mode change is allowed to propagate to an alias outside this tree.
        available = os.fstatvfs(parent_fd)
        if available.f_bavail * available.f_frsize < info.st_size + 1024 * 1024:
            raise OwnershipFailure('INSUFFICIENT_SPACE_TO_ISOLATE_PROJECT_HARDLINK')
        temporary = '.ownership-' + uuid.uuid4().hex
        target = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
        try:
            with os.fdopen(os.dup(fd), 'rb') as source, os.fdopen(os.dup(target), 'wb') as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            after = os.fstat(fd)
            if (after.st_size, after.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                raise OwnershipFailure('PROJECT_FILE_CHANGED_DURING_REPAIR')
            os.fchown(target, uid, gid)
            os.fchmod(target, mode)
            os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
            same_entry(parent_fd, name, info)
            os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            counts['external_hardlinks_isolated'] += 1
        finally:
            os.close(target)
            try:os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:pass

    def adopt(path, parent_fd=None, name=None):
        try:
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False) if parent_fd is not None else path.lstat()
        except FileNotFoundError:
            return
        if info.st_dev != device:
            raise OwnershipFailure('PROJECT_MOUNT_REQUIRES_EXPLICIT_SCOPE')
        owner_change = (info.st_uid, info.st_gid) != (uid, gid)
        if stat.S_ISLNK(info.st_mode):
            counts['symlinks_checked'] += 1
            if owner_change:
                os.chown(name, uid, gid, dir_fd=parent_fd, follow_symlinks=False)
                counts['ownership_updates'] += 1
            return
        directory = stat.S_ISDIR(info.st_mode)
        regular = stat.S_ISREG(info.st_mode)
        if not directory and not regular:
            if stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode):
                raise OwnershipFailure('PROJECT_DEVICE_REQUIRES_EXPLICIT_SCOPE')
            if owner_change:
                os.chown(name, uid, gid, dir_fd=parent_fd, follow_symlinks=False)
                counts['ownership_updates'] += 1
            return
        counts['directories_checked' if directory else 'files_checked'] += 1
        mode = desired_mode(info, directory)
        mode_change = stat.S_IMODE(info.st_mode) != mode
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_DIRECTORY if directory else 0)
        fd = os.open(name, flags, dir_fd=parent_fd) if parent_fd is not None else os.open(path, flags)
        try:
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise OwnershipFailure('PROJECT_ENTRY_CHANGED_DURING_REPAIR')
            if not directory and (owner_change or mode_change) and current.st_nlink > links.get((current.st_dev, current.st_ino), 1):
                isolate(fd, parent_fd, name, current, mode)
                counts['ownership_updates'] += int(owner_change)
                counts['permission_updates'] += int(mode_change)
                return
            if owner_change:
                os.fchown(fd, uid, gid)
                counts['ownership_updates'] += 1
            if mode_change or owner_change:
                os.fchmod(fd, mode)
                counts['permission_updates'] += int(mode_change)
            if directory:
                for entry in os.listdir(fd):
                    adopt(path / entry, fd, entry)
        finally:
            os.close(fd)
    adopt(root)
    return counts
