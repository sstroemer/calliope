"""
Copyright (C) 2013-2017 Calliope contributors listed in AUTHORS.
Licensed under the Apache 2.0 License (see LICENSE file).

model.py
~~~~~~~~

Implements the core Model class.

"""

import numpy as np

from calliope.analysis import plotting as plot

from calliope.core import debug, io
from calliope.core.preprocess import \
    model_run_from_yaml, \
    model_run_from_dict, \
    build_model_data, \
    apply_time_clustering, \
    final_timedimension_processing
from calliope.core.util.tools import log_time
from calliope.core.util.dataset import split_loc_techs
from calliope import exceptions

from calliope.backend.pyomo import run as run_pyomo
# from calliope.backend.julia import run as run_julia

BACKEND_RUNNERS = {
    'pyomo': run_pyomo,
    # 'julia': run_julia
}


def read_netcdf(path):
    """
    Return a Model object reconstructed from model data in a NetCDF file.

    """
    model_data = io.read_netcdf(path)
    return Model(config=None, model_data=model_data)


class Model(object):
    """
    A Calliope Model.

    """
    def __init__(self, config, model_data=None, *args, **kwargs):
        """
        Returns a new Model from either the path to a run configuration file
        or a dict containing 'run' and 'model' keys fully specifying the
        model.

        Parameters
        ----------
        config : str or dict or AttrDict
            If str, must be the path to a run configuration file.
            If dict or AttrDict, must contain two top-level keys, model and run,
            specifying the model and run configuration respectively.
        model_data : Dataset, optional
            Create a Model instance from a fully built model_data Dataset.
            Only used if `config` is explicitly set to None.

        """
        self._timings = {}
        log_time(self._timings, 'model_creation')
        if isinstance(config, str):
            model_run, debug_data = model_run_from_yaml(config, *args, **kwargs)
            self._init_from_model_run(model_run, debug_data)
        elif isinstance(config, dict):
            model_run, debug_data = model_run_from_dict(config, *args, **kwargs)
            self._init_from_model_run(model_run, debug_data)
        elif model_data is not None and config is None:
            self._init_from_model_data(model_data)
        else:
            # expected input is a string pointing to a YAML file of the run
            # configuration or a dict/AttrDict in which the run and model
            # configurations are defined
            raise ValueError(
                'Input configuration must either be a string or a dictionary.'
            )

    def _init_from_model_run(self, model_run, debug_data):
        self._model_run = model_run
        self._debug_data = debug_data
        log_time(self._timings, 'model_run_creation')

        self._model_data_original = build_model_data(model_run)
        log_time(self._timings, 'model_data_original_creation')

        random_seed = self._model_run.get_key('run.random_seed', None)
        if random_seed:
            np.random.seed(seed=random_seed)

        # After setting the random seed, time clustering can take place
        time_config = model_run.model.get('time', None)
        if not time_config:
            self._model_data = final_timedimension_processing(self._model_data_original)
        else:
            clustered_model_data = apply_time_clustering(
                self._model_data_original, model_run
            )
            self._model_data = final_timedimension_processing(clustered_model_data)
        log_time(self._timings, 'model_data_creation', time_since_start=True)

        for var in self._model_data.data_vars:
            self._model_data[var].attrs['is_result'] = 0
        self.inputs = self._model_data.filter_by_attrs(is_result=0)

    def _init_from_model_data(self, model_data):
        self._model_run = None
        self._debug_data = None
        self._model_data = model_data
        self.inputs = self._model_data.filter_by_attrs(is_result=0)

        results = self._model_data.filter_by_attrs(is_result=1)
        if len(results.data_vars) > 0:
            self.results = results
        log_time(self._timings, 'model_data_loaded', time_since_start=True)

    def save_debug_data(self, path):
        """
        Save fully built and commented model_run to a YAML file at the
        given path, for debug purposes.

        """
        debug.save_debug_data(self._model_run, self._debug_data, path)

    def run(self, force_rerun=False):
        """
        Run the model. if force_rerun is True, any existing results will be
        overwritten.

        """

        if hasattr(self, 'results') and not force_rerun:
            raise exceptions.ModelError(
                'This model object already has results, set force_rerun to True'
                ' to force the results to be overwritten with a new run.'
            )

        backend = self._model_data.attrs['run.backend']
        results, self._backend_model = BACKEND_RUNNERS[backend](self._model_data, self._timings)

        for var in results.data_vars:
            results[var].attrs['is_result'] = 1

        # FIXME: possibly add some summary tables to results

        self._model_data = self._model_data.merge(results)

        self.results = self._model_data.filter_by_attrs(is_result=1)

    def get_formatted_array(self, var):
        """
        Return an xr.DataArray with locs, techs, and carriers as separate
        dimensions. Can be used to view input/output as in calliope < v0.6.0.

        """
        if var not in self._model_data.data_vars:
            raise KeyError("Variable {} not in Model data".format(var))

        return split_loc_techs(self._model_data[var])

    def to_netcdf(self, path):
        """
        Save complete model data (inputs and, if available, results)
        to a NetCDF file at the given path.

        """
        io.save_netcdf(self._model_data, path)

    def to_csv(self, path):
        """
        Save complete model data (inputs and, if available, results)
        as a set of CSV files to the given path.

        """
        io.save_csv(self._model_data, path)

    def plot(self, plot_type, plot_var=None, **kwargs):
        """
        plot data for input/output

        Parameters
        ----------
        plot_type : string; 'timeseries', 'capacity', or 'transmission'
            timeseries = data plotted against the time axis, must be data in
                the time domain
            capacity = data plotted per location on x-axis and per technology
                in a stacked bar. Can be any data input, provided array is only
                indexed over locations and technologies after selecting and summing
                over other dimensions (using loc=dict(...) and sum_dims=[...])
            transmission = data plotted based on coordinates.
                If coordinates are `lat`, `lon` then a map is used, otherwise
                cartesian scatter is used.
        plot_var : string
            variable from input/result xarray Dataset to plot. If `carrier_prod`
            or `carrier_con` given, sum of both will be plotted
        kwargs:
            loc = dictionary by which data is selected for timeseries/capacity
                plot types (keys any of ['timeseries', 'locs', 'techs', 'carriers'])
            sum_dims = list of dimension names to sum plot_var.
            squeeze = bool stating whether to squeeze out dimensions containing
                only single values

        """
        if plot_type == 'timeseries':
            if plot_var in ['carrier_prod', 'carrier_con']:
                plot_var = 'carrier'
            plot.plot_timeseries(self, timeseries_type=plot_var, **kwargs)

        elif plot_type == 'capacity':
            plot.plot_capacity(self, cap_type=plot_var, **kwargs)

        elif plot_type == 'transmission':
            plot.plot_transmission(self, **kwargs)
