#!/usr/bin/env python
"""
Python priors for use with PolyChord.

PolyChord v1.14 requires priors to be callables with parameter and return
types:

Parameters
----------
hypercube: 1d numpy array
    Parameter positions in the prior hypercube.

Returns
-------
theta: 1d numpy array
    Corresponding physical parameter coordinates.

Input hypercube values numpy array is mapped to physical space using the
inverse CDF (cumulative distribution function) of each parameter.
See the PolyChord papers for more details.

We use classes with the prior defined in the __call__ property, as
this provides convenient way of storing other information such as
hyperparameter values. The objects be used in the same way as functions
due to python's "duck typing" (or alternatively you can just define prior
functions).
"""
import numpy as np
import scipy
import bsr.basis_functions as bf
import bsr.neural_networks as nn


def get_default_prior(func, nfunc, adaptive=False, **kwargs):
    """Construct a default set of priors for the basis function."""
    nfunc_min = kwargs.pop('nfunc_min', 1)
    global_bias = kwargs.pop('global_bias', False)
    if kwargs:
        raise TypeError('Unexpected **kwargs: {0}'.format(kwargs))
    assert not global_bias
    # specify default priors
    if func.__name__ == 'nn_fit':
        assert isinstance(nfunc, list)
        assert len(nfunc) >= 2
        prior_blocks = [Gaussian(10.0)]
        block_sizes = [nn.nn_num_params(nfunc)]
        if adaptive:
            assert len(set(nfunc[1:])) == 1, nfunc
            prior_blocks = ([Uniform(nfunc_min - 0.5, nfunc[1] + 0.5)]
                            + prior_blocks)
            block_sizes = [1] + block_sizes
    elif func.__name__ in ['gg_1d', 'gg_2d', 'ta_1d', 'ta_2d']:
        if func.__name__ in ['gg_1d', 'gg_2d']:
            priors_dict = {'a':     SortedExponential(2.0),
                           'mu':    Uniform(0, 1.0),
                           'sigma': Exponential(2.0),
                           'beta':  Exponential(0.5)}
            if adaptive:
                priors_dict['a'] = AdaptiveSortedExponential(
                    nfunc_min=nfunc_min, **priors_dict['a'].__dict__)
            if func.__name__ == 'gg_2d':
                for param in ['mu', 'sigma', 'beta']:
                    priors_dict[param + '1'] = priors_dict[param]
                    priors_dict[param + '2'] = priors_dict[param]
                    del priors_dict[param]  # Causes error if accidentally used
                priors_dict['omega'] = Uniform(-0.25 * np.pi, 0.25 * np.pi)
        elif func.__name__ in ['ta_1d', 'ta_2d']:
            priors_dict = {'a':           SortedExponential(0.5),
                           'w_0':         Gaussian(10.0),
                           'w_1':         Gaussian(10.0),
                           'w_2':         Gaussian(10.0)}
            if adaptive:
                priors_dict['a'] = AdaptiveSortedExponential(
                    nfunc_min=nfunc_min, **priors_dict['a'].__dict__)
        # Get a list of the priors we want
        args = bf.get_bf_param_names(func)
        prior_blocks = [priors_dict[arg] for arg in args]
        block_sizes = [nfunc] * len(args)
        if adaptive:
            block_sizes[0] += 1
    else:
        raise AssertionError('not yet set up for {}'.format(func.__name__))
    return BlockPrior(prior_blocks, block_sizes)


class Gaussian(object):

    """Symmetric Gaussian prior centred on the origin."""

    def __init__(self, sigma=10.0):
        """
        Set up prior object's hyperparameter values.

        Parameters
        ----------
        sigma: float
            Standard deviation of Gaussian prior in each parameter.
        """
        self.sigma = sigma

    def __call__(self, hypercube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        hypercube: 1d numpy array
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: 1d numpy array
            Physical parameter values corresponding to hypercube.
        """
        theta = scipy.special.erfinv(2 * hypercube - 1)
        theta *= self.sigma * np.sqrt(2)
        return theta


class Uniform(object):

    """Uniform prior."""

    def __init__(self, minimum=0.0, maximum=1.0):
        """
        Set up prior object's hyperparameter values.

        Prior is uniform in [minimum, maximum] in each parameter.

        Parameters
        ----------
        minimum: float
        maximum: float
        """
        assert maximum > minimum
        self.maximum = maximum
        self.minimum = minimum

    def __call__(self, hypercube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        hypercube: 1d numpy array
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: 1d numpy array
            Physical parameter values corresponding to hypercube.
        """
        return self.minimum + (self.maximum - self.minimum) * hypercube


class Exponential(object):

    """Exponential prior."""

    def __init__(self, lambd=1.0):
        """
        Set up prior object's hyperparameter values.

        Parameters
        ----------
        lambd: float
        """
        self.lambd = lambd

    def __call__(self, hypercube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        hypercube: 1d numpy array
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: 1d numpy array
            Physical parameter values corresponding to hypercube.
        """
        return - np.log(1 - hypercube) / self.lambd


class SortedUniform(Uniform):

    """Uniform prior with sorting imposed so values have decreasing size."""

    def __call__(self, cube):
        """See Uniform.__call__ docstring."""
        ordered = forced_identifiability_transform(cube)
        return super(SortedUniform, self).__call__(ordered)


class SortedExponential(Exponential):

    """Exponential prior with sorting imposed so values have decreasing
    size."""

    def __call__(self, cube):
        """See Exponential.__call__ docstring."""
        ordered = forced_identifiability_transform(cube)
        return super(SortedExponential, self).__call__(ordered)


class AdaptiveSortedUniform(SortedUniform):

    """Adaptive sorted uniform prior."""

    def __init__(self, minimum=0.0, maximum=1.0, nfunc_min=1):
        """
        Set up prior object's hyperparameter values.

        Parameters
        ----------
        minimum: float
        maximum: float
        nfunc_min: int, optional
        """
        SortedUniform.__init__(self, minimum, maximum)
        self.minimum = minimum
        self.maximum = maximum
        self.nfunc_min = nfunc_min

    def __call__(self, cube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        hypercube: 1d numpy array
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: 1d numpy array
            Physical parameter values corresponding to hypercube.
        """
        try:
            nfunc, theta = adaptive_transform(cube, self.nfunc_min)
            # perform SortedUniform on the next nfunc components
            theta[1:1 + nfunc] = SortedUniform.__call__(self,
                                                        cube[1:1 + nfunc])
            # do uniform prior on remaining components
            if len(cube) > 1 + nfunc:
                theta[1 + nfunc:] = (
                    self.minimum + (self.maximum - self.minimum)
                    * cube[1 + nfunc:])
            return theta
        except ValueError:
            if np.isnan(cube[0]):
                return np.full(cube.shape, np.nan)
            else:
                raise


class AdaptiveSortedExponential(SortedExponential):

    """Adaptive sorted uniform prior."""

    def __init__(self, lambd=1.0, nfunc_min=1):
        """
        Set up prior object's hyperparameter values.

        Parameters
        ----------
        lambd: float
        nfunc_min: int, optional
        """
        SortedExponential.__init__(self, lambd=lambd)
        self.lamb = lambd
        self.nfunc_min = nfunc_min

    def __call__(self, cube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        hypercube: 1d numpy array
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: 1d numpy array
            Physical parameter values corresponding to hypercube.
        """
        try:
            nfunc, theta = adaptive_transform(cube, self.nfunc_min)
            # perform SortedExponential on the next nfunc components
            theta[1:1 + nfunc] = SortedExponential.__call__(
                self, cube[1:1 + nfunc])
            # do uniform prior on remaining components
            if len(cube) > 1 + nfunc:
                theta[1 + nfunc:] = Exponential(self.lambd)(cube[1 + nfunc:])
            return theta
        except ValueError:
            if np.isnan(cube[0]):
                return np.full(cube.shape, np.nan)
            else:
                raise


class BlockPrior(object):

    """Prior object which applies a list of priors to different blocks within
    the parameters."""

    def __init__(self, prior_blocks, block_sizes):
        """Store prior and size of each block."""
        assert len(prior_blocks) == len(block_sizes), (
            'len(prior_blocks)={}, len(block_sizes)={}, block_sizes={}'
            .format(len(prior_blocks), len(block_sizes), block_sizes))
        self.prior_blocks = prior_blocks
        self.block_sizes = block_sizes

    def __call__(self, cube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        hypercube: 1d numpy array
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: 1d numpy array
            Physical parameter values corresponding to hypercube.
        """
        theta = np.zeros(cube.shape)
        start = 0
        end = 0
        for i, prior in enumerate(self.prior_blocks):
            end += self.block_sizes[i]
            theta[start:end] = prior(cube[start:end])
            start += self.block_sizes[i]
        return theta


# Helper functions
# ----------------


def forced_identifiability_transform(cube):
    """Transform hypercube coordinates to enforce identifiability.
    Note that the formula in the MNRAS PolyChord paper (2015) contains a typo.

    Parameters
    ----------
    cube: 1d numpy array
        Point coordinate on unit hypercube (in probabily space).

    Returns
    -------
    ordered_cube: 1d numpy array
    """
    ordered_cube = np.zeros(cube.shape)
    ordered_cube[-1] = cube[-1] ** (1. / cube.shape[0])
    for n in range(cube.shape[0] - 2, -1, -1):
        ordered_cube[n] = cube[n] ** (1. / (n + 1)) * ordered_cube[n + 1]
    return ordered_cube


def adaptive_transform(cube, nfunc_min):
    """Extract adaptive number of functions and return theta array.

    Parameters
    ----------
    cube: 1d numpy array
        Point coordinate on unit hypercube (in probabily space).

    Returns
    -------
    nfunc: int
    theta: 1d numpy array
        First element is physical coordinate of nfunc parameter, other elements
        are zero.
    """
    # First get integer number of funcs
    theta = np.zeros(cube.shape)
    nfunc_max = cube.shape[0] - 1
    # first component is a number of funcs
    theta[0] = ((nfunc_min - 0.5)
                + (1.0 + nfunc_max - nfunc_min) * cube[0])
    nfunc = int(np.round(theta[0]))
    return nfunc, theta
