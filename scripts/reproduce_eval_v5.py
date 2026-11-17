"""Capture real, isolated PostgreSQL fault/recovery observations for eval v5.

Uses cached images, a private internal network, no published ports, no production
mounts, no Docker socket mounts, non-root processes and bounded tmpfs/resources.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

IMAGES = {'old': 'postgres:16.16-trixie', 'current': 'postgres:17.12-alpine'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Lab:
    def __init__(self, out):
        self.out = out
        self.prefix = 'monitoring-v5-' + uuid.uuid4().hex[:10]
        self.network = self.prefix + '-net'
        self.containers = []
        self.events = []

    def command(self, args, *, input=None, check=True, timeout=45):
        start = time.time()
        result = subprocess.run(['rtk', 'proxy', 'docker', *args], input=input,
                                text=True, capture_output=True, timeout=timeout)
        record = {'id': 'event-' + str(len(self.events) + 1),
                  'captured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'argv': ['docker', *args], 'exit_code': result.returncode,
                  'stdout': result.stdout, 'stderr': result.stderr,
                  'elapsed_seconds': round(time.time() - start, 3)}
        self.events.append(record)
        self.write('events.json', self.events)
        if check and result.returncode:
            raise RuntimeError(f'Docker command failed; see {record["id"]}')
        return record

    def write(self, name, obj):
        target = self.out / name
        target.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')

    def start_server(self, suffix, image, *, sql=None, network=None):
        name = self.prefix + '-' + suffix
        self.containers.append(name)
        args = ['run', '-d', '--name', name, '--network', network or self.network,
                '--user', 'postgres', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--memory', '256m',
                '--cpus', '0.5', '--pids-limit', '128',
                '--tmpfs', '/tmp:rw,size=128m,mode=1777',
                '--tmpfs', '/var/run/postgresql:rw,size=16m,mode=1777',
                '-e', 'PGDATA=/tmp/pgdata', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
                '-e', 'POSTGRES_DB=evaldata']
        if sql:
            args += ['--mount', f'type=bind,src={sql},dst=/docker-entrypoint-initdb.d/00-eval.sql,readonly']
        self.command(args + [image])
        return name

    def wait_server(self, name, expect_failure=False):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            state = self.command(['inspect', '--format', '{{json .State}}', name])
            data = json.loads(state['stdout'])
            if not data['Running']:
                if expect_failure and data['ExitCode'] != 0:
                    return state
                raise RuntimeError('Unexpected container exit: ' + name)
            if not expect_failure:
                ready = self.command(['exec', name, 'pg_isready', '-U', 'postgres', '-d', 'evaldata'], check=False)
                # initdb temporarily starts a socket-only server before running SQL.
                if ready['exit_code'] == 0:
                    check = self.command(['exec', name, 'psql', '-U', 'postgres', '-d', 'evaldata', '-Atc',
                                          'SELECT count(*) FROM eval_marker;'], check=False)
                    if check['exit_code'] == 0 and check['stdout'].strip() == '3':
                        return check
            time.sleep(.5)
        raise RuntimeError('Container readiness deadline exceeded')

    def sql(self, name, statement, db='evaldata'):
        return self.command(['exec', name, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', db, '-Atc', statement])

    def logs(self, name):
        return self.command(['logs', '--timestamps', '--tail', '150', name])

    def dump(self, name, image, suffix):
        client = self.prefix + '-client-' + suffix
        self.containers.append(client)
        return self.command(['run', '--rm', '--name', client, '--network', self.network,
            '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--user', 'postgres', '--memory', '128m', '--cpus', '0.5', '--pids-limit', '64',
            '--entrypoint', 'pg_dump', image, '-h', name, '-U', 'postgres', '-d', 'evaldata',
            '--no-owner', '--no-privileges'], check=False)

    def restore(self, name, dump, database):
        self.sql(name, f'CREATE DATABASE {database}', db='postgres')
        self.command(['exec', '-i', name, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', database], input=dump)
        restored = self.sql(name, "SELECT count(*) || ':' || sum(value) FROM eval_marker;", db=database)
        assert restored['stdout'].strip() == '3:60'
        return restored

    def cleanup(self):
        for name in reversed(self.containers):
            self.command(['rm', '-f', '-v', name], check=False)
        self.command(['network', 'rm', self.network], check=False)
        remaining = self.command(['ps', '-aq', '--filter', 'name=' + self.prefix])['stdout'].strip()
        network_left = self.command(['network', 'ls', '-q', '--filter', 'name=' + self.network])['stdout'].strip()
        self.write('cleanup.json', {'prefix': self.prefix, 'containers_remaining': remaining, 'network_remaining': network_left})
        assert not remaining and not network_left


def run(out):
    if out.exists():
        raise ValueError('Refusing to overwrite a previous capture')
    out.mkdir(parents=True)
    lab = Lab(out)
    images = {}
    for key, tag in IMAGES.items():
        info = lab.command(['image', 'inspect', tag, '--format', '{{.Id}}'])
        images[key] = info['stdout'].strip()
    lab.write('environment.json', {'images': images, 'tags': IMAGES, 'prefix': lab.prefix,
              'production_modified': False, 'reproduction_not_original_incident': True})
    phases = {}
    try:
        lab.command(['network', 'create', '--internal', '--label', 'purpose=monitoring-eval-v5', lab.network])
        with tempfile.TemporaryDirectory(prefix='eval-v5-sql-') as temp:
            folder = Path(temp)
            folder.chmod(0o755)
            sql = folder / '00-eval.sql'
            sql.write_text('CREATE TABLE eval_marker(value integer);\nINSERT INTO eval_marker VALUES (10),(20),(30);\n')
            sql.chmod(0o644)
            server = lab.start_server('backup-server', images['current'], sql=sql)
            lab.wait_server(server)
            version = lab.sql(server, 'SHOW server_version;')
            good = lab.dump(server, images['current'], 'baseline')
            assert good['exit_code'] == 0 and 'eval_marker' in good['stdout']
            restored_good = lab.restore(server, good['stdout'], 'restored_before')
            old_version = lab.command(['run', '--rm', '--network', 'none', '--read-only',
                '--cap-drop', 'ALL', '--entrypoint', 'pg_dump', images['old'], '--version'])
            bad = lab.dump(server, images['old'], 'mismatch')
            assert bad['exit_code'] != 0 and 'server version mismatch' in bad['stderr']
            assert '16.' in bad['stderr'] and '17.' in bad['stderr']
            recovered = lab.dump(server, images['current'], 'recovered')
            assert recovered['exit_code'] == 0
            restored_after = lab.restore(server, recovered['stdout'], 'restored_after')
            phases['pg_dump_version'] = {'normal': [good['id'], restored_good['id']],
                'fault': [old_version['id'], version['id'], bad['id']],
                'recovered': [recovered['id'], restored_after['id']],
                'intervention': 'Only change pg_dump client image from 17 to 16, then back to 17. Same server and rows.',
                'source': 'https://about.gitlab.com/blog/postmortem-of-database-outage-of-january-31/',
                'source_fidelity': 'Same incompatibility mechanism, different versions and isolated data; not whole GitLab outage.'}
            # Separate initialization attempts are necessary: init scripts run only on empty PGDATA.
            healthy = lab.start_server('init-normal', images['current'], sql=sql, network='none')
            health = lab.wait_server(healthy)
            normal_logs = lab.logs(healthy)
            sql.chmod(0o600)
            permissions = {'uid': sql.stat().st_uid, 'gid': sql.stat().st_gid, 'mode': oct(sql.stat().st_mode & 0o777),
                           'container_user': 'postgres', 'path': '/docker-entrypoint-initdb.d/00-eval.sql'}
            bad_init = lab.start_server('init-fault', images['current'], sql=sql, network='none')
            bad_state = lab.wait_server(bad_init, expect_failure=True)
            bad_logs = lab.logs(bad_init)
            text = bad_logs['stdout'] + bad_logs['stderr']
            assert 'Permission denied' in text and '/docker-entrypoint-initdb.d/00-eval.sql' in text
            sql.chmod(0o644)
            fixed = lab.start_server('init-recovered', images['current'], sql=sql, network='none')
            fixed_health = lab.wait_server(fixed)
            fixed_logs = lab.logs(fixed)
            phases['pg_init_permissions'] = {'normal': [health['id'], normal_logs['id']],
                'fault': [bad_state['id'], bad_logs['id']], 'fault_file_metadata': permissions,
                'recovered': [fixed_health['id'], fixed_logs['id']],
                'intervention': 'Same SQL and image; remove then restore read permission. Each attempt has fresh tmpfs PGDATA.',
                'source': 'https://github.com/docker-library/postgres/issues/722#issuecomment-621161536',
                'source_fidelity': 'Same unreadable init SQL mechanism; source used chown, this reproduction grants read permission with chmod. PG17 instead of PG11.'}
            lab.write('phases.json', phases)
            lab.write('validation.json', {'passed': True, 'families': 2, 'normal_fault_recovered_verified': True,
                       'backup_restore_row_count': 3, 'backup_restore_value_sum': 60})
            print('PASS: 2 families, real normal/fault/recovery, backup restoration checked.', flush=True)
    finally:
        lab.cleanup()
    files = sorted(f for f in out.iterdir() if f.is_file())
    (out/'SHA256SUMS').write_text(''.join(digest(f.read_bytes())+'  '+f.name+'\n' for f in files))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out)
