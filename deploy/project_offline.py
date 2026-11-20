"""Build the offline filter once for native project containers on this Docker host."""
import base64
import ctypes
import errno
import tempfile
from functools import lru_cache


# Keep the filter in a kernel-backed file outside the writable project volume.
LAUNCHER = """import base64, os, sys
fd = os.memfd_create('project-offline')
os.write(fd, base64.b64decode(sys.argv[1], validate=True))
os.lseek(fd, 0, os.SEEK_SET)
os.set_inheritable(fd, True)
os.execv('/usr/bin/setpriv', ['setpriv', '--no-new-privs', '--seccomp-filter', f'/proc/self/fd/{fd}',
    '/usr/bin/timeout', '--kill-after=2s', sys.argv[2], '/bin/bash', '-c', sys.argv[3]])
"""


@lru_cache(maxsize=1)
def filter_base64():
    seccomp = ctypes.CDLL('libseccomp.so.2')
    seccomp.seccomp_init.argtypes = [ctypes.c_uint]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = seccomp.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    if not ctx:
        raise RuntimeError('Could not initialize project isolation')
    try:
        deny = 0x00050000 | errno.EPERM  # SCMP_ACT_ERRNO
        for name in (b'socket', b'socketpair', b'io_uring_setup', b'ptrace', b'process_vm_writev',
                     b'pidfd_getfd', b'pidfd_send_signal'):
            number = seccomp.seccomp_syscall_resolve_name(name)
            if number < 0 or seccomp.seccomp_rule_add(ctx, deny, number, 0) != 0:
                raise RuntimeError('Could not configure project isolation')
        with tempfile.TemporaryFile() as output:
            if seccomp.seccomp_export_bpf(ctx, output.fileno()) != 0:
                raise RuntimeError('Could not export project isolation filter')
            output.seek(0)
            return base64.b64encode(output.read()).decode('ascii')
    finally:
        seccomp.seccomp_release(ctx)
