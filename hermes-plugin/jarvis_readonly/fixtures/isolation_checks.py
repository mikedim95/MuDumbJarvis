"""Operator-authored sandbox acceptance fixture. Execution is recorded separately.

This is reusable verification code, not agent-authored work or a security
efficacy benchmark. It runs only in the reviewed private execution container.
"""
import os
from pathlib import Path
import tempfile
import unittest


class SandboxIsolation(unittest.TestCase):
    def test_nonroot(self):
        self.assertNotEqual(os.getuid(), 0)

    def test_kali_files_absent(self):
        self.assertFalse(Path('/home/kali').exists())

    def test_docker_socket_absent(self):
        self.assertFalse(Path('/var/run/docker.sock').exists())

    def test_runtime_credentials_absent(self):
        for name in ('API_SERVER_KEY', 'PAPERCLIP_API_KEY', 'HERMES_PAPERCLIP_AGENT_KEY',
                'JARVIS_EXECUTION_PROOF_KEY', 'JARVIS_AGENT_PROOF_KEY'):
            with self.subTest(variable=name):
                self.assertNotIn(name, os.environ)

    def test_root_mount_readonly(self):
        self.assertTrue(os.statvfs('/').f_flag & os.ST_RDONLY)

    def test_no_default_ipv4_route(self):
        for line in Path('/proc/net/route').read_text().splitlines()[1:]:
            fields = line.split()
            self.assertFalse(fields[1] == '00000000' and int(fields[3], 16) & 1)

    def test_only_private_workspace_is_used(self):
        cwd = Path.cwd()
        self.assertTrue(cwd == Path('/workspace') or Path('/workspace') in cwd.parents)
        with tempfile.TemporaryDirectory(prefix='.jarvis-check-', dir=cwd) as directory:
            file = Path(directory) / 'probe.txt'
            file.write_text('actual isolated execution')
            self.assertEqual(file.read_text(), 'actual isolated execution')

    def test_container_resource_caps(self):
        cgroup = Path('/sys/fs/cgroup')
        self.assertLessEqual(int((cgroup / 'memory.max').read_text()), 2 * 1024**3)
        self.assertLessEqual(int((cgroup / 'pids.max').read_text()), 256)
        quota, period = (cgroup / 'cpu.max').read_text().split()
        self.assertNotEqual(quota, 'max')
        self.assertLessEqual(int(quota) / int(period), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
