import simulation as S

EXPECTED = {"RL": 1, "UtilityAI": 9, None: 0}


def test_canon_batch_outcome():
    assert S.run_batch(10, quiet=True)[2] == EXPECTED


def test_canon_repeatable_in_process():
    assert S.run_batch(10, quiet=True)[2] == S.run_batch(10, quiet=True)[2]
