"""Whisper's word timings: a letter split over two tokens must come out whole.

Whisper's tokens are pieces of bytes. A Persian letter or the half-space
(U+200C) can be split over two of them, and each half decoded alone is U+FFFD,
the "unknown character" diamond. File mode builds its sentences from these
words, so the diamonds reached the transcript."""

import numpy as np
import pytest

from volis import paths
from volis.asr.hf import _whisper_words

FFFD = "�"
SENTENCES = [
    "من می‌خواهم کتاب‌ها را بخرم",
    "پژوهش‌گران ژاپنی گفته‌اند",
    "چهارشنبه گچ پژ ژاله",
]


@pytest.fixture(scope="module")
def tokenizer():
    folder = paths.asr_dir(paths.app_root()) / "whisper-large-v3-turbo"
    if not (folder / "tokenizer.json").is_file() and not (folder / "vocab.json").is_file():
        pytest.skip("needs models\\asr\\whisper-large-v3-turbo")
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(str(folder), local_files_only=True)


def test_the_sentences_do_split_letters_over_tokens(tokenizer):
    """Otherwise the next test proves nothing."""
    pieces = [tokenizer.decode([i]) for s in SENTENCES for i in tokenizer.encode(" " + s, add_special_tokens=False)]
    assert any(FFFD in p for p in pieces)


def test_words_are_whole_when_a_letter_is_split_over_two_tokens(tokenizer):
    for sentence in SENTENCES:
        ids = tokenizer.encode(" " + sentence, add_special_tokens=False)
        stamps = np.arange(len(ids), dtype=np.float32) / 10
        words = _whisper_words(tokenizer, np.array(ids), stamps)
        assert " ".join(w.text for w in words) == sentence, "the words are the sentence, letter for letter"
        assert not any(FFFD in w.text for w in words)
        assert all(a.start <= a.end <= b.end for a, b in zip(words, words[1:])), "and their times still run forward"
