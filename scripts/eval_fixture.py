"""Strict adapter for legacy observation summaries, not a PromQL evaluator.

Syntax is parsed by promql-parser. Unsupported valid expressions/unknown label
facts are explicitly ungraded rather than assigned a fabricated numeric result.
"""
import json
import re
import sys

import promql_parser as p


def result(status, data):
    return {"status": status, "data": data}


def verify(scene, name, labels):
    alert = scene["alert"]
    if name != alert["name"] or labels != alert.get("labels", {}):
        return {"status": "UNKNOWN"}
    return scene["mocks"]["verify"]


def matcher_matches(matcher, value):
    op = str(matcher.op)
    if op in ("MatchOp.Equal", "MatchOp.NotEqual"):
        equal = value == matcher.value
        return equal if op == "MatchOp.Equal" else not equal
    equal = re.fullmatch(matcher.value, value) is not None
    return equal if op == "MatchOp.Re" else not equal


def query(scene, expression):
    try:
        expr = p.parse(expression)
    except (ValueError, TypeError) as exc:
        return result("invalid_argument", str(exc))
    while isinstance(expr, p.ParenExpr):
        expr = expr.expr
    if not isinstance(expr, p.VectorSelector):
        return result("unsupported_fixture", "유효한 PromQL이지만 기존 설명형 fixture로 계산할 수 없음")
    if expr.offset is not None or expr.at is not None or expr.matchers.or_matchers:
        return result("unsupported_fixture", "fixture에 시각 변경/OR 선택을 계산할 상태가 없음")
    names = scene["mocks"].get("metrics", [])
    selected = [name for name in names if expr.name is None or name == expr.name]
    if not selected:
        return result("empty", "정의된 메트릭 없음")
    observations = []
    unknown = False
    for name in selected:
        try:
            if any(not matcher_matches(m, name) for m in expr.matchers.matchers if m.name == "__name__"):
                continue
        except re.error:
            return result("unsupported_fixture", "지원하지 않는 정규식 선택")
        entries = [e for e in scene["mocks"].get("prometheus", [])
                   if name == e["keyword"]
                   or re.search(r"\b" + re.escape(name) + r"(?=\{|:)", e["response"])]
        entries.sort(key=lambda e: len(e["keyword"]), reverse=True)
        if not entries:
            unknown = True
            continue
        text = entries[0]["response"]
        labels = {}
        # Only explicit equality labels on this metric are facts. Do not guess job,
        # mode, or target values from a family keyword or historical narrative.
        label_sets = list(re.finditer(r"\b" + re.escape(name) + r"\{([^}]+)\}", text))
        if len(label_sets) > 1 and any(m.name != "__name__" for m in expr.matchers.matchers):
            return result("unsupported_fixture", "요약에 여러 시계열이 있어 대상별 결과를 분리할 수 없음")
        match = label_sets[0] if label_sets else None
        if match:
            for pair in match[1].split(","):
                m = re.fullmatch(r'\s*(\w+)\s*=\s*("[^"]*"|[^\s,!=~]+)\s*', pair)
                if m:
                    labels[m[1]] = m[2].strip('"')
        labels["__name__"] = name
        matches = True
        for matcher in expr.matchers.matchers:
            if matcher.name not in labels:
                unknown = True
                matches = False
                break
            value = str(labels[matcher.name])
            op = str(matcher.op)
            if op in ("MatchOp.Equal", "MatchOp.NotEqual"):
                equal = value == matcher.value
                matches = matches and (equal if op == "MatchOp.Equal" else not equal)
            else:
                try:
                    equal = re.fullmatch(matcher.value, value) is not None
                except re.error:
                    return result("unsupported_fixture", "지원하지 않는 정규식 선택")
                matches = matches and (equal if op == "MatchOp.Re" else not equal)
        if matches:
            if "데이터 없음" in text:
                continue
            observations.append(text)
    if unknown:
        return result("unsupported_fixture", "fixture에 필요한 메트릭 관측 또는 레이블 사실이 없음")
    if not observations:
        return result("empty", "대상 조건에 맞는 관측 없음")
    return result("observation", "기존 시나리오의 관측 요약 (PromQL 계산 결과가 아님):\n" + "\n".join(dict.fromkeys(observations)))


def main():
    request = json.load(sys.stdin)
    if request.get("action") == "preflight":
        response = result("ready", "promql-parser")
    elif request.get("action") == "verify":
        response = verify(request["scenario"], request["name"], request["labels"])
    else:
        response = query(request["scenario"], request["query"])
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
