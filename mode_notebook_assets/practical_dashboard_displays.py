from typing import Any, Callable

from dataclasses import dataclass

import pandas as pd
import numpy as np

import plotly.graph_objects as go
import plotly.express as px
from IPython.core.display import HTML

import base64
import matplotlib.pyplot as plt
from io import BytesIO

@dataclass
class MetricEvaluationPipeline:
    s: pd.Series

    metric_name: str = None
    measure_name: str = None

    check_outside_of_normal_range: bool = True
    outside_of_normal_range_minimum_periods: int = 8
    outside_of_normal_range_rolling_calculation_periods: int = None

    check_sudden_change: bool = True
    sudden_change_minimum_periods: int = 7
    sudden_change_rolling_calculation_periods: int = None

    check_change_in_steady_state_long: bool = False
    change_in_steady_state_long_minimum_periods: int = 14

    disable_warnings: bool = False

    is_higher_good: bool = True
    is_lower_good: bool = False
    good_palette: list = None
    bad_palette: list = None
    ambiguous_palette: list = None

    def __post_init__(self):

        if self.check_change_in_steady_state_long and not self.disable_warnings:
            raise Warning(
                'The steady_state_long actionability check is an alpha feature and not recommended'
                'for actual use. The current method of a rolling train/test window causes unexpected'
                'results, such as the long run index changing unexpectedly due to the changing historical'
                'average. If you wish to proceed, set the disable_warnings argument to True'
            )

        _outside_of_normal_range_results = outside_of_normal_range(
            self.s,
            minimum_periods=self.outside_of_normal_range_minimum_periods,
            rolling_calculation_periods=self.outside_of_normal_range_rolling_calculation_periods
        ) if self.check_outside_of_normal_range else None

        _sudden_change_results = sudden_change(
            self.s,
            minimum_periods=self.sudden_change_minimum_periods,
            rolling_calculation_periods=self.sudden_change_rolling_calculation_periods
        ) if self.check_sudden_change else None

        _change_in_steady_state_long_results = change_in_steady_state_long(
            self.s,
            minimum_periods=self.change_in_steady_state_long_minimum_periods
        ) if self.check_change_in_steady_state_long else None

        self._actionability_score_columns = [
            s for s in [
                'normal_range_actionability_score' if self.check_outside_of_normal_range else None,
                'sudden_change_actionability_score' if self.check_sudden_change else None,
                'change_in_steady_state_long_actionability_score' if self.check_change_in_steady_state_long else None,
            ] if s is not None
        ]

        if len(self._actionability_score_columns) > 0:
            _results = pd.concat(
                [df for df in
                 [_outside_of_normal_range_results, _sudden_change_results, _change_in_steady_state_long_results] if
                 df is not None],
                axis=1
            )

            _results = _results.loc[:, ~_results.columns.duplicated()]

            self.results = pd.concat([
                    _results,
                    pd.DataFrame.from_records(
                        [self.combine_actionability_scores(r) for r in
                         _results[self._actionability_score_columns].to_dict(orient='records')],
                        index=_results.index,
                    )
                ], axis=1,)
        else:
            _results = pd.DataFrame(self.s)
            _results['period_value'] = self.s
            self.results = _results.assign(general_actionability_score=0, is_valence_ambiguous=False)

    @staticmethod
    def combine_actionability_scores(record: dict):
        return {
            # Take the actionability score farthest from zero
            'general_actionability_score': max(record.values(), key=np.abs),

            # Valence is considered ambiguous if at least two actionability scores have different signs
            'is_valence_ambiguous':        len(set(np.sign(x) for x in record.values() if pd.notna(x) and x != 0)) > 1,
        }

    def get_current_record(self):
        return self.results.to_dict(orient='records')[-1]

    def get_current_actionability_status(self):
        return self.get_current_record()['general_actionability_score']

    def is_current_actionability_ambiguous(self):
        return self.get_current_record()['is_valence_ambiguous']

    def get_current_actionability_status_dot(self):
        _color = map_actionability_score_to_color(
            x=self.get_current_actionability_status(),
            is_valence_ambiguous=self.is_current_actionability_ambiguous(),
            is_higher_good=self.is_higher_good,
            is_lower_good=self.is_lower_good,
            good_palette=self.good_palette,
            bad_palette=self.bad_palette,
            ambiguous_palette=self.ambiguous_palette
        )

        _hex_color = '#%02x%02x%02x' % tuple(
            int(s) for s in _color.replace('rgb(', '').replace(')', '').split(',')
        )

        return dot(_hex_color)

    def get_current_sparkline(self, periods=20):
        return sparkline(self.results.tail(periods)['period_value'])

    def get_current_display_record(self, sparkline=True, sparkline_periods=20):

        _output = {'Metric': self.metric_name} if self.metric_name else {}

        _output['Current Value'] = self.get_current_record()['period_value']
        _output['Actionability Score'] = self.get_current_actionability_status()
        _output['Status Dot'] = self.get_current_actionability_status_dot()
        
        if sparkline:
            _output['Sparkline'] = self.get_current_sparkline(periods=sparkline_periods)

        return _output

    def write_actionability_summary(self, record: dict, is_higher_good=True, is_lower_good=False):

        _description = '<b>' + map_actionability_score_to_description(
            record['general_actionability_score'],
            is_valence_ambiguous=record['is_valence_ambiguous'],
            is_higher_good=is_higher_good,
            is_lower_good=is_lower_good
        ) + '</b>'

        if self.check_outside_of_normal_range:
            _normal_range_sign = np.sign(record["normal_range_actionability_score"])
            _high_or_low = (
                    ("<b>high</b>" if record["normal_range_actionability_score"] > 0 else "<b>low</b>") + \
                    " compared with historical ranges"
            )
            _within_normal_str = "within a <b>normal</b> range based on historical values"
            _is_in_normal_range = record["normal_range_actionability_score"] == 0
            _normal_range_summary = (
                f'Metric is {_within_normal_str if _is_in_normal_range else (_high_or_low)}.')
        else:
            _normal_range_summary = None

        if self.check_sudden_change:
            _sudden_change_sign = np.sign(record["sudden_change_actionability_score"])
            _sudden_dip_or_spike_summary = (
                None if _sudden_change_sign == 0
                else f'Metric <b>{"increased" if _sudden_change_sign == 1 else "decreased"} '
                     f'suddenly</b> compared to historical values.'
            )
        else:
            _sudden_dip_or_spike_summary = None

        if self.check_change_in_steady_state_long:
            _change_in_steady_state_long_sign = np.sign(record["change_in_steady_state_long_actionability_score"])
            _change_in_steady_state_long_summary = (
                None if _change_in_steady_state_long_sign == 0
                else f'Metric has been <b>{"above" if _change_in_steady_state_long_sign == 1 else "below"}</b> the '
                     f'historical average for {int(record["current_long_run"])} consecutive periods.'
            )
        else:
            _change_in_steady_state_long_summary = None

        _text = "<br>".join([s for s in [_description, _normal_range_summary, _sudden_dip_or_spike_summary,
                                         _change_in_steady_state_long_summary] if s])

        return _text

    def display_sparkline_time_series(self, metric_name=None):

        df = self.results.dropna()

        fig = go.Figure(
            layout=go.Layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                hovermode='x',
            )
        )

        # plot period values for display
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df.period_value,
                name=metric_name or 'Period Value',
                mode='lines',
                line=dict(color='gray', width=4),
            )
        )

        # hide and lock down axes
        fig.update_xaxes(visible=False, fixedrange=True)
        fig.update_yaxes(visible=False, fixedrange=True)

        # remove facet/subplot labels
        fig.update_layout(annotations=[])

        # strip down the rest of the plot
        fig.update_layout(
            showlegend=False,
            plot_bgcolor="white",
            margin=dict(t=1,l=1,b=1,r=1)
        )

        return fig

    def display_actionability_time_series(self, title=None, metric_name=None, display_last_n_valence_periods=4,
                                          show_legend=False):
        df = self.results.dropna()

        fig = go.Figure(
            layout=go.Layout(
                title=title,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                hovermode='x',
            )
        )
        if self.check_outside_of_normal_range:
            # plot thresholds
            threshold_value_list = [
                'high_l2_threshold_value',
                'high_l1_threshold_value',
                'normal_range_rolling_baseline',
                'low_l1_threshold_value',
                'low_l2_threshold_value',
            ]

            for colname in threshold_value_list:
                fig.add_trace(
                    go.Scatter(
                        x=df.index,
                        y=df[colname],
                        mode='lines',
                        name=map_threshold_labels_to_name_by_configuration(
                            colname,
                            is_higher_good=self.is_higher_good,
                            is_lower_good=self.is_lower_good,
                        ),
                        line=dict(color='lightgray', dash='dash'),
                        hoverinfo='skip',
                        showlegend=show_legend,
                    )
                )

        # plot actionable periods
        actionable_periods_df = df.query('general_actionability_score != 0')
        fig.add_trace(
            go.Scatter(
                x=actionable_periods_df.index,
                y=actionable_periods_df.period_value,
                mode='markers',
                name='Actionability',
                hovertext=[
                    self.write_actionability_summary(
                        record,
                        is_higher_good=self.is_higher_good,
                        is_lower_good=self.is_lower_good,
                    ) for record in actionable_periods_df.to_records()],
                hoverinfo="text",
                marker=dict(
                    size=10,
                    color=[
                        map_actionability_score_to_color(
                            score,
                            is_valence_ambiguous=is_valence_ambiguous,
                            is_higher_good=self.is_higher_good,
                            is_lower_good=self.is_lower_good,
                            good_palette=self.good_palette,
                            bad_palette=self.bad_palette,
                            ambiguous_palette=self.ambiguous_palette,
                        ) for period, score, is_valence_ambiguous in
                        actionable_periods_df[['general_actionability_score', 'is_valence_ambiguous']].to_records()
                    ]
                ),
                showlegend=show_legend,
            )
        )

        # Cover up past actionable periods with neutral color
        if display_last_n_valence_periods is not None:
            historical_actionable_periods_df = df.head(len(df.index) - display_last_n_valence_periods).query(
                'general_actionability_score != 0')
            fig.add_trace(
                go.Scatter(
                    x=historical_actionable_periods_df.index,
                    y=historical_actionable_periods_df.period_value,
                    mode='markers',
                    name='Historical Alerts',
                    hoverinfo="skip",
                    marker=dict(
                        size=10,
                        color=['lightgray'] * len(historical_actionable_periods_df.period_value),
                    ),
                    showlegend=show_legend,
                )
            )

        # plot period values
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df.period_value,
                mode='lines',
                name=metric_name or 'Period Value',
                line=dict(color='gray', width=4),
                showlegend=show_legend,
            )
        )

        return fig


def create_output_column_for_rolling_period(func: Callable[[pd.Series, int], dict],
                                            df: pd.DataFrame,
                                            derived_colname: str,
                                            minimum_periods: int,
                                            rolling_calculation_periods: Any,
                                            apply_to_colname='period_value'):
    '''
    Performs a rolling or expanding calculation window calculation (func) based on
    minimum_periods and rolling_calculation_periods.

    Creates column "derived_colname" which must be a key to a dictionary output by func.

    Side effects: Mutates df.
    '''
    _apply_function = lambda x: func(x, minimum_periods)[derived_colname]
    _apply_to_series = df[apply_to_colname]

    if rolling_calculation_periods is not None:
        _runtime_rolling_calculation_periods = min(len(_apply_to_series), rolling_calculation_periods)

        df[derived_colname] = _apply_to_series.rolling(_runtime_rolling_calculation_periods).apply(
            _apply_function,
            raw=False,
        )

    else:
        df[derived_colname] = _apply_to_series.expanding(minimum_periods).apply(
            _apply_function,
            raw=False,
        )


def change_in_steady_state_long(s: pd.Series, minimum_periods=14) -> pd.DataFrame:
    '''
    Assumptions: 14 periods or more, 50/50 split between historical series (baseline) and
                 evaluation series (testing)
    '''

    def _change_in_steady_state_long_point_in_time(values: pd.Series, local_minimum_n_periods: int):
        values_series = values
        L1_LONG_RUN_ACTIONABILITY_THRESHOLD = 7
        L2_LONG_RUN_ACTIONABILITY_THRESHOLD = 9

        if len(values) >= local_minimum_n_periods:
            train_test_breakpoint_index = max(int(len(values) / 2), local_minimum_n_periods)
            training_series = values_series[:train_test_breakpoint_index]
            testing_series = values_series[train_test_breakpoint_index:]

            mean_of_historical_training_values = training_series.mean()

            current_long_run = 0
            last_value_greater_than_historical_mean = False
            last_value_less_than_historical_mean = False
            for x in testing_series:
                current_value_greater_than_historical_mean = x > mean_of_historical_training_values
                current_value_less_than_historical_mean = x < mean_of_historical_training_values

                increment_long_run_check = (
                        current_value_greater_than_historical_mean == last_value_greater_than_historical_mean
                        and current_value_less_than_historical_mean == last_value_less_than_historical_mean
                        and x != mean_of_historical_training_values
                )

                if increment_long_run_check:
                    current_long_run = current_long_run + 1
                else:
                    current_long_run = 0

                last_value_greater_than_historical_mean = current_value_greater_than_historical_mean
                last_value_less_than_historical_mean = current_value_less_than_historical_mean

            change_in_steady_state_long_actionability_score = 0 if current_long_run < L1_LONG_RUN_ACTIONABILITY_THRESHOLD else (
                    (-1 if last_value_less_than_historical_mean else 1) * (
                    .01 + (current_long_run - L1_LONG_RUN_ACTIONABILITY_THRESHOLD) /
                    (L2_LONG_RUN_ACTIONABILITY_THRESHOLD - L1_LONG_RUN_ACTIONABILITY_THRESHOLD))
            )

            return {
                # Actionability
                'change_in_steady_state_long_actionability_score': change_in_steady_state_long_actionability_score,

                # Threshold
                'mean_of_historical_training_values':              mean_of_historical_training_values,

                # Intermediate Values
                'current_long_run':                                current_long_run,
            }

        else:
            return {
                'change_in_steady_state_long_actionability_score': None,
                'mean_of_historical_training_values':              None,
                'current_long_run':                                None,
            }

    _t = pd.DataFrame(s)

    output_columns = [
        'change_in_steady_state_long_actionability_score',
        'mean_of_historical_training_values',
        'current_long_run',
    ]

    _t['period_value'] = s

    for colname in output_columns:
        create_output_column_for_rolling_period(
            _change_in_steady_state_long_point_in_time,
            _t,
            colname,
            minimum_periods=minimum_periods,
            rolling_calculation_periods=None
        )

    return _t


def sudden_change(s: pd.Series, minimum_periods=7, rolling_calculation_periods=None) -> pd.DataFrame:
    def _sudden_change_point_in_time(values: pd.Series, local_minimum_n_periods: int):
        L1_SUDDEN_CHANGE_CONSTANT = 3.27
        L2_SUDDEN_CHANGE_CONSTANT = 4.905

        values_series = values

        if len(values) >= local_minimum_n_periods:
            mean_of_historical_values = values_series.mean()
            mean_of_pop_differences = abs(values_series - values_series.shift(1)).mean()
            most_recent_period_change = values_series[-1] - values_series[-2]

            is_actionable = np.abs(most_recent_period_change) >= L1_SUDDEN_CHANGE_CONSTANT * mean_of_pop_differences

            sudden_change_l1_threshold_value = L1_SUDDEN_CHANGE_CONSTANT * mean_of_pop_differences
            sudden_change_l2_threshold_value = L2_SUDDEN_CHANGE_CONSTANT * mean_of_pop_differences

            sudden_change_actionability_score = 0 if not is_actionable else (
                    (abs(most_recent_period_change) - sudden_change_l1_threshold_value)
                    / (sudden_change_l2_threshold_value - sudden_change_l1_threshold_value)
                    * np.sign(most_recent_period_change)
            )

            return {
                # Actionability
                'sudden_change_actionability_score': sudden_change_actionability_score,

                # Thresholds
                'sudden_change_l1_threshold_value':  sudden_change_l1_threshold_value,
                'sudden_change_l2_threshold_value':  sudden_change_l2_threshold_value,

                # Intermediate Values
                'most_recent_period_change':         most_recent_period_change,
            }

        else:
            return {
                'sudden_change_actionability_score': None,
                'sudden_change_l1_threshold_value':  None,
                'sudden_change_l2_threshold_value':  None,
                'most_recent_period_change':         None,
            }

    _t = pd.DataFrame(s)

    output_columns = [
        'sudden_change_actionability_score',
        'sudden_change_l1_threshold_value',
        'sudden_change_l2_threshold_value',
        'most_recent_period_change',
    ]

    _t['period_value'] = s

    for colname in output_columns:
        create_output_column_for_rolling_period(
            _sudden_change_point_in_time,
            _t,
            colname,
            minimum_periods=minimum_periods,
            rolling_calculation_periods=rolling_calculation_periods
        )

    return _t


def outside_of_normal_range(s: pd.Series, minimum_periods=8, rolling_calculation_periods=None) -> pd.DataFrame:
    def _outside_of_normal_range_point_in_time(values: pd.Series, local_minimum_n_periods: int):
        '''
        Calculates Outside of Normal Range check, including thresholds, for a point in time.
        This function is applied to a rolling time series
        '''
        # Statistical process control constants
        L1_NORMAL_RANGE_CONSTANT = 2.66
        L2_NORMAL_RANGE_CONSTANT = 3.99

        values_series = values

        if len(values) >= local_minimum_n_periods:
            mean_of_historical_values = values_series.mean()
            mean_of_pop_differences = abs(values_series - values_series.shift(1)).mean()
            most_recent_value = values_series[-1]
            most_recent_value_deviation = most_recent_value - mean_of_historical_values
            is_actionable = np.abs(most_recent_value_deviation) >= L1_NORMAL_RANGE_CONSTANT * mean_of_pop_differences

            low_l2_threshold_value = mean_of_historical_values - L2_NORMAL_RANGE_CONSTANT * mean_of_pop_differences
            low_l1_threshold_value = mean_of_historical_values - L1_NORMAL_RANGE_CONSTANT * mean_of_pop_differences
            high_l1_threshold_value = mean_of_historical_values + L1_NORMAL_RANGE_CONSTANT * mean_of_pop_differences
            high_l2_threshold_value = mean_of_historical_values + L2_NORMAL_RANGE_CONSTANT * mean_of_pop_differences

            normal_range_actionability_score = 0 if not is_actionable else (
                    (abs(most_recent_value_deviation) - mean_of_pop_differences * L1_NORMAL_RANGE_CONSTANT)
                    / (
                            mean_of_pop_differences * L2_NORMAL_RANGE_CONSTANT - mean_of_pop_differences * L1_NORMAL_RANGE_CONSTANT)
                    * np.sign(most_recent_value_deviation)
            )

            return {
                # Actionability
                'normal_range_actionability_score': normal_range_actionability_score,

                # Thresholds
                'low_l2_threshold_value':           low_l2_threshold_value,
                'low_l1_threshold_value':           low_l1_threshold_value,
                'high_l1_threshold_value':          high_l1_threshold_value,
                'high_l2_threshold_value':          high_l2_threshold_value,

                # Intermediate Calculations
                'normal_range_rolling_baseline':    mean_of_historical_values,
                'normal_range_rolling_deviation':   mean_of_pop_differences,
            }

        else:
            return {
                'normal_range_actionability_score': None,
                'low_l2_threshold_value':           None,
                'low_l1_threshold_value':           None,
                'high_l1_threshold_value':          None,
                'high_l2_threshold_value':          None,
                'mean_of_historical_values':        None,
                'mean_of_pop_differences':          None,
            }

    _t = pd.DataFrame(s)

    output_columns = [
        'normal_range_actionability_score',
        'low_l2_threshold_value',
        'low_l1_threshold_value',
        'normal_range_rolling_baseline',
        'high_l1_threshold_value',
        'high_l2_threshold_value',
    ]

    _t['period_value'] = s

    for colname in output_columns:
        # TODO: This is very inefficient. For this to scale, especially scanning
        #       many time series, shouldn't re-do each ts calculation five times
        #       unnecessarily!
        create_output_column_for_rolling_period(
            _outside_of_normal_range_point_in_time,
            _t,
            colname,
            minimum_periods=minimum_periods,
            rolling_calculation_periods=rolling_calculation_periods
        )

    return _t


def map_actionability_score_to_color(x: float, is_valence_ambiguous=False, is_higher_good=True, is_lower_good=False,
                                     good_palette=None, bad_palette=None, ambiguous_palette=None):
    _good_palette = list(good_palette or px.colors.sequential.Greens[3:-2])
    _bad_palette = list(bad_palette or px.colors.sequential.Reds[3:-2])
    _ambiguous_palette = list(ambiguous_palette or ['rgb(255,174,66)'])

    if x == 0:
        return 'rgb(211,211,211)'
    elif is_valence_ambiguous:
        return _ambiguous_palette[
            int(min(np.floor(np.abs(x) * (len(_ambiguous_palette) - 1)), len(_ambiguous_palette) - 1))]
    else:
        _is_good = (is_higher_good and x > 0) or (is_lower_good and x < 0)
        if _is_good:
            return _good_palette[int(min(np.floor(np.abs(x) * (len(_good_palette) - 1)), len(_good_palette) - 1))]
        else:
            return _bad_palette[int(min(np.floor(np.abs(x) * (len(_bad_palette) - 1)), len(_bad_palette) - 1))]


def map_actionability_score_to_description(x: float, is_valence_ambiguous=False, is_higher_good=True,
                                           is_lower_good=False):
    if x == 0:
        return 'Within a Normal Range'
    elif is_valence_ambiguous:
        return 'Ambiguous'
    else:
        _is_good = (is_higher_good and x > 0) or (is_lower_good and x < 0)
        if _is_good:
            if np.abs(x) > 1:
                return 'Extraordinary'
            else:
                return 'Actionably Good'
        else:
            if np.abs(x) > 1:
                return 'Crisis'
            else:
                return 'Actionably Bad'


def map_threshold_labels_to_name_by_configuration(label: str, is_higher_good=True, is_lower_good=False):
    is_high = 'high' in label
    is_low = 'low' in label
    is_l1 = 'l1' in label
    is_l2 = 'l2' in label

    if is_high and is_l2:
        return 'Extraordinary' if is_higher_good else 'Crisis'
    elif is_high and is_l1:
        return 'Actionably Good' if is_higher_good else 'Actionably Bad'
    elif is_low and is_l1:
        return 'Actionably Good' if is_lower_good else 'Actionably Bad'
    elif is_low and is_l2:
        return 'Extraordinary' if is_lower_good else 'Crisis'
    else:
        return label


def html_div_grid(html_elements:list, columns=3):

    def table_div(s):
        return f'<div style="width:100%; display: table;">{s}</div>'

    def row_div(s):
        return f'<div style="display: table-row;">{s}</div>'

    def cell_div(s):
        return f'<div style="display: table-cell;">{s}</div>'

    html_element_rows = [html_elements[i*columns:min(i*columns+columns, len(html_elements))] for i in range(0, len(html_elements)//columns+1)]
    html_format = table_div(''.join(row_div(''.join(cell_div(e) for e in l)) for l in html_element_rows))
    return html_format


def plotly_div_grid(fig_list: list, columns=3):
    def handle_element(e):
        if isinstance(e, str):
            return e
        else:
            return e.to_html()

    return HTML(html_div_grid([handle_element(fig) for fig in fig_list], columns=columns))


def sparkline(data, point_marker='.', point_size=6, point_alpha=1.0, figsize=(4, 0.25), **kwargs):
    """
    Create a single HTML image tag containing a base64 encoded
    sparkline style plot.

    Forked from https://github.com/crdietrich/sparklines on 2020-12-22.
    """

    data = list(data)

    fig = plt.figure(figsize=figsize)  # set figure size to be small
    ax = fig.add_subplot(111)
    plot_len = len(data)
    point_x = plot_len - 1

    plt.plot(data, linewidth=2, color='gray', **kwargs)

    # turn off all axis annotations
    ax.axis('off')

    # plot the right-most point larger
    plt.plot(point_x, data[point_x], color='gray',
             marker=point_marker, markeredgecolor='gray',
             markersize=point_size,
             alpha=point_alpha, clip_on=False)

    # squeeze axis to the edges of the figure
    fig.subplots_adjust(left=0)
    fig.subplots_adjust(right=0.99)
    fig.subplots_adjust(bottom=0.1)
    fig.subplots_adjust(top=0.9)

    # save the figure to html
    bio = BytesIO()
    plt.savefig(bio)
    plt.close()
    html = """<img src="data:image/png;base64,%s"/>""" % base64.b64encode(bio.getvalue()).decode('utf-8')
    return html


def dot(color='gray', figsize=(.5, .5), **kwargs):

    fig = plt.figure(figsize=figsize)  # set figure size to be small
    ax = fig.add_subplot(111)

    ax.add_artist(plt.Circle((.5, .5), .25, color=color))

    # turn off all axis annotations
    ax.axis('off')

    # save the figure to html
    bio = BytesIO()
    plt.savefig(bio, dpi=300)
    plt.close()
    html = """<img style="height:40px;width:40px;" src="data:image/png;base64,%s"/>""" % base64.b64encode(bio.getvalue()).decode('utf-8')
    return html


def convert_metric_status_table_to_html(df: pd.DataFrame, title=None, include_actionability_score=False,
                                        sort_records_by_actionability=False, sort_records_by_value=False,
                                        font_color='#3C3C3C', title_color='#2A3F5F'):

    _df = df.copy()

    if sort_records_by_actionability and sort_records_by_value:
        if 'Actionability Score' in _df.columns and 'Current Value' in _df.columns:
            _df = _df.assign(
                sorting_key=lambda df: df['Actionability Score'] * df['Current Value'],
            ).sort_values(
                by='sorting_key',
                ascending=False,
            ).drop(
                columns=['sorting_key']
            )
        elif sort_records_by_value:
            _df = _df.sort_values(key=lambda r: r['Current Value'])
        elif sort_records_by_actionability:
            _df = _df.sort_values(key=lambda r: r['Actionability Score'])
        else:
            pass

    if include_actionability_score is False and 'Actionability Score' in _df.columns:
        _df = _df[[c for c in _df.columns if c != 'Actionability Score']]

    _output = _df.style.set_table_styles(
        [{'selector': '.row_heading',
          'props': [('display', 'none')]},
         {'selector': '.col_heading',
          'props': [('display', 'none')]},
         {'selector': '.blank.level0',
          'props': [('display', 'none')]},
         {'selector': '.data',
          'props': [
              ('font-family', 'Arial'),
              ('color', font_color),
              ('border-width', 0),
              ('text-align', 'left'),
          ]}]
    ).format({
        'Current Value': '{:.0f}',
        'Metric': f'<b style="color: {title_color}">{{}}</b>'
    }).bar(
        'Current Value',
        color='lightgray',
    ).render(header=False, index=False)

    if title is not None:
        _output = f'<h4 style="color: {title_color};">{title}</h4>' + _output

    return _output