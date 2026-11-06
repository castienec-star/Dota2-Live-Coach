import json

import pytest

from coach import lessons
from coach.lessons import Chunk, Lesson, card, chunks, learn, load, matching


def test_speech_is_cut_into_stretches():
    segs = [(0, 5, "Look at this."), (5, 12, "He keeps his wand charges."), (12, 24, "Then the lotus fight."),
            (24, 30, " "), (30, 41, "Now the next thing.")]
    out = list(chunks(segs, seconds=20))
    assert [(c.start, c.end) for c in out] == [(0, 12), (12, 24), (30, 41)]
    assert out[0].text == "Look at this. He keeps his wand charges."


def test_card_reads_the_models_json():
    chunk = Chunk(754, 770, "Keep those wand charges for the lotus fight.")
    reply = json.dumps({"skip": False, "situation": "Lane at 4:00, 15 wand charges", "point": "He saved the charges",
                        "why": "They win the lotus fight", "advice": "Break the wand in the fight",
                        "stage": "laning", "tags": ["lotus", "items", "made up"]})
    lesson = card(reply, chunk, "pro-review")
    assert lesson.source == "pro-review at 12:34" and lesson.tags == ["lotus", "items"]
    assert lesson.said.startswith("Keep those wand")
    assert card(json.dumps({"skip": True}), chunk, "x") is None
    assert card("not json", chunk, "x") is None


def test_learn_saves_cards_and_load_reads_them(tmp_path):
    video = tmp_path / "Pro Lane Review.mp4"
    video.write_bytes(b"")
    replies = iter([
        json.dumps({"skip": True}),
        json.dumps({"skip": False, "situation": "Mid lane, enemy missing", "point": "He backed off",
                    "why": "The enemy support was coming", "advice": "Back off when two heroes go missing",
                    "stage": "laning", "tags": ["map awareness", "positioning"]}),
    ])
    asked = []

    def ask(prompt, frames):
        asked.append((prompt, frames))
        return next(replies)

    segs = [(0, 10, "Hi everyone, welcome back."), (30, 45, "See how he backs off when the support is missing.")]
    said = []
    out = learn(video, tmp_path, ask, segs, grab=lambda v, times: [b"jpg1", b"jpg2"], say=said.append)
    assert len(out) == 1 and len(asked) == 2
    assert asked[1][0].startswith('The coach said: "See how')
    folder = tmp_path / "lessons" / "pro-lane-review"
    assert (folder / "002.json").is_file() and (folder / "002.jpg").read_bytes() == b"jpg2"
    loaded = load(tmp_path)
    assert loaded[0].point == "He backed off" and loaded[0].source == "Pro Lane Review at 0:30"
    (folder / "bad.json").write_text("{")
    assert len(load(tmp_path)) == 1


def test_matching_prefers_the_stage_and_kind_of_moment():
    lane_death = Lesson("s", "Died in lane", "w", "a", "laning", ["death", "positioning"])
    lane_farm = Lesson("s", "Missed last hits", "w", "a", "laning", ["last hits"])
    late_fight = Lesson("s", "Bad fight", "w", "a", "late", ["fight", "death"])
    found = matching([lane_farm, late_fight, lane_death], "died", "laning")
    assert found[0] is lane_death and late_fight not in found
    assert matching([late_fight], "regular", "laning") == []


def test_frames_at_reads_a_real_video(tmp_path):
    av = pytest.importorskip("av")
    pytest.importorskip("PIL")
    import numpy as np

    path = tmp_path / "clip.mp4"
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for i in range(30):
            img = np.full((48, 64, 3), i * 8, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    frames = lessons.frames_at(path, [0.5, 2.0])
    assert len(frames) == 2 and all(f[:2] == b"\xff\xd8" for f in frames)
