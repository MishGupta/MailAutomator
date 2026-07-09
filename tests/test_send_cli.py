import pytest
from send_emails import validate_limit


def test_validate_limit_none_ok():
    assert validate_limit(None) is None


def test_validate_limit_positive_ok():
    assert validate_limit(400) == 400


def test_validate_limit_zero_rejected():
    with pytest.raises(ValueError):
        validate_limit(0)


def test_validate_limit_negative_rejected():
    with pytest.raises(ValueError):
        validate_limit(-5)
