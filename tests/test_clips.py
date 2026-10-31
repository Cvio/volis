"""A conversation's audio, and playing one clip (U3). No sound device."""

import queue
from types import SimpleNamespace

import numpy as np

from volis import clips
from volis import events as ev
from volis.pipeline import SpeakThread


class FakePlayer:
    device_rate = 1000

    def __init__(self):
        self.played, self.left = [], 0

    def clear(self):
        self.left = 0

    def play(self, samples, rate):
        self.played.append((len(samples), rate))
        self.left += len(samples)

    def queued(self):
        return self.left


def one_second():
    return clips.Clip(np.ones(1000, np.int16), 1000)


def test_audio_is_kept_compact_and_comes_back_at_the_same_level():
    store = clips.Clips()
    store.put_spoken("1.1", np.array([0.5, -1.0, 2.0], np.float32), 22050)
    clip = store.spoken("1.1")
    assert clip.samples.dtype == np.int16 and clip.rate == 22050
    assert np.allclose(clip.floats(), [0.5, -1.0, 1.0], atol=1e-3)
    assert store.spoken("nope") is None


def test_a_sentences_original_is_its_part_of_the_utterance():
    store = clips.Clips()
    store.put_heard(3, 10.0, np.ones(16000 * 4, np.float32))
    assert store.original(3, 11.0, 12.0).seconds == 1.0
    assert store.original(3, 10.0, 14.0).seconds == 4.0
    assert store.original(9, 0.0, 1.0) is None


def test_bad_times_give_the_whole_utterance_rather_than_nothing():
    store = clips.Clips()
    store.put_heard(1, 10.0, np.ones(16000, np.float32))
    assert store.original(1, 50.0, 51.0).seconds == 1.0


def test_the_same_words_from_the_other_computer_are_the_same_speech():
    assert clips.remote_key("fa", "سلام") == clips.remote_key("fa", "سلام") != clips.remote_key("en", "سلام")


def test_replay_position_comes_from_what_the_player_has_left():
    player, r = FakePlayer(), clips.Replay()
    r.play("1.1", one_second(), player)
    assert r.playing() and r.position() == 0.0
    player.left = 250
    assert r.position() == 0.75
    player.left = 0
    r.update()
    assert r.finished and not r.playing() and r.position() == 1.0


def test_pause_takes_it_out_of_the_player_and_play_carries_on_from_there():
    player, r = FakePlayer(), clips.Replay()
    r.play("1.1", one_second(), player)
    player.left = 500
    r.toggle()
    assert r.paused and not r.playing() and player.left == 0 and r.position() == 0.5
    r.update()
    assert not r.finished, "paused is not finished"
    r.toggle()
    assert r.playing() and player.left == 500 and r.position() == 0.5


def test_play_after_the_end_starts_again():
    player, r = FakePlayer(), clips.Replay()
    r.play("1.1", one_second(), player)
    player.left = 0
    r.update()
    r.toggle()
    assert r.playing() and player.left == 1000


def test_seek_goes_there_and_stays_paused_if_paused():
    player, r = FakePlayer(), clips.Replay()
    r.play("1.1", one_second(), player)
    r.seek(0.4)
    assert player.left == 600 and r.position() == 0.4
    r.toggle()
    r.seek(0.9)
    assert r.paused and player.left == 0 and r.position() == 0.9
    r.toggle()
    assert player.left == 100


def test_stop_clears_only_when_it_was_playing():
    player, r = FakePlayer(), clips.Replay()
    r.stop()
    r.play("1.1", one_second(), player)
    r.stop()
    assert not r.active() and player.left == 0 and r.key == "" and r.position() == 0.0


def test_forgetting_leaves_a_new_sentence_in_the_player():
    player, r = FakePlayer(), clips.Replay()
    r.play("1.1", one_second(), player)
    player.play(np.ones(300), 1000)
    r.forget()
    assert not r.active() and player.left == 1300


class Voice:
    name = "fake"

    def speak(self, text):
        return SimpleNamespace(samples=np.ones(160, np.float32) / 2, sample_rate=16_000, duration_ms=lambda: 10)


def speaker(monkeypatch, tmp_path, muted=False):
    from volis.config import PythonConfig

    seen, played = queue.Queue(), []
    store = clips.Clips()
    pipeline = SimpleNamespace(root=tmp_path, pyconfig=PythonConfig(), emit=seen.put, generation=0, muted=muted, clips=store)
    player = SimpleNamespace(play=lambda samples, rate: played.append(rate), queued=lambda: 0, close=lambda: None)
    thread = SpeakThread(pipeline, player)
    monkeypatch.setattr(thread, "_voice", lambda language, folder="": Voice())
    return thread, store, seen, played


def test_what_is_spoken_is_kept(monkeypatch, tmp_path):
    thread, store, _, played = speaker(monkeypatch, tmp_path)
    thread.submit("1.1", "Hello", "en", 0.0)
    thread.submit_remote("سلام", "fa")
    thread.finish(wait=True)
    assert played == [16_000, 16_000]
    assert store.spoken("1.1").seconds == 0.01
    assert store.spoken(clips.remote_key("fa", "سلام")) is not None


def test_with_the_sound_off_it_is_kept_but_not_played(monkeypatch, tmp_path):
    thread, store, seen, played = speaker(monkeypatch, tmp_path, muted=True)
    thread.submit("1.1", "Hello", "en", 0.0)
    thread.finish(wait=True)
    assert played == [] and store.spoken("1.1") is not None
    events = []
    while not seen.empty():
        events.append(seen.get())
    assert any(isinstance(e, ev.NotSpoken) for e in events), "the turn must not wait for speech that won't come"
