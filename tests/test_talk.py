"""The Talk page's rules (U2): what is offered and what the buttons say. No Qt."""

import pytest

from volis import events as ev
from volis.config import Config, ConfigError, PythonConfig
from volis.gui import session as ses
from volis.gui import talk


def listening(mode="shared", paired=False):
    s = ses.Session()
    s.begin("fa", "en", False, True, paired)
    s.apply(ev.Listening())
    s.apply(ev.Mode(mode))
    return s


def test_only_the_ways_in_the_setup_are_offered():
    py = PythonConfig()
    assert [w.name for w in talk.offered_ways(py)] == [talk.TOGETHER, talk.TWO_COMPUTERS, talk.HANDS_FREE]
    py.setup.ways = ["hands-free"]
    assert [w.name for w in talk.offered_ways(py)] == [talk.HANDS_FREE]


def test_a_way_not_known_is_refused_when_the_settings_are_read(tmp_path):
    path = tmp_path / "volis-python.toml"
    path.write_text('[setup]\nways = ["shouting"]\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="shouting"):
        PythonConfig.load(path)


def test_the_last_way_comes_back_and_falls_back_to_what_is_offered():
    config = Config()
    all_ways = list(talk.WAYS.values())
    config.mode.kind = "continuous"
    assert talk.saved_way(config, all_ways).name == talk.HANDS_FREE
    config.mode.kind, config.peer.enabled = "turn", True
    assert talk.saved_way(config, all_ways).name == talk.TWO_COMPUTERS
    assert talk.saved_way(config, [talk.WAYS[talk.HANDS_FREE]]).name == talk.HANDS_FREE


@pytest.mark.parametrize("way, kind, peer", [(talk.TOGETHER, "shared", False), (talk.TWO_COMPUTERS, "turn", True),
                                             (talk.HANDS_FREE, "continuous", False)])
def test_choosing_a_way_sets_what_the_pipeline_reads(way, kind, peer):
    config = Config()
    config.mode.turn_style = "hold"
    talk.choose(config, way, "fa", "en")
    assert (config.mode.kind, config.peer.enabled, config.mode.turn_style) == (kind, peer, "toggle")
    assert (config.languages.source, config.languages.target) == ("fa", "en")


def test_a_new_language_forgets_the_models_chosen_for_the_old_one():
    config = Config()
    config.shared.left_language, config.shared.left_asr, config.shared.right_voice = "es", "old", "old"
    config.shared.right_asr, config.shared.right_language = "keep", "en"
    talk.choose(config, talk.TOGETHER, "fa", "en")
    s = config.shared
    assert (s.left_language, s.left_asr, s.right_voice, s.right_asr) == ("fa", "", "", "keep")


def test_start_says_why_it_can_not_be_pressed():
    assert "No speech" in talk.can_start(talk.TOGETHER, "fa", "en", [])
    assert "different" in talk.can_start(talk.TOGETHER, "fa", "fa", ["fa"])
    assert "English" in talk.can_start(talk.TOGETHER, "fa", "en", ["fa"])
    assert talk.can_start(talk.HANDS_FREE, "fa", "en", ["fa"]) == ""  # it only translates into English
    assert talk.can_start(talk.TOGETHER, "fa", "en", ["fa", "en"]) == ""


def test_the_moments_of_two_people_on_one_computer():
    s = listening()
    ready = talk.side_button(s, "left", "فارسی", "←")
    assert (ready.tone, ready.enabled) == (talk.READY, True) and talk.PRESS in ready.hint and "←" in ready.hint
    s.apply(ev.TurnStarted("left"))
    mine, theirs = talk.side_button(s, "left", "فارسی"), talk.side_button(s, "right", "English")
    assert (mine.tone, mine.hint, mine.enabled) == (talk.LISTENING, talk.FINISH, True)
    assert (theirs.hint, theirs.enabled) == ("Wait", False)
    s.apply(ev.TurnEnded())
    assert talk.side_button(s, "left", "فارسی").hint == talk.PLEASE_WAIT
    s.speaking = True
    for side in ("left", "right"):
        button = talk.side_button(s, side, "x")
        assert (button.hint, button.enabled) == (talk.VOLIS_SPEAKING, False)


def test_talk_needs_a_connection_and_the_floor():
    s = listening("turn", True)
    assert not talk.talk_button(s).enabled
    s.apply(ev.PeerMsg("connected", name="Front desk"))
    assert talk.talk_button(s).enabled
    s.apply(ev.FloorChanged("them", "Front desk"))
    them = talk.talk_button(s)
    assert (them.enabled, them.hint) == (False, "Front desk is talking")
    s.apply(ev.FloorChanged("free"))
    s.apply(ev.TurnStarted())
    assert talk.talk_button(s).hint == talk.FINISH


def test_self_assigned_addresses_only_when_there_is_nothing_else():
    assert talk.addresses_to_show([("Wi-Fi", "192.168.1.5"), ("x", "169.254.1.1")]) == ["192.168.1.5"]
    assert talk.addresses_to_show([("Cable", "169.254.1.1")]) == ["169.254.1.1"]
    assert talk.addresses_to_show([]) == []


def test_a_dropped_connection_says_so():
    s = listening("turn", True)
    assert talk.link(s).words == "Getting ready..."
    s.apply(ev.PeerMsg("waiting", port=47800))
    assert talk.link(s).can_connect
    s.apply(ev.PeerMsg("connected", name="Front desk"))
    assert talk.link(s).connected and talk.link(s).good
    s.apply(ev.PeerMsg("disconnected", reason="The cable came out."))
    dropped = talk.link(s)
    assert dropped.bad and dropped.can_connect and "The cable came out." in dropped.words


@pytest.mark.parametrize("error, title, fix", [
    ("cannot start a turn: device gone", "We can't use your microphone", talk.CHOOSE_MICROPHONE),
    ("No voice is installed for Persian: translations", "One language won't be spoken", ""),
    ("sentence 1.1 was not spoken: boom", "A sentence wasn't spoken", talk.CHOOSE_SPEAKERS),
    ("utterance 3: transcription failed: boom", "Volis couldn't listen", ""),
    ('no translator found in D:\\x', "Volis couldn't translate", ""),
    ("something nobody planned for", "Something went wrong", ""),
])
def test_problems_are_plain_with_the_real_message_behind_details(error, title, fix):
    problem = talk.problem_for(error)
    assert (problem.title, problem.fix, problem.details) == (title, fix, error)


def test_the_microphone_watch_counts_silence_only_while_it_should_hear():
    watch = talk.MicWatch()
    assert not watch.silent(False, 0.0)
    assert not watch.silent(True, 1.0)
    assert watch.silent(True, 1.0 + talk.SILENT_SECONDS)
    watch.heard(-30.0, 6.0)
    assert not watch.silent(True, 6.0)
    watch.heard(None, 7.0)  # digital silence is not hearing something
    watch.heard(-90.0, 8.0)
    assert watch.silent(True, 6.0 + talk.SILENT_SECONDS)
    assert not watch.silent(False, 20.0)  # closed: starts counting afresh
    assert not watch.silent(True, 21.0)


def test_the_microphone_should_hear_in_a_turn_or_hands_free_but_not_while_speaking():
    s = listening()
    assert not talk.microphone_open(s)
    s.apply(ev.TurnStarted("left"))
    assert talk.microphone_open(s)
    hands = listening("continuous")
    assert talk.microphone_open(hands)
    hands.speaking = True
    assert not talk.microphone_open(hands)


def test_loading_words_and_the_level():
    assert talk.loading_words("translator x.gguf") == "Loading the translator..."
    assert talk.loading_words("recognizer whisper") == "Loading speech recognition..."
    assert talk.level_share(None) == 0 and talk.level_share(0.0) == 100 and talk.level_share(-120.0) == 0


def test_a_language_is_offered_in_its_own_script():
    assert talk.language_choice("en") == "English"
    assert "فارسی" in talk.language_choice("fa") and "Persian" in talk.language_choice("fa")
