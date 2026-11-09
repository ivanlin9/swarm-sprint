from concordia_infection.analyse_voting import paired_effect, binary_effect, wilson, nominal_bounds


def test_zero_effect_is_not_certainty():
    result = binary_effect([False] * 12, [False] * 12)
    assert result['mean_difference'] == 0
    assert result['exact_two_sided_discordance_p'] == 1
    assert result['bootstrap_95_percentile_interval'] is None
    assert wilson(0, 12)[1] > .2


def test_discordance_and_variation():
    result = binary_effect([True] * 6, [False] * 6)
    assert result['exact_two_sided_discordance_p'] == .03125
    continuous = paired_effect([0, 1, 0], [0, 0, 0])
    assert continuous['mean_difference'] == 1 / 3
    assert continuous['sd_of_paired_differences'] > 0
    assert continuous['bootstrap_95_percentile_interval'] is not None


def test_cache_write_unknown_lifetime_not_treated_free():
    low, high = nominal_bounds({'input_tokens': 1100, 'output_tokens': 100,
                               'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 1000}})
    assert abs(low - .0037) < 1e-10
    assert abs(high - .0062) < 1e-10
    assert nominal_bounds({'input_tokens': 100, 'output_tokens': 100,
                           'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0}}) == [.0012, .0012]
