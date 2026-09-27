from lindenfret.rng import stage_rng, stage_seed


def test_stage_seed_is_stable_across_processes():
    # A fixed value guards against switching to hash(), which Python salts per process.
    assert stage_seed(1, "form") == 0x376CD74359176253


def test_same_seed_and_stage_give_the_same_stream():
    a = stage_rng(42, "section.0")
    b = stage_rng(42, "section.0")
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]


def test_stages_are_independent():
    assert stage_seed(42, "form") != stage_seed(42, "section.0")
    assert stage_seed(42, "form") != stage_seed(43, "form")
