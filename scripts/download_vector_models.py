"""Download pinned official model weights into a local, ignored experiment cache."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'eval/vector-v3-improvement'
CACHE = ROOT / '.cache-vector-models'


def fetch(model):
    name = model['model_id']
    files = model['files']
    weights = 'model.safetensors' if 'model.safetensors' in files else 'pytorch_model.bin'
    selected = [f for f in files if '/' not in f and (f.endswith('.json') or f in [weights, 'tokenizer.model', 'sentencepiece.bpe.model', 'vocab.txt', 'merges.txt'])]
    dest = CACHE / name.replace('/', '--') / model['revision']
    dest.mkdir(parents=True, exist_ok=True)
    records = []
    for filename in selected:
        path = dest / filename
        url = f"https://huggingface.co/{name}/resolve/{model['revision']}/{filename}"
        if not path.exists():
            temp = path.with_suffix(path.suffix + '.part')
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(url, timeout=60) as response, temp.open('wb') as f:
                        downloaded = 0
                        while chunk := response.read(1024 * 1024):
                            if shutil.disk_usage(ROOT).free < 4 * 1024**3:
                                raise RuntimeError('Less than 4 GiB disk free; stop model downloads')
                            f.write(chunk)
                            downloaded += len(chunk)
                            if downloaded % (256 * 1024**2) == 0:
                                print(name, filename, 'MiB', downloaded // 1024**2, flush=True)
                    temp.rename(path)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(2)
        digest = hashlib.sha256()
        with path.open('rb') as f:
            while chunk := f.read(1024 * 1024):
                digest.update(chunk)
        records.append({'filename': filename, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest(), 'url': url})
    result = {'model_id': name, 'revision': model['revision'], 'license': model['license'], 'files': records}
    (BASE / ('download-' + name.replace('/', '--') + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    print('READY', name, flush=True)
    return result


if __name__ == '__main__':
    models = json.loads((BASE / 'model-sources.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(fetch, models))
    (BASE / 'model-downloads.json').write_text(json.dumps(results, indent=2) + '\n')
