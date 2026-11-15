import pytest

from src.services.webui_render.background import choose_mode, parse_crop, saved_crops


@pytest.mark.parametrize(("source", "target", "expected"), [
    (9 / 16, 16 / 9, "soft"), (16 / 9, 9 / 19.5, "soft"),
    (16 / 9, 16 / 9, "cover"), (9 / 16, 9 / 19.5, "cover"),
    (4 / 3, 16 / 9, "cover"), (1, 16 / 9, "soft"), (1, 9 / 19.5, "soft"),
])
def test_adaptive_modes(source, target, expected):
    assert choose_mode(source, target, parse_crop("auto", "", "")) == expected


def test_protected_area_changes_choice():
    assert choose_mode(1, 16 / 9, parse_crop("auto", "50,25", "10,10,90,55")) == "cover"
    assert choose_mode(1, 16 / 9, parse_crop("auto", "50,25", "10,10,90,90")) == "soft"
    assert choose_mode(1, 3, parse_crop("auto", "50,25", "10,10,90,30")) == "soft"


@pytest.mark.parametrize(("focus", "protect"), [("NaN,50", ""), ("10,101", ""), ("", "10,50,90,20")])
def test_invalid_coordinates(focus, protect):
    with pytest.raises(ValueError):
        parse_crop("auto", focus, protect)


def test_legacy_position_and_default():
    def empty(_key, default):
        return default
    assert saved_crops(empty)["desktop"].mode == "auto"
    legacy = {"bg_size": "cover", "bg_position": "top"}
    assert saved_crops(legacy.get)["mobile"] == ("cover", (.5, 0), None)
