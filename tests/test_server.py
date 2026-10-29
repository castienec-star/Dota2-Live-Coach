from coach.gsi_server import Coach, make_app
from coach.recorder import MatchRecorder, read_recording


async def test_accepts_update_with_token(aiohttp_client, payload):
    coach = Coach("test-token")
    seen = []
    coach.listeners.append(lambda state: seen.append(state.current.gold))
    client = await aiohttp_client(make_app(coach))

    resp = await client.post("/", json=payload)
    assert resp.status == 200
    assert coach.state.current.gold == 1640
    assert seen == [1640]


async def test_rejects_wrong_token(aiohttp_client, payload):
    coach = Coach("test-token")
    client = await aiohttp_client(make_app(coach))
    payload["auth"]["token"] = "nope"

    resp = await client.post("/", json=payload)
    assert resp.status == 401
    assert coach.state.current.match_id is None


async def test_rejects_bad_json(aiohttp_client):
    client = await aiohttp_client(make_app(Coach("test-token")))
    resp = await client.post("/", data=b"not json", headers={"Content-Type": "application/json"})
    assert resp.status == 400
    resp = await client.post("/", json=[1, 2])
    assert resp.status == 400


async def test_records_match_without_token(aiohttp_client, payload, tmp_path):
    recorder = MatchRecorder(tmp_path)
    coach = Coach("test-token", recorder)
    client = await aiohttp_client(make_app(coach))

    await client.post("/", json=payload)
    await client.post("/", json=payload)
    recorder.close()

    entries = list(read_recording(recorder.path))
    assert len(entries) == 2
    assert "auth" not in entries[0][1]
    assert recorder.path.name.endswith("match-8012345678.jsonl")


def test_recording_keeps_spoken_lines_apart_from_updates(payload, tmp_path):
    from coach.recorder import read_lines

    recorder = MatchRecorder(tmp_path)
    recorder.start("1")
    recorder.write(payload)
    recorder.said("Power rune in 15 seconds.", 345)
    recorder.said("Stack the camp.", 353, spoken=False)
    recorder.close()

    assert len(list(read_recording(recorder.path))) == 1
    assert list(read_lines(recorder.path)) == [
        (345, "Power rune in 15 seconds.", True),
        (353, "Stack the camp.", False),
    ]


def test_said_before_a_match_is_ignored(tmp_path):
    recorder = MatchRecorder(tmp_path)
    recorder.said("Dota is connected.", None)
    assert recorder.path is None
