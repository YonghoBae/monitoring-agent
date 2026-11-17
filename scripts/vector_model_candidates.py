"""Pinned local inference adapters following each author's published pooling/scoring."""
import gc
import json
import os
from pathlib import Path
import time

os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['HF_HUB_OFFLINE'] = '1'
import numpy as np
import torch
from transformers import AutoModel, AutoModelForCausalLM, AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'eval/vector-v3-improvement'
TASK = 'Given a server troubleshooting query, retrieve existing questions describing the same underlying problem.'
MODELS = {'e5': 'intfloat/multilingual-e5-small', 'bge': 'BAAI/bge-m3', 'qwen': 'Qwen/Qwen3-Embedding-0.6B',
          'bge-reranker': 'BAAI/bge-reranker-v2-m3', 'qwen-reranker': 'Qwen/Qwen3-Reranker-0.6B'}
torch.set_num_threads(2)


def checkpoint_path(alias):
    entry = next(x for x in json.loads((BASE / 'model-sources.json').read_text()) if x['model_id'] == MODELS[alias])
    assert (BASE / ('download-' + entry['model_id'].replace('/', '--') + '.json')).exists(), 'Model download is incomplete'
    return ROOT / '.cache-vector-models' / entry['model_id'].replace('/', '--') / entry['revision']


class Candidate:
    def __init__(self, alias, precision='float32'):
        self.alias = alias
        self.precision = precision
        path = str(checkpoint_path(alias))
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False,
                                                       padding_side='left' if alias.startswith('qwen') else 'right')
        dtype = getattr(torch, precision)
        cls = AutoModelForCausalLM if alias == 'qwen-reranker' else AutoModelForSequenceClassification if alias == 'bge-reranker' else AutoModel
        self.model = cls.from_pretrained(path, local_files_only=True, trust_remote_code=False,
                                        torch_dtype=dtype, attn_implementation='eager').eval().to('cuda')
        if alias == 'qwen-reranker':
            prefix = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
            suffix = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
            self.prefix = self.tokenizer.encode(prefix, add_special_tokens=False)
            self.suffix = self.tokenizer.encode(suffix, add_special_tokens=False)
            self.yes = self.tokenizer.convert_tokens_to_ids('yes')
            self.no = self.tokenizer.convert_tokens_to_ids('no')

    def close(self):
        del self.model
        gc.collect()
        torch.cuda.empty_cache()

    @torch.inference_mode()
    def embed(self, texts, query=False, max_length=256):
        if self.alias == 'e5':
            texts = [('query: ' if query else 'passage: ') + s for s in texts]
        elif self.alias == 'qwen' and query:
            texts = ['Instruct: ' + TASK + '\nQuery: ' + s for s in texts]
        encoded = self.tokenizer(texts, padding=True, truncation=True, max_length=max_length, return_tensors='pt').to('cuda')
        output = self.model(**encoded, **({'use_cache': False} if self.alias == 'qwen' else {})).last_hidden_state
        mask = encoded['attention_mask']
        if self.alias == 'e5':
            hidden = output.masked_fill(~mask[..., None].bool(), 0.0)
            pooled = hidden.sum(dim=1) / mask.sum(dim=1)[..., None]
        elif self.alias == 'bge':
            pooled = output[:, 0]
        else:
            assert (mask[:, -1] == 1).all()
            pooled = output[:, -1]
        normalized = torch.nn.functional.normalize(pooled.float(), p=2, dim=1)
        result = normalized.cpu().numpy()
        assert np.isfinite(result).all() and (np.linalg.norm(result, axis=1) > .99).all()
        return result

    @torch.inference_mode()
    def rerank(self, queries, documents, max_length=512):
        if self.alias == 'bge-reranker':
            encoded = self.tokenizer(list(zip(queries, documents)), padding=True, truncation=True, max_length=max_length, return_tensors='pt').to('cuda')
            result = self.model(**encoded).logits.float().view(-1).cpu().numpy()
        else:
            texts = ['<Instruct>: ' + TASK + '\n<Query>: ' + q + '\n<Document>: ' + d for q, d in zip(queries, documents)]
            encoded = self.tokenizer(texts, padding=False, truncation=True,
                                     max_length=max_length - len(self.prefix) - len(self.suffix), add_special_tokens=False)
            batch = [{'input_ids': self.prefix + ids + self.suffix} for ids in encoded['input_ids']]
            batch = self.tokenizer.pad(batch, padding=True, return_tensors='pt').to('cuda')
            logits = self.model(**batch, use_cache=False, logits_to_keep=1).logits[:, -1, :].float()
            result = torch.softmax(torch.stack([logits[:, self.no], logits[:, self.yes]], dim=1), dim=1)[:, 1].cpu().numpy()
        assert np.isfinite(result).all()
        return result


def profile(alias):
    path = BASE / 'profiles' / (alias + '.json')
    if path.exists():
        return json.loads(path.read_text())
    docs = json.loads((BASE / 'cache/development-documents.json').read_text())
    queries = json.loads((BASE / 'cache/development-queries.json').read_text())
    texts = [d['title'] + '\n' + d['text'] for d in docs[:32]]
    records = []
    for precision in ['float32', 'float16']:
        model = None
        try:
            torch.cuda.reset_peak_memory_stats()
            loaded = time.monotonic()
            model = Candidate(alias, precision)
            load_seconds = time.monotonic() - loaded
            batch_size = 4 if alias == 'e5' else 2
            function = (lambda batch: model.rerank([queries[0]['text']] * len(batch), batch)) if 'reranker' in alias else model.embed
            function(texts[:batch_size])
            torch.cuda.synchronize()
            start = time.monotonic()
            for offset in range(0, len(texts), batch_size):
                function(texts[offset:offset + batch_size])
            torch.cuda.synchronize()
            seconds = time.monotonic() - start
            records.append({'precision': precision, 'status': 'pass', 'items': len(texts), 'seconds': seconds,
                            'seconds_per_item': seconds / len(texts), 'batch_size': batch_size,
                            'load_seconds': load_seconds, 'peak_allocated_mib': torch.cuda.max_memory_allocated() / 1024**2})
        except Exception as error:
            records.append({'precision': precision, 'status': 'failed', 'error_type': type(error).__name__, 'error': str(error)[:700]})
        finally:
            if model is not None:
                model.close()
            gc.collect()
            torch.cuda.empty_cache()
    passed = [r for r in records if r['status'] == 'pass']
    best = min(passed, key=lambda r: r['seconds_per_item']) if passed else None
    result = {'alias': alias, 'model_id': MODELS[alias], 'gpu': torch.cuda.get_device_name(), 'measurements': records,
              'selected': best, 'selection': 'fastest finite precision on same 32 smoke inputs, before relevance scores', 'task_instruction': TASK}
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    import sys
    profile(sys.argv[1])
