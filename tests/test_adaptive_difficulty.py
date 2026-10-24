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


def test_streak_target_climbs_one_rank_per_three_wins():
    assert [adaptive.target_score(s) for s in [-1, 0, 3, 6, 9, 12, 30]] == [20, 20, 40, 60, 80, 100, 105]


def test_weights_favour_nearest_score_with_ties_and_soft_tail():
    assert adaptive.candidate_weights([20, 40, 60], 0) == [1, .3, .3**2]
    assert adaptive.candidate_weights([60, 20, 40, 40], 3) == [.3, .3, 1, 1]
    assert adaptive.candidate_weights([10, 10], 20) == [1, 1]
    means = []
    for streak in [0, 3, 6, 9]:
        rng = random.Random(42)
        draws = [adaptive.choose_candidate([20,40,60,80], [20,40,60,80], streak, rng) for _ in range(20000)]
        means.append(sum(draws)/len(draws))
        # The nearest board dominates, but others still appear.
        assert 0.5 < draws.count(adaptive.target_score(streak))/len(draws) < 0.8
        assert len(set(draws)) == 4
    assert means == sorted(means) and len(set(means)) == 4


def test_master_boards_wait_for_ten_clear_streak():
    rng = random.Random(3)
    for streak in [0, 3, 9]:
        assert {adaptive.choose_candidate(['a','b','c'], [40, 95, 120], streak, rng) for _ in range(300)} == {'a'}
    assert 'c' in {adaptive.choose_candidate(['a','b','c'], [40, 95, 120], 10, rng) for _ in range(300)}
    # With nothing easier available the board is still served.
    assert adaptive.choose_candidate(['b'], [95], 0, rng) == 'b'


def test_generator_looks_for_an_allowed_board_when_all_are_master(monkeypatch):
    samples = boards()[:3]
    monkeypatch.setattr(engine, '_expert_seeds', {'expert': engine.deque(samples, maxlen=32)})
    monkeypatch.setattr(engine, '_recent_families', {})
    monkeypatch.setattr(engine, '_generation_counts', {'expert':1})
    monkeypatch.setattr(engine, 'vary_expert', lambda seed, rng, deadline=None: dict(seed, fingerprint=engine.fingerprint(seed['regions'])))
    measured = []
    def score(regions, deadline=None):
        measured.append(regions)
        return 100 if len(measured) <= 3 else 50
    monkeypatch.setattr(engine, 'score_regions', score)
    picked = []
    monkeypatch.setattr(engine, 'choose_candidate', lambda c, s, streak, rng: picked.append(s) or c[-1])
    engine.generate('expert', streak=3)
    assert picked == [[100, 100, 100, 50]]


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
    monkeypatch.setattr(engine, 'WALK_TOLERANCE', 1000)
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


def test_rank_points_follow_complete_score(monkeypatch):
    for score, points in [(0,100),(29,100),(30,150),(50,200),(70,250),(89,250),(90,300),(130,300)]:
        monkeypatch.setattr(adaptive, 'score_regions', lambda *a, **kw: score)
        assert adaptive.rated_points([]) == points
    monkeypatch.setattr(adaptive, 'score_regions', lambda *a, **kw: None)
    assert adaptive.rated_points([]) == 100


def test_expert_clear_awards_rank_points(monkeypatch):
    import uuid
    import main
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from models import Base, Puzzle
    database = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(database)
    monkeypatch.setattr(main, 'engine', database)
    sample = boards()[0]
    with Session(database) as session:
        session.add(Puzzle(id='e'*32, difficulty='expert', size=9, points=100, regions=sample['regions'],
                           solution=sample['solution'], fingerprint=engine.fingerprint(sample['regions'])))
        session.commit()
    expected = adaptive.RANK_POINTS[adaptive.rank_for(adaptive.score_regions(sample['regions']))]
    with TestClient(main.app) as client:
        assert client.post('/api/profile', json={'name':'rank'}).status_code == 200
        game = client.post('/api/games', json={'request_id':str(uuid.uuid4()),'puzzle_id':'e'*32}).json()
        assert game['puzzle']['points'] == expected
        for r, c in enumerate(sample['solution']):
            result = client.post(f"/api/games/{game['id']}/stars", json={'row':r,'col':c,'request_id':str(uuid.uuid4())}).json()
        assert result['game']['completed'] and result['game']['score'] == expected
        assert client.get('/api/me').json()['points'] == expected
    database.dispose()


def test_rank_weights_step_one_rank_per_three_wins_and_hold_master():
    all_ranks = adaptive.RANKS
    assert adaptive.rank_weights(all_ranks, 0) == {'入門':1, '初級':.3, '中級':.3**2, '上級':.3**3}
    assert max(adaptive.rank_weights(all_ranks, 6).items(), key=lambda kv: kv[1])[0] == '中級'
    assert max(adaptive.rank_weights(all_ranks, 9).items(), key=lambda kv: kv[1])[0] == '上級'
    assert '達人' not in adaptive.rank_weights(all_ranks, 9)
    assert max(adaptive.rank_weights(all_ranks, 12).items(), key=lambda kv: kv[1])[0] == '達人'
    # Only master boards ready: still serve one rather than nothing.
    assert adaptive.rank_weights(['達人'], 0) == {'達人': .3**4}


def test_pooled_boards_follow_streak_rank(monkeypatch):
    pool = {rank: engine.deque() for rank in adaptive.RANKS}
    monkeypatch.setattr(engine, '_pool', pool)
    rng = random.Random(5)
    def refill():
        for rank in adaptive.RANKS:
            while len(pool[rank]) < 2:
                pool[rank].append({'rank': rank})
    picks = {}
    for streak in [0, 6, 12]:
        drawn = []
        for _ in range(400):
            refill()
            drawn.append(engine.take_pooled(streak, rng)['rank'])
        picks[streak] = max(set(drawn), key=drawn.count)
        assert drawn.count(picks[streak]) / len(drawn) > .55
        if streak < 10:
            assert '達人' not in drawn
    assert picks == {0: '入門', 6: '中級', 12: '達人'}
    for rank in adaptive.RANKS:
        pool[rank].clear()
    assert engine.take_pooled(12, rng) is None
