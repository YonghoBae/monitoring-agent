"""Publish neutral, complete request fields for the eight-case confirmatory core.

Only answer_fields changes. Questions, worlds, identities and external provenance
remain byte-equivalent as JSON values. No answers or expected values are imported
into the model-visible dataset.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REL = 'eval/v5/dataset.json'
GOLD_REL = 'eval/v5/gold-v52.json'
PROVENANCE_REL = 'eval/v5/provenance.json'
BASE_REL = 'eval/v5/canonical-core'
SOURCE_SHA = '2f10a21b02a617c12fe009671b6e0c2cf54b673b9fd09889869f553066905447'
GOLD_SHA = 'e00320b5c6f416b436e86d7f25205698679b1d9ed783f4b2dd377caedb242fc8'
KEYS = ('operation_status', 'secondary_check', 'direct_cause')
FIELDS = {
    'pg_dump_version': [
        {'key': 'operation_status', 'question': '백업 작업 자체의 결과를 succeeded, failed, unknown 중 하나로 알려줘. 일반 컨테이너 상태와 구분하고, 백업 결과를 확인할 수 없으면 unknown으로 답해.'},
        {'key': 'secondary_check', 'question': '해당 덤프에 대해 기록된 제한적인 복원 검사 결과를 알려줘. 기록이 없거나 결과를 확인할 수 없으면 unknown으로 답해. 확인된 검사 범위 안에서 설명해.'},
        {'key': 'direct_cause', 'question': '실패했다면 기록으로 확인되는 직접 원인을 알려줘. 작업 성공이면 not_applicable, 실패 원인이나 작업 결과가 확인되지 않으면 unknown으로 답해. 관측되지 않은 근본 원인은 단정하지 마.'},
    ],
    'pg_init_permissions': [
        {'key': 'operation_status', 'question': 'PostgreSQL 초기화 단계 자체의 결과를 succeeded, failed, unknown 중 하나로 알려줘. 일반 컨테이너 상태와 구분하고, 초기화 결과를 확인할 수 없으면 unknown으로 답해.'},
        {'key': 'secondary_check', 'question': '기록된 초기 데이터 조회 결과를 알려줘. 기록이 없거나 결과를 확인할 수 없으면 unknown으로 답해. 확인된 조회 범위 안에서 설명해.'},
        {'key': 'direct_cause', 'question': '실패했다면 기록으로 확인되는 직접 원인을 알려줘. 작업 성공이면 not_applicable, 실패 원인이나 작업 결과가 확인되지 않으면 unknown으로 답해. 관측되지 않은 근본 원인은 단정하지 마.'},
    ],
}
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def save(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
def transform(source, gold):
    result = copy.deepcopy(source)
    scenes = result['scenarios']
    if len(scenes) != 8 or len({s['id'] for s in scenes}) != 8 or set(gold) != {s['id'] for s in scenes}:
        raise ValueError('Exactly the approved eight case identities required')
    for scene in scenes:
        if scene['split'] != 'test' or scene['family'] not in FIELDS: raise ValueError('Unexpected case scope')
        if {f['key'] for f in gold[scene['id']]['reference']['required_findings']} != set(KEYS):
            raise ValueError('Approved rubric must enumerate exactly the three requested findings')
        scene['answer_fields'] = copy.deepcopy(FIELDS[scene['family']])
    return result
def verify(dataset):
    if sha(ROOT/SOURCE_REL) != SOURCE_SHA or sha(ROOT/GOLD_REL) != GOLD_SHA:
        raise ValueError('Approved original dataset or reference changed')
    expected = transform(read(ROOT/SOURCE_REL), read(ROOT/GOLD_REL))
    if dataset != expected: raise ValueError('Canonical dataset differs from the neutral field-only transformation')
    return True
def build(base=None):
    base = Path(base or ROOT/BASE_REL)
    if (base/'dataset.json').exists() or (base/'build-manifest.json').exists():
        raise ValueError('Refuse to overwrite a published canonical build')
    dataset = transform(read(ROOT/SOURCE_REL), read(ROOT/GOLD_REL)); verify(dataset)
    base.mkdir(parents=True, exist_ok=True); save(base/'dataset.json', dataset)
    manifest = {'kind': 'confirmatory_canonical_core', 'source_dataset': SOURCE_REL,
        'source_dataset_sha256': sha(ROOT/SOURCE_REL), 'approved_gold': GOLD_REL,
        'approved_gold_sha256': sha(ROOT/GOLD_REL), 'provenance': PROVENANCE_REL,
        'provenance_sha256': sha(ROOT/PROVENANCE_REL), 'built_dataset_sha256': sha(base/'dataset.json'),
        'builder_sha256': sha(Path(__file__)), 'case_ids': [s['id'] for s in dataset['scenarios']],
        'only_changed_scene_field': 'answer_fields', 'requested_findings': list(KEYS),
        'schema_policy': 'Same neutral three fields for every phase within each family; no expected values',
        'exploratory_campaign_preserved': 'eval/v5/comparison-2'}
    save(base/'build-manifest.json', manifest); return manifest
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--out', type=Path)
    print(json.dumps(build(parser.parse_args().out), ensure_ascii=False, indent=2))
