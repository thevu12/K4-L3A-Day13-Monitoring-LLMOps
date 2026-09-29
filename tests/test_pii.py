from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd() -> None:
    cccd = "123456789012"

    out = scrub_text(f"CCCD: {cccd}")

    assert cccd not in out
    assert "REDACTED_CCCD" in out


def test_scrub_credit_card_with_spaces_or_dashes() -> None:
    for card_number in ("4111 1111 1111 1111", "4111-1111-1111-1111"):
        out = scrub_text(f"Card: {card_number}")

        assert card_number not in out
        assert "REDACTED_CREDIT_CARD" in out
