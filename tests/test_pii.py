from support_ai.pii import redact


def test_redacts_card_phone_and_email() -> None:
    source = "Карта 4111 1111 1111 1111, +7 (999) 123-45-67, me@example.com"

    result, masks = redact(source)

    assert result.text == "Карта <CARD_1>, <PHONE_1>, <EMAIL_1>"
    assert set(result.found_types) == {"CARD", "PHONE", "EMAIL"}
    assert result.placeholders == 3
    assert set(masks.values()) == {
        "4111 1111 1111 1111",
        "+7 (999) 123-45-67",
        "me@example.com",
    }


def test_redact_is_idempotent() -> None:
    first, _ = redact("Пишите на me@example.com, карта 4111111111111111")
    second, masks = redact(first.text)

    assert second == first
    assert masks == {}


def test_original_values_are_absent() -> None:
    values = ["4111111111111111", "89991234567", "me@example.com"]
    result, _ = redact(" ".join(values))

    assert all(value not in result.text for value in values)


def test_invalid_card_number_is_not_redacted_as_card() -> None:
    result, _ = redact("Номер 4111 1111 1111 1112 не проходит Луна")

    assert result.text == "Номер 4111 1111 1111 1112 не проходит Луна"
    assert "CARD" not in result.found_types
