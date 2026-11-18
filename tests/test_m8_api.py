import threading
import app.store as store
from app.errors import DomainError


LOW_PASS_CSV = '''lot,batch,mass,unit,moisture,element,assay,basis,revision
L1,B9,100,kg,1,Cu,9,dry,1
L1,B9,100,kg,1,Zn,5,dry,1
L2,B9,100,kg,1,Cu,10,dry,1
L2,B9,100,kg,1,Zn,5,dry,1
'''
ORDERS_CSV = (
    'order_id,grade,batch,cutoff\n'
    'O-LOW,低牌号,B9,2099-01-01T00:00:00Z\n'
    'O-HIGH,高牌号,B9,2099-01-02T00:00:00Z\n'
)


def _run(client):
    return client.post('/api/run', json={
        'csv': LOW_PASS_CSV, 'orders': ORDERS_CSV,
        'now': '2026-11-18T12:00:00Z', 'retest_hours': 8,
    }).get_json()


def test_m8_page_and_stage_endpoint(client):
    run = _run(client)
    assert client.post('/api/m8', json={}).status_code == 200
    page = client.get('/work/8?run_id=' + run['manifest']['run_id']).data.decode()
    assert '截单裁决' in page and '完整区间' in page and '订单截单' in page
    assert run['stages']['8']['stage'] == 8


def test_decision_visible_on_page_with_basis(client):
    run = _run(client)
    page = client.get('/work/8?run_id=' + run['manifest']['run_id']).data.decode()
    assert '截单裁决' in page and '放行' in page
    assert '9.5~9.5' in page  # 完整区间数值直接展示，判定依据可复核


def test_release_created_once_and_retry_returns_same_form(client):
    run = _run(client)
    rid = run['manifest']['run_id']
    payload = {'run_id': rid, 'batch': 'B9', 'grade': '低牌号', 'idem_key': 'key-1'}
    first = client.post('/api/releases', json=payload)
    assert first.status_code == 201
    again = client.post('/api/releases', json=payload)
    # 重试不新增放行单：返回同一张单，表中仍只有一份
    assert again.get_json()['id'] == first.get_json()['id']
    assert len(client.get('/api/releases').get_json()) == 1


def test_concurrent_same_batch_only_one_release(client):
    run = _run(client)
    rid = run['manifest']['run_id']
    results, barrier = [], threading.Barrier(4)

    def worker(idx):
        barrier.wait()
        resp = client.post('/api/releases', json={
            'run_id': rid, 'batch': 'B9', 'grade': '低牌号', 'idem_key': 'concurrent-%d' % idx})
        results.append(resp.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results).count(201) == 1
    assert sorted(results).count(409) == 3
    assert len(client.get('/api/releases?batch=B9').get_json()) == 1


def test_different_grades_same_batch_second_is_conflict(client):
    run = _run(client)
    rid = run['manifest']['run_id']
    low = client.post('/api/releases', json={'run_id': rid, 'batch': 'B9', 'grade': '低牌号', 'idem_key': 'a'})
    high = client.post('/api/releases', json={'run_id': rid, 'batch': 'B9', 'grade': '高牌号', 'idem_key': 'b'})
    assert low.status_code == 201 and high.status_code == 409
    assert high.get_json()['code'] == 'RELEASE_CONFLICT'


def test_pending_grade_release_rejected_by_server(client):
    # 样例炉次两牌号均待确认，服务端不得放行
    run = client.post('/api/run', json={'now': '2026-11-18T12:00:00Z'}).get_json()
    batch = run['stages']['8']['rows'][0]['炉次']
    resp = client.post('/api/releases', json={
        'run_id': run['manifest']['run_id'], 'batch': batch, 'grade': '低牌号', 'idem_key': 'x'})
    assert resp.status_code == 422 and resp.get_json()['code'] == 'RELEASE'


def test_idem_key_reused_for_different_request_conflicts(client):
    run = _run(client)
    rid = run['manifest']['run_id']
    client.post('/api/releases', json={'run_id': rid, 'batch': 'B9', 'grade': '低牌号', 'idem_key': 'same'})
    # 同一幂等键改报高牌号：判定为冲突，不得新开单
    resp = client.post('/api/releases', json={'run_id': rid, 'batch': 'B9', 'grade': '高牌号', 'idem_key': 'same'})
    assert resp.status_code == 409 and resp.get_json()['code'] == 'IDEMPOTENT'
    assert len(client.get('/api/releases?batch=B9').get_json()) == 1


def test_store_unique_constraint_direct(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv('APP_DB', str(tmp_path / 's.sqlite3'))
    form = {'batch': 'BX', 'grade': '低牌号', 'run_id': 'r1', 'order_id': 'o1', 'idem_key': 'k1'}
    first = store.create_release(form)
    with pytest.raises(DomainError) as exc:
        store.create_release({**form, 'idem_key': 'k2'})
    assert exc.value.status == 409 and exc.value.code == 'RELEASE_CONFLICT'
    # 同幂等键重试仍返回原单
    assert store.create_release(form)['id'] == first['id']
    assert len(store.list_releases('BX')) == 1
