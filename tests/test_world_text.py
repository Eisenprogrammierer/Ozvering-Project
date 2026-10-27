from view.support import world_text


def test_forecast_chance_labels_are_qualitative():
    assert world_text.chance_label(1.0) == "почти гарантированно"
    assert world_text.chance_label(0.9) == "весьма вероятно"
    assert world_text.chance_label(0.7) == "вероятно"
    assert world_text.chance_label(0.5) == "возможно"
    assert world_text.chance_label(0.35) == "маловероятно"
    assert world_text.chance_label(0.2) == "почти невероятно"
    assert world_text.chance_label(0.0) == "почти невозможно"
    assert world_text.failure_label(0.8) == "почти невероятно"


def test_effect_maps_do_not_expose_exact_numbers():
    lines = world_text.format_effect_map(
        {"affinity": 0.2, "trust": -0.08}, character_name="Мира"
    )
    assert lines
    assert any("Мира" in line and "расположение" in line for line in lines)
    assert any("доверие" in line for line in lines)
    assert all("%" not in line for line in lines)

    nested = world_text.format_effect_map(
        {
            "player": {"influence": 0.12},
            "target": {"legitimacy": 0.1},
            "relation": -0.07,
        },
        {"influence": "влияние", "legitimacy": "легитимность"},
    )
    assert any("влияние" in line for line in nested)
    assert any("легитимность" in line for line in nested)
    assert any("отношения" in line for line in nested)
    assert all("%" not in line for line in nested)


def test_change_summary_and_reason_text_are_qualitative():
    summary = world_text.summarize_changes(
        [("влияние", 0.1), ("доказательства", 0.01)]
    )
    assert "влияние" in summary
    assert "доказательства" in summary
    assert "%" not in summary
    assert (
        world_text.reason_text("недостаточно полномочий: нужно 30%")
        == "Недостаточно полномочий"
    )
    assert world_text.reason_text("нужен навык «интрига» не ниже 42%") == (
        "Нужен навык «интрига»"
    )


def test_skill_ranks_advance_to_the_next_threshold():
    assert world_text.skill_rank(0.1) == "ученик"
    assert world_text.skill_rank(0.56) == "опытный"
    assert world_text.skill_next_rank(0.1) == "подмастерье"
    assert world_text.skill_next_rank(0.56) == "мастер"
    assert world_text.skill_next_rank(0.95) == ""
