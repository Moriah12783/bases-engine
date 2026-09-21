from bases_engine.util import parse_race_id, race_label, race_seed, race_slug


def test_race_slug_no_spaces():
    assert race_slug("R1C1_21092026_LA CAPELLE") == "2026-09-21_r1c1_la-capelle"
    assert race_slug("R8C8_21092026_LE MONT SAINT MICHEL") == "2026-09-21_r8c8_le-mont-saint-michel"
    assert race_label("R1C1_21092026_LA CAPELLE") == "LA CAPELLE - R1C1"
    assert parse_race_id("R12C3_05012026_SAINT-CLOUD")["hippodrome"] == "SAINT-CLOUD"


def test_seed_is_stable():
    assert race_seed("2026-09-21", "R1C1_21092026_LA CAPELLE") == race_seed("2026-09-21", "R1C1_21092026_LA CAPELLE")
    assert race_seed("2026-09-21", "R1C1_21092026_LA CAPELLE") != race_seed("2026-09-22", "R1C1_21092026_LA CAPELLE")
