import json
from pathlib import Path
import random
import time

import adaptive_difficulty as adaptive
import puzzle_engine as engine


def boards():
    return [dict(size=len(row['regions']), difficulty='expert', points=100, regions=row['regions'],
                 solution=row['solution'])
            for row in json.loads((Path(__file__).parents[1]/'docs/research/difficulty-probe.json').read_text())
            if row['level'] == 'expert']


def test_weights_are_soft_monotone_tie_and_order_invariant():
    assert adaptive.candidate_weights([10, 20, 30], 0) == [1, 1, 1]
    assert adaptive.candidate_weights([10, 20, 30], 20) == [1, 1.4, 1.8]
    assert adaptive.candidate_weights([30, 10, 20, 20], 20) == [1.8, 1, 1.4, 1.4]
    assert adaptive.candidate_weights([10, 10], 20) == [1, 1]
    assert adaptive.candidate_weights([10, 20], 200) == [1, 1.8]
    assert adaptive.candidate_weights([10, 20], -1) == [1, 1]
    means = []
    for streak in [0, 5, 10, 20]:
        rng = random.Random(42)
        draws = [adaptive.choose_candidate([10,20,30], [10,20,30], streak, rng) for _ in range(20000)]
        means.append(sum(draws)/len(draws))
        assert 0.2 < draws.count(10)/len(draws) < 0.36
    assert means == sorted(means) and len(set(means)) == 4


def test_complete_score_does_not_read_stored_solution_and_budget_can_stop():
    regions = boards()[0]['regions']
    adaptive._scores.clear()
    assert adaptive.score_regions(regions, deadline=time.monotonic()-1) is None
    assert not adaptive._scores
    score = adaptive.score_regions(regions)
    assert type(score) is int and score > 0
    assert adaptive.score_regions(regions) == score


def test_stalled_proof_not_scored_as_easy(monkeypatch):
    adaptive._scores.clear()
    monkeypatch.setattr(adaptive, 'next_hint', lambda *args: None)
    assert adaptive.score_regions(boards()[0]['regions']) is None


def test_generator_selects_final_candidate_and_only_records_selected_family(monkeypatch):
    samples = boards()[:3]
    monkeypatch.setattr(engine, '_expert_seeds', {'expert': engine.deque(samples, maxlen=32)})
    monkeypatch.setattr(engine, '_recent_families', {})
    monkeypatch.setattr(engine, '_generation_counts', {'expert':1})
    monkeypatch.setattr(engine, 'vary_expert', lambda seed, rng, deadline=None: dict(seed, fingerprint=engine.fingerprint(seed['regions'])))
    measured = []
    def score(regions, deadline=None):
        measured.append(regions)
        return len(measured)*10
    monkeypatch.setattr(engine, 'score_regions', score)
    selected = []
    def choose(candidates, scores, streak, rng):
        assert streak == 7 and scores == [10,20,30]
        selected.extend(candidates)
        return candidates[-1]
    monkeypatch.setattr(engine, 'choose_candidate', choose)
    result = engine.generate('expert', streak=7)
    assert len(measured) == 3
    assert result['regions'] == selected[-1]['regions']
    assert list(engine._recent_families['expert']) == [engine.solution_family(result['solution'])]


def test_all_unscored_candidates_keep_valid_normal_fallback(monkeypatch):
    sample = boards()[0]
    monkeypatch.setattr(engine, '_expert_seeds', {'expert':engine.deque([sample], maxlen=32)})
    monkeypatch.setattr(engine, '_recent_families', {})
    monkeypatch.setattr(engine, '_generation_counts', {'expert':1})
    monkeypatch.setattr(engine, 'vary_expert', lambda seed, rng, deadline=None: dict(seed, fingerprint=engine.fingerprint(seed['regions'])))
    monkeypatch.setattr(engine, 'score_regions', lambda *args, **kwargs: None)
    result = engine.generate('expert', streak=20)
    assert engine.solutions(result['regions']) == [result['solution']]


def test_api_uses_server_streak_only_for_new_expert(monkeypatch):
    adaptive._scores.clear()
    import uuid
    import main
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from models import Base
    database = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(database)
    monkeypatch.setattr(main, 'engine', database)
    calls = []
    sample = boards()[0]
    sample['fingerprint'] = engine.fingerprint(sample['regions'])
    def generate(level, **kwargs):
        calls.append((level, kwargs))
        return sample if level == 'expert' else engine.generate(level, random.Random(4))
    monkeypatch.setattr(main, 'generate', generate)
    monkeypatch.setattr(main, 'derive_streaks', lambda session, player: dict.fromkeys(engine.LEVELS,7))
    with TestClient(main.app) as client:
        assert client.post('/api/profile', json={'name':'test'}).status_code == 200
        assert client.post('/api/games', json={'difficulty':'easy','request_id':str(uuid.uuid4())}).status_code == 200
        assert calls == [('easy',{})]
        request = {'difficulty':'expert', 'request_id':str(uuid.uuid4())}
        response = client.post('/api/games', json=request)
        assert response.status_code == 200
        game = response.json()
        assert calls[-1] == ('expert',{'streak':7})
        count = len(calls)
        assert client.post('/api/games', json=request).json()['id'] == game['id']
        shared = client.post('/api/games', json={'puzzle_id':game['puzzle']['id'],'request_id':str(uuid.uuid4())})
        assert shared.status_code == 200 and shared.json()['id'] == game['id']
        wrong = (sample['solution'][0]+1)%9
        assert client.post(f"/api/games/{game['id']}/stars",json={'row':0,'col':wrong,'request_id':str(uuid.uuid4())}).status_code == 200
        assert client.post(f"/api/games/{game['id']}/retry", json={}).status_code == 200
        assert len(calls) == count
        assert 'solution' not in game['puzzle']
        assert game['puzzle']['difficulty_rating']['rank'] in ['入門','初級','中級','上級','達人']
        assert type(game['puzzle']['difficulty_rating']['score']) is int
    database.dispose()


def test_extra_variation_honors_expired_budget(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No solving work after expired deadline')
    monkeypatch.setattr(engine, 'solutions', forbidden)
    assert engine.vary_expert(boards()[0], random.Random(7), deadline=time.monotonic()-1) is None


def test_five_rating_boundaries(monkeypatch):
    for score, rank in [(0,'入門'),(29,'入門'),(30,'初級'),(49,'初級'),
                        (50,'中級'),(69,'中級'),(70,'上級'),(89,'上級'),(90,'達人'),(108,'達人')]:
        monkeypatch.setattr(adaptive, 'score_regions', lambda *a, **kw: score)
        assert adaptive.difficulty_rating([]) == {'rank':rank,'score':score}
    monkeypatch.setattr(adaptive, 'score_regions', lambda *a, **kw: None)
    assert adaptive.difficulty_rating([]) is None
