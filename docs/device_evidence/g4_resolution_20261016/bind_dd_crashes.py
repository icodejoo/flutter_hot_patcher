#!/usr/bin/env python3
"""Bind saved DD inputs to analyzer PIDs and their macOS crash reports.

Run small, explicitly selected batches. Original crash reports stay in the
private output directory; report.json contains only the relevant crash fields.
Exit zero means the requested evidence is complete, not that G4 has passed.
"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import struct
import time
import uuid


CASES = ('table_count', 'table_empty_0', 'table_empty_1', 'table_empty_2',
         'table_trunc1', 'table_trunc2000', 'links_flip20000')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def load_ips(path):
    raw = path.read_bytes()
    return json.loads(raw.split(b'\n', 1)[1])


def binary_uuid(path):
    data = path.read_bytes()
    if data[:4] in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
        fat64 = data[:4] == b'\xca\xfe\xba\xbf'
        for i in range(struct.unpack_from('>I', data, 4)[0]):
            entry = 8 + i * (32 if fat64 else 20)
            cpu = struct.unpack_from('>I', data, entry)[0]
            if cpu == 0x100000c:  # CPU_TYPE_ARM64.
                fmt = '>QQ' if fat64 else '>II'
                start, length = struct.unpack_from(fmt, data, entry + 8)
                data = data[start:start + length]
                break
    if data[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('expected a little-endian 64-bit Mach-O binary')
    offset = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        command, size = struct.unpack_from('<II', data, offset)
        if command == 0x1b:  # LC_UUID, metadata only.
            return str(uuid.UUID(bytes=data[offset + 8:offset + 24]))
        if size < 8:
            raise ValueError('invalid Mach-O load command')
        offset += size
    raise ValueError('binary has no LC_UUID')


def crash_matches(body, row):
    if body.get('pid') != row['pid'] or body.get('parentPid') != row['parent_pid']:
        return False
    # macOS redacts procPath to /Users/USER/*/... in local IPS files. Bind
    # the basename AND LC_UUID, in addition to PID, parent, time and SHA-256.
    if Path(body.get('procPath', '')).name != Path(row['command'][0]).name:
        return False
    if not any(image.get('uuid', '').lower() == row['binary_uuid']
               and image.get('name') == Path(row['command'][0]).name
               for image in body.get('usedImages', [])):
        return False
    captured = datetime.strptime(body['captureTime'], '%Y-%m-%d %H:%M:%S.%f %z')
    start = datetime.fromisoformat(row['started_at'])
    end = datetime.fromisoformat(row['finished_at'])
    return start - timedelta(seconds=2) <= captured <= end + timedelta(seconds=10)


def crash_summary(body, raw_path):
    frames = body['threads'][body.get('faultingThread', 0)]['frames']
    images = body['usedImages']
    return {
        'source_filename': raw_path.name,
        'pid': body['pid'], 'parent_pid': body['parentPid'],
        'capture_time': body['captureTime'],
        'exception': {k: body['exception'].get(k) for k in ('type', 'signal', 'subtype')},
        'frames': [dict(symbol=f.get('symbol'), offset=f.get('symbolLocation'),
                        image_offset=f.get('imageOffset'),
                        image_uuid=images[f['imageIndex']].get('uuid')) for f in frames],
    }


def validate_report(report, directory):
    failures = []
    runs = report['runs']
    if len(runs) != 2 * (1 + len(report['cases'])):
        failures.append('missing or extra runs')
    for side in ('ours', 'theirs'):
        if sorted(r['case'] for r in runs if r['side'] == side) != sorted(['valid'] + report['cases']):
            failures.append(side + ': missing or duplicated case')
    for row in runs:
        label = row['side'] + '/' + row['case']
        d = directory / row['directory']
        for name, expected in row['files_sha256'].items():
            p = d / name
            if not p.is_file() or digest(p) != expected:
                failures.append(label + ': changed/missing ' + name)
        if set(row['input_sha256']) != {'table', 'links', 'identity', 'snapshot.so'}:
            failures.append(label + ': incomplete input manifest')
        for name, expected in row['input_sha256'].items():
            if row['files_sha256'].get(name) != expected:
                failures.append(label + ': input changed during run: ' + name)
        if row.get('timed_out'):
            failures.append(label + ': timeout')
        if row['case'] == 'valid':
            if row['returncode'] != 0 or not (d / 'mapping').is_file() or not (d / 'mapping').stat().st_size:
                failures.append(label + ': invalid positive control')
        elif row['side'] == 'ours':
            if row['returncode'] != 255 or (d / 'mapping').exists() or not row['stderr'].startswith('Error: DD '):
                failures.append(label + ': not a clean diagnostic rejection')
        else:
            expected_signal = 'SIGABRT' if row['case'].startswith('table_empty') else 'SIGBUS'
            if row['signal'] != expected_signal:
                failures.append(label + ': unexpected reference disposition')
            raw = d / 'crash.ips'
            if not raw.is_file():
                failures.append(label + ': missing crash report')
            else:
                body = load_ips(raw)
                if not crash_matches(body, row) or body['exception']['signal'] != row['signal']:
                    failures.append(label + ': crash PID/parent/path/time/signal mismatch')
                if crash_summary(body, raw) | {'source_filename': row['crash']['source_filename']} != row['crash']:
                    failures.append(label + ': crash summary differs from IPS')
        binary = Path(row['command'][0])
        if digest(binary) != report['binaries_sha256'][row['side']]:
            failures.append(label + ': binary changed')
    for case in ['valid'] + report['cases']:
        paired = [r for r in runs if r['case'] == case]
        if len(paired) == 2:
            for name in ('table', 'links', 'identity'):
                if paired[0]['input_sha256'][name] != paired[1]['input_sha256'][name]:
                    failures.append(case + ': unequal paired input: ' + name)
    valid = [r for r in runs if r['case'] == 'valid']
    if len(valid) == 2 and valid[0]['files_sha256'].get('mapping') != valid[1]['files_sha256'].get('mapping'):
        failures.append('positive-control mapping differs')
    return failures


def collect_crash(row, directory, ips_dir, wait):
    deadline = time.monotonic() + wait
    while True:
        matches = []
        for p in ips_dir.glob(Path(row['command'][0]).name + '-*.ips'):
            try:
                body = load_ips(p)
                if crash_matches(body, row):
                    matches.append((p, body))
            except (OSError, ValueError, KeyError):
                continue
        if len(matches) == 1:
            p, body = matches[0]
            (directory / 'crash.ips').write_bytes(p.read_bytes())
            row['crash'] = crash_summary(body, p)
            row.pop('crash_report_error', None)
            break
        if time.monotonic() >= deadline:
            row['crash_report_error'] = 'no unique PID-bound crash report'
            break
        time.sleep(0.5)
    row['files_sha256'] = {p.name: digest(p) for p in directory.iterdir() if p.is_file()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--verify-only', action='store_true')
    ap.add_argument('--collect-only', action='store_true',
                    help='collect reports for already saved launches, without rerunning inputs')
    ap.add_argument('--ours', type=Path)
    ap.add_argument('--reference', type=Path)
    ap.add_argument('--matrix', type=Path)
    ap.add_argument('--cases', nargs='+', choices=CASES)
    ap.add_argument('--ips-dir', type=Path, default=Path.home() / 'Library/Logs/DiagnosticReports')
    ap.add_argument('--crash-wait', type=float, default=25)
    args = ap.parse_args()
    args.out = args.out.resolve()
    if args.verify_only:
        report = json.loads((args.out / 'report.json').read_text())
        failures = validate_report(report, args.out)
        print(json.dumps({'verified': not failures, 'failures': failures}))
        return int(bool(failures))
    if args.collect_only:
        path = args.out / 'report.json'
        report = json.loads(path.read_text())
        backup = args.out / 'report.before_collect.json'
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
        for row in report['runs']:
            binary = Path(row['command'][0])
            if digest(binary) != report['binaries_sha256'][row['side']]:
                raise ValueError('cannot collect with a changed binary')
            row['binary_uuid'] = binary_uuid(binary)
            if row['side'] == 'theirs' and row['returncode'] < 0:
                collect_crash(row, args.out / row['directory'], args.ips_dir, args.crash_wait)
        report['collection_note'] = 'Matched redacted procPath by basename plus binary LC_UUID; original launches preserved.'
        report['failures'] = validate_report(report, args.out)
        report['status'] = 'BOUND_DD_DIFFERENCES' if not report['failures'] else 'INCOMPLETE'
        report['collected_at'] = now()
        save(path, report)
        print(report['status'], report['failures'])
        return int(bool(report['failures']))
    if not all((args.ours, args.reference, args.matrix, args.cases)):
        ap.error('a run requires --ours, --reference, --matrix and --cases')
    if len(set(args.cases)) != len(args.cases):
        ap.error('duplicate cases')
    args.out.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    bins = {'ours': args.ours.resolve(), 'theirs': args.reference.resolve()}
    report = {'status': 'RUNNING', 'scope': 'host DD evidence binding, not device acceptance',
              'cases': args.cases, 'started_at': now(), 'parent_pid': os.getpid(),
              'binaries_sha256': {k: digest(v) for k, v in bins.items()}, 'runs': []}
    try:
        for side, binary in bins.items():
            stem = args.matrix.resolve() / ('as.hello.' + side)
            table = Path(str(stem) + '.ddsm_in.ddt').read_bytes()
            links = Path(str(stem) + '.ddsm_in.ddcl').read_bytes()
            for case in ['valid'] + args.cases:
                d = args.out / side / case
                d.mkdir(parents=True)
                dt, cl = table, links
                if case == 'table_count':
                    dt = bytes([255]) + table[1:]
                elif case.startswith('table_empty'):
                    dt = b''
                elif case == 'table_trunc1':
                    dt = table[:1]
                elif case == 'table_trunc2000':
                    dt = table[:2000]
                elif case == 'links_flip20000':
                    changed = bytearray(links); changed[20000] ^= 2; cl = bytes(changed)
                for name, data in {'table': dt, 'links': cl,
                                   'identity': Path(str(stem) + '.ddsm_in.ddid').read_bytes(),
                                   'snapshot.so': Path(str(stem) + '.so').read_bytes()}.items():
                    (d / name).write_bytes(data)
                command = [str(binary), '--compute_dd_slot_mapping=' + str(d / 'mapping'),
                           '--dd_table_data=' + str(d / 'table'),
                           '--dd_caller_links=' + str(d / 'links'),
                           '--dd_function_identity=' + str(d / 'identity'), str(d / 'snapshot.so')]
                row = {'side': side, 'case': case, 'directory': str(d.relative_to(args.out)),
                       'command': command, 'parent_pid': os.getpid(), 'started_at': now(),
                       'binary_uuid': binary_uuid(binary),
                       'input_sha256': {n: digest(d / n) for n in ('table', 'links', 'identity', 'snapshot.so')}}
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                row['pid'] = process.pid
                save(d / 'launch.json', row)
                try:
                    stdout, stderr = process.communicate(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill(); stdout, stderr = process.communicate(); row['timed_out'] = True
                row.update(finished_at=now(), returncode=process.returncode,
                           signal=signal.Signals(-process.returncode).name if process.returncode < 0 else None,
                           stderr=stderr.decode(errors='replace'))
                (d / 'stdout.log').write_bytes(stdout); (d / 'stderr.log').write_bytes(stderr)
                if side == 'theirs' and process.returncode < 0:
                    collect_crash(row, d, args.ips_dir, args.crash_wait)
                row['files_sha256'] = {p.name: digest(p) for p in d.iterdir() if p.is_file()}
                report['runs'].append(row)
                save(args.out / 'report.json', report)
                print(side, case, 'pid=' + str(row['pid']), 'rc=' + str(row['returncode']),
                      'IPS=' + str('crash' in row), flush=True)
        report['failures'] = validate_report(report, args.out)
        report['status'] = 'BOUND_DD_DIFFERENCES' if not report['failures'] else 'INCOMPLETE'
    except Exception as error:
        report.update(status='INCOMPLETE', error=repr(error))
    report['finished_at'] = now()
    save(args.out / 'report.json', report)
    print(report['status'], report.get('failures', report.get('error')), flush=True)
    return int(report['status'] != 'BOUND_DD_DIFFERENCES')


if __name__ == '__main__':
    raise SystemExit(main())
