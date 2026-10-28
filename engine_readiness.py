"""Choose a safe, installed language pair for a one-time engine warm-up."""
SAMPLES={'ko':'안녕하세요.','en':'Hello.','ja':'こんにちは。'}

def choose_probe(source,targets,resolve):
    sources=('ko','en','ja') if source=='auto' else (source,)
    for target in targets:
        for src in sources:
            if src==target:continue
            try:resolve(src,target)
            except ValueError:continue
            return src,target
    raise ValueError('설정된 번역 방향에 필요한 언어팩이 없습니다.')

def choose_probes(source,targets,resolve):
    return [choose_probe(source,[target],resolve) for target in dict.fromkeys(targets)]

def warm(source,target,translate):
    result=translate(SAMPLES[source],source,target)
    if not isinstance(result,str) or not result.strip():
        raise ValueError('번역 엔진이 빈 결과를 반환했습니다.')
    return result
