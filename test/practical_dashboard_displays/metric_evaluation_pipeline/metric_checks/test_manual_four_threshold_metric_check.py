from itertools import permutations

import pytest
import pandas as pd

from mode_notebook_assets.practical_dashboard_displays.metric_evaluation_pipeline.metric_checks.manual_four_threshold_metric_check import \
    ManualFourThresholdMetricCheck

TEST_CONFIGURATION = ManualFourThresholdMetricCheck(
    threshold_1=10,
    threshold_2=20,
    threshold_3=30,
    threshold_4=40,
)


def test_init_manual_four_threshold_metric_check():
    assert TEST_CONFIGURATION, 'Object should initialize.'


def test_invalid_configuration():
    # Initialization should fail if the thresholds
    # aren't in sorted order.
    with pytest.raises(AssertionError):
        for _theshold_permutations in permutations([10, 20, 30, 40], r=4):
            if _theshold_permutations != sorted(_theshold_permutations):
                assert ManualFourThresholdMetricCheck(
                    threshold_1=_theshold_permutations[0],
                    threshold_2=_theshold_permutations[1],
                    threshold_3=_theshold_permutations[2],
                    threshold_4=_theshold_permutations[3],
                )


def test_run_check():
    assert TEST_CONFIGURATION.run(pd.Series([25, 25, 5, 15, 35, 45])), 'Run method should finish executing.'
