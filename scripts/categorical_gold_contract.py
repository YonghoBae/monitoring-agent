"""Necessary log-evidence checks for controlled categorical labels.

These checks catch absent evidence, not all semantic ambiguity. Independent
review is still required; a marker is not a proof of an ultimate root cause.
"""

MARKERS = {
    'failure': {
        'port_bind': ('Address already in use', 'Problem binding to port'),
        'missing_env': ('MYSQL_HOST is not defined',),
        'yaml_parse': ('yaml: line',),
        'lock': ('lock not available',),
    },
    'encoding': {
        'software': ('libx264', 'libx265', 'software encoding'),
        'hardware': ('h264_nvenc', 'hevc_nvenc', 'h264_vaapi', 'hevc_vaapi', 'h264_qsv', 'hevc_qsv'),
    },
}


def assert_categorical_log_support(scene):
    checked = []
    for gold in scene['gold']:
        labels = MARKERS.get(gold['key'])
        if not labels:
            continue
        targets = {target.removeprefix('log:docker:') for target in gold['evidence_targets']
                   if target.startswith('log:docker:')}
        lines = [entry['line'] for log in scene['world']['logs']
                 if log['source'] == 'docker' and log['name'] in targets
                 for entry in log['entries'] if -1800 <= entry['offset_seconds'] <= 0]
        text = '\n'.join(lines).casefold()
        if gold['value'] in labels:
            assert any(marker.casefold() in text for marker in labels[gold['value']]), (
                scene['id'], gold['key'], gold['value'], 'supporting log marker absent')
            checked.append(gold['key'])
        elif gold['key'] == 'encoding' and gold['value'] == 'unknown':
            assert lines, (scene['id'], 'unknown encoding needs inspected log content')
            assert not any(marker.casefold() in text for markers in labels.values() for marker in markers), (
                scene['id'], 'explicit encoder contradicts unknown encoding')
            checked.append(gold['key'])
    return checked
