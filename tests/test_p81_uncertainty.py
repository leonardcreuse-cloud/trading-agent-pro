"""
Stage 3 design power and PT1 noise band (src/uncertainty.py): design quantities only, no result is read.
"""


def test_stage3_design_power_matches_the_preregistered_design():
    from src.uncertainty import stage3_power
    p = stage3_power()
    assert p['tickers'] == 40 and p['records'] == 52 and p['required_p'] == 0.025
    by = {t['hypothesis']: t for t in p['tests']}
    assert by['P1']['n_effective'] == 13.0 and by['P2']['n_effective'] == 52.0
    assert by['P1']['power']['0.03'] == 0.06 and by['P2']['power']['0.03'] == 0.19
    assert by['P1']['mde_80'] == 0.137 and by['P2']['mde_80'] == 0.068


def test_pt1_noise_band_grows_with_the_square_root_of_time():
    from src.uncertainty import pt1_noise_band, pt1_noise_text
    assert pt1_noise_band(52) == 22.7 and pt1_noise_band(13) == 11.3 and pt1_noise_band(0) is None
    assert 'within the noise' in pt1_noise_text(5.0, 260)
    assert 'within the noise' not in pt1_noise_text(30.0, 260)
