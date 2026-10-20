from app.rag.chunking import chunk_text


def test_empty_and_blank_notes_make_no_chunks():
    assert chunk_text(None) == []
    assert chunk_text("   ") == []


def test_short_note_stays_whole():
    assert chunk_text("Back injury with physical therapy.") == ["Back injury with physical therapy."]


def test_long_note_splits_on_sentences_within_the_limit():
    text = " ".join(f"Sentence number {i} describes one more fact about the claim." for i in range(12))
    chunks = chunk_text(text, max_chars=200)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert all(c.endswith(".") for c in chunks)  # never cut mid sentence


def test_neighbouring_chunks_share_one_sentence():
    text = "Alpha one. Bravo two. Charlie three. Delta four. Echo five. Foxtrot six."
    chunks = chunk_text(text, max_chars=30, overlap_sentences=1)
    for left, right in zip(chunks, chunks[1:]):
        last_sentence = left.split(". ")[-1]
        assert last_sentence.rstrip(".") in right


def test_no_overlap_when_disabled():
    chunks = chunk_text("Alpha one. Bravo two. Charlie three. Delta four.", max_chars=22, overlap_sentences=0)
    assert " ".join(chunks) == "Alpha one. Bravo two. Charlie three. Delta four."


def test_a_single_huge_sentence_is_cut_on_word_boundaries():
    chunks = chunk_text("word " * 200, max_chars=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(c.replace(" ", "") for c in chunks).startswith("wordword")
