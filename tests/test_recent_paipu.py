from majsoul_auto_rating.recent_paipu import _signed_int32


def test_signed_int32_keeps_positive_values() -> None:
    assert _signed_int32(28400) == 28400


def test_signed_int32_decodes_wrapped_negative_values() -> None:
    assert _signed_int32(4294962296) == -5000
