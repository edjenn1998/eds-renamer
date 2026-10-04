from renamer.operations import (
    case_op,
    cut_op,
    ext_add_op,
    ext_case_op,
    ext_set_op,
    ext_strip_op,
    numbering_op,
    regex_op,
    replace_op,
    split_name,
    stem_set_op,
)
import pytest


def test_split_simple():
    assert split_name("photo.jpg") == ("photo", ".jpg")


def test_split_multiple_dots_last_wins():
    assert split_name("archive.tar.gz") == ("archive.tar", ".gz")


def test_split_no_extension():
    assert split_name("README") == ("README", "")


def test_split_hidden_file_has_no_ext():
    assert split_name(".gitignore") == (".gitignore", "")


def test_split_hidden_with_ext():
    assert split_name(".config.json") == (".config", ".json")


def test_split_dotfile_single_dot():
    # a name that is only dots
    assert split_name("..") == ("..", "")


def test_split_trailing_dot():
    assert split_name("file.") == ("file", ".")


def test_replace_all():
    op = replace_op("foo", "bar")
    assert op("foo_x_foo", ".txt", 0, 1) == ("bar_x_bar", ".txt")


def test_regex_capture_group():
    op = regex_op(r"(\d+)", r"num\1")
    assert op("pic123", ".png", 0, 1) == ("picnum123", ".png")


def test_regex_ignore_case():
    op = regex_op("abc", "x", ignore_case=True)
    assert op("ABC", ".t", 0, 1) == ("x", ".t")


def test_cut_front():
    op = cut_op("front", 4)
    # IMG_ is 4 chars; suffix untouched
    assert op("IMG_001", ".jpg", 0, 1) == ("001", ".jpg")


def test_cut_end_keeps_first_n():
    op = cut_op("end", 3)
    assert op("abcdef", ".txt", 0, 1) == ("abc", ".txt")


def test_cut_zero_noop():
    op = cut_op("front", 0)
    assert op("abc", ".txt", 0, 1) == ("abc", ".txt")


def test_cut_unknown_mode():
    with pytest.raises(ValueError):
        cut_op("side", 2)


def test_case_modes():
    assert case_op("lower")("AbC", ".x", 0, 1) == ("abc", ".x")
    assert case_op("upper")("AbC", ".x", 0, 1) == ("ABC", ".x")
    assert case_op("title")("a_b", ".x", 0, 1) == ("A_B", ".x")
    assert case_op("sentence")("hello world", ".x", 0, 1) == ("Hello world", ".x")


def test_numbering_token_padding():
    op = numbering_op()
    assert op("clip_#", ".jpg", 0, 5) == ("clip_1", ".jpg")
    assert op("clip_##", ".jpg", 9, 12) == ("clip_10", ".jpg")
    assert op("clip_###", ".jpg", 2, 3) == ("clip_003", ".jpg")


def test_numbering_token_first_run_only():
    op = numbering_op()
    assert op("a##b##", ".x", 4, 10) == ("a05b##", ".x")


def test_numbering_prefix_mode():
    op = numbering_op(mode="prefix", pad=2)
    assert op("file", ".txt", 0, 3) == ("01file", ".txt")


def test_numbering_suffix_mode():
    op = numbering_op(mode="suffix", pad=3)
    assert op("file", ".txt", 2, 3) == ("file003", ".txt")


def test_numbering_start_and_step():
    op = numbering_op(mode="prefix", pad=1, start=5, step=2)
    assert op("f", "", 0, 3)[0] == "5f"
    assert op("f", "", 1, 3)[0] == "7f"
    assert op("f", "", 2, 3)[0] == "9f"


def test_numbering_negative_not_padded():
    op = numbering_op(mode="suffix", pad=3, start=-5)
    assert op("f", "", 0, 1)[0] == "f-5"


def test_stem_set_keeps_suffix():
    op = stem_set_op("fixed")
    assert op("whatever", ".mp4", 0, 1) == ("fixed", ".mp4")


def test_ext_set_replaces():
    assert ext_set_op("txt")("name", ".md", 0, 1) == ("name", ".txt")
    assert ext_set_op(".txt")("name", "", 0, 1) == ("name", ".txt")


def test_ext_add_only_when_missing():
    assert ext_add_op("txt")("name", "", 0, 1) == ("name", ".txt")
    assert ext_add_op("txt")("name", ".md", 0, 1) == ("name", ".md")


def test_ext_strip_removes_suffix():
    assert ext_strip_op()("file", ".bak", 0, 1) == ("file", "")


def test_ext_case():
    assert ext_case_op("lower")("f", ".JPG", 0, 1) == ("f", ".jpg")
    assert ext_case_op("upper")("f", ".jpg", 0, 1) == ("f", ".JPG")
