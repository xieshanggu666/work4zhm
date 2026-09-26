"""协作远征查询接口的成员身份校验（读侧权限边界）。

背景：协作查询接口曾经只凭队伍/远征 id 即可读取——队伍状态（成员/角色）、
行动记录（时间线/逐章回放）与成员贡献（ledger）对任何拿到 id 的人裸露。
修复后所有协作读接口与写动作/增量同步同一权限边界：

- 未带 member_id / 成员不存在 / 他队成员 -> 403，零副作用；
- 本队成员 -> 200，视口正常下发；
- 单人远征/普通局无账号体系，行为不变（回归保障）。

覆盖端点：队伍视口、协作续局、协作整程回放、远征视口/整程回放（协作）、
章节 run 的 get/resume/replay（协作）。
"""
from tests.test_coop import _make_team, _squad


def _foreign_member(client):
    """另一支队伍的队长 id（用于「他队成员」越权场景）。"""
    _, other_leader, _ = _make_team(client, captain="外人", seed=99)
    return other_leader


# ---------- 队伍视口 GET /api/coop/teams/{id} ----------
def test_team_view_requires_membership(client):
    squad = _squad(client)
    tid = squad["team_id"]
    # 未带身份 / 伪造成员 / 他队成员 -> 403，且响应不含任何队伍数据
    for bad in (None, "m_nobody", _foreign_member(client)):
        r = client.get(f"/api/coop/teams/{tid}",
                       params={"member_id": bad} if bad else {})
        assert r.status_code == 403
        assert "members" not in r.json() and "events" not in r.json()
    # 本队任意成员 -> 200
    for mid in (squad["leader_id"], squad["supply_id"], squad["combat_id"]):
        r = client.get(f"/api/coop/teams/{tid}", params={"member_id": mid})
        assert r.status_code == 200
        assert r.json()["me"]["id"] == mid
    # 不存在的队伍 -> 400
    assert client.get("/api/coop/teams/t_none",
                      params={"member_id": squad["leader_id"]}
                      ).status_code == 400


def test_team_view_forming_also_guarded(client):
    """组队中（未开赛）同样拦截：大厅成员列表/入队码不向外泄露。"""
    team, leader_id, _ = _make_team(client)
    r = client.get(f"/api/coop/teams/{team['id']}")
    assert r.status_code == 403
    r = client.get(f"/api/coop/teams/{team['id']}",
                   params={"member_id": leader_id})
    assert r.status_code == 200


# ---------- 协作续局 GET /api/coop/teams/{id}/expedition ----------
def test_team_expedition_requires_membership(client):
    squad = _squad(client)
    tid = squad["team_id"]
    for bad in (None, "m_nobody", _foreign_member(client)):
        r = client.get(f"/api/coop/teams/{tid}/expedition",
                       params={"member_id": bad} if bad else {})
        assert r.status_code == 403
        assert "run" not in r.json() and "team" not in r.json()
    r = client.get(f"/api/coop/teams/{tid}/expedition",
                   params={"member_id": squad["supply_id"]})
    assert r.status_code == 200
    assert r.json()["run"]["run_id"] == squad["run_id"]


def test_team_expedition_forming_also_guarded(client):
    team, leader_id, _ = _make_team(client)
    assert client.get(f"/api/coop/teams/{team['id']}/expedition").status_code == 403
    r = client.get(f"/api/coop/teams/{team['id']}/expedition",
                   params={"member_id": leader_id})
    assert r.status_code == 200 and r.json()["run"] is None


# ---------- 协作整程回放 GET /api/coop/teams/{id}/replay ----------
def test_team_replay_requires_membership(client):
    squad = _squad(client)
    tid = squad["team_id"]
    for bad in (None, "m_nobody", _foreign_member(client)):
        r = client.get(f"/api/coop/teams/{tid}/replay",
                       params={"member_id": bad} if bad else {})
        assert r.status_code == 403
        # 行动记录与成员贡献绝不外泄
        assert "events" not in r.json() and "ledger" not in r.json()
    r = client.get(f"/api/coop/teams/{tid}/replay",
                   params={"member_id": squad["combat_id"]})
    assert r.status_code == 200
    assert r.json()["team"]["id"] == tid


# ---------- 远征视口/整程回放（协作） ----------
def test_coop_expedition_view_and_replay_require_membership(client):
    squad = _squad(client)
    exp_id = squad["expedition_id"]
    for path in (f"/api/expeditions/{exp_id}", f"/api/expeditions/{exp_id}/replay"):
        for bad in (None, "m_nobody", _foreign_member(client)):
            r = client.get(path, params={"member_id": bad} if bad else {})
            assert r.status_code == 403, path
            assert "expedition" not in r.json()
        r = client.get(path, params={"member_id": squad["leader_id"]})
        assert r.status_code == 200, path


def test_solo_expedition_endpoints_unchanged(client):
    """单人远征无账号体系：不带 member_id 行为不变（回归保障）。"""
    r = client.post("/api/expeditions", json={"seed": 3, "chapters": 1})
    exp_id = r.json()["expedition"]["id"]
    assert client.get(f"/api/expeditions/{exp_id}").status_code == 200
    assert client.get(f"/api/expeditions/{exp_id}/replay").status_code == 200


# ---------- 章节 run 的 get/resume/replay（协作） ----------
def test_coop_run_read_endpoints_require_membership(client):
    squad = _squad(client)
    rid = squad["run_id"]
    for path in (f"/api/runs/{rid}", f"/api/runs/{rid}/resume",
                 f"/api/runs/{rid}/replay"):
        for bad in (None, "m_nobody", _foreign_member(client)):
            r = client.get(path, params={"member_id": bad} if bad else {})
            assert r.status_code == 403, path
        r = client.get(path, params={"member_id": squad["combat_id"]})
        assert r.status_code == 200, path


def test_solo_run_read_endpoints_unchanged(client):
    """普通局读接口无需身份（回归保障）。"""
    rid = client.post("/api/runs", json={"seed": 5}).json()["run_id"]
    assert client.get(f"/api/runs/{rid}").status_code == 200
    assert client.get(f"/api/runs/{rid}/resume").status_code == 200
    assert client.get(f"/api/runs/{rid}/replay").status_code == 200


# ---------- 越权读取零副作用 ----------
def test_unauthorized_reads_have_zero_side_effects(client):
    """越权 403 后权威视口与游标不变（读接口本就只读，此处锁定语义）。"""
    squad = _squad(client)
    tid = squad["team_id"]
    before = client.get(f"/api/coop/teams/{tid}",
                        params={"member_id": squad["leader_id"]}).json()
    # 连续越权访问各读接口
    client.get(f"/api/coop/teams/{tid}")
    client.get(f"/api/coop/teams/{tid}/expedition")
    client.get(f"/api/coop/teams/{tid}/replay")
    client.get(f"/api/expeditions/{squad['expedition_id']}")
    client.get(f"/api/runs/{squad['run_id']}/resume")
    after = client.get(f"/api/coop/teams/{tid}",
                       params={"member_id": squad["leader_id"]}).json()
    assert after == before
