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


def get_default_prior(func, nfunc, **kwargs):
    """Construct a default set of priors for the basis function."""
    nfunc_min = kwargs.pop('nfunc_min', 1)
    global_bias = kwargs.pop('global_bias', False)
    adaptive = kwargs.pop('adaptive', False)
    if kwargs:
        raise TypeError('Unexpected **kwargs: {0}'.format(kwargs))
    assert not global_bias
    # specify default priors
    if func.__name__[:2] == 'nn':
        assert isinstance(nfunc, list)
        assert len(nfunc) >= 2
        prior_blocks = [Gaussian(10.0)]
        block_sizes = [nn.nn_num_params(nfunc)]
        if adaptive:
            assert len(set(nfunc[1:])) == 1, nfunc
            prior_blocks = ([Uniform(nfunc_min - 0.5, nfunc[1] + 0.5)]
                            + prior_blocks)
            block_sizes = [1] + block_sizes
    elif func.__name__ == 'adfam_gg_ta_1d':
        assert adaptive
        # Need to explicitly provide all args rather than use **kwargs as
        # kwargs is now empty due to poping
        gg_prior = get_default_prior(bf.gg_1d, nfunc, global_bias=global_bias,
                                     nfunc_min=nfunc_min, adaptive=adaptive)
        ta_prior = get_default_prior(bf.ta_1d, nfunc, global_bias=global_bias,
                                     nfunc_min=nfunc_min, adaptive=adaptive)
        return AdFamPrior(gg_prior, ta_prior, nfunc)
    elif func.__name__ in ['gg_1d', 'gg_2d', 'ta_1d', 'ta_2d']:
        if func.__name__ in ['gg_1d', 'gg_2d']:
            priors_dict = {'a':     Exponential(
                2.0, nfunc_min=nfunc_min, adaptive=adaptive, sort=True),
                           'mu':    Uniform(0, 1.0),
                           'sigma': Exponential(2.0),
                           'beta':  Exponential(0.5)}
            if func.__name__ == 'gg_2d':
                for param in ['mu', 'sigma', 'beta']:
                    priors_dict[param + '1'] = priors_dict[param]
                    priors_dict[param + '2'] = priors_dict[param]
                    del priors_dict[param]  # Causes error if accidentally used
                priors_dict['omega'] = Uniform(-0.25 * np.pi, 0.25 * np.pi)
        elif func.__name__ in ['ta_1d', 'ta_2d']:
            priors_dict = {'a':           Exponential(
                0.5, nfunc_min=nfunc_min, adaptive=adaptive, sort=True),
                           'w_0':         Gaussian(10.0),
                           'w_1':         Gaussian(10.0),
                           'w_2':         Gaussian(10.0)}
        # Get a list of the priors we want
        args = bf.get_bf_param_names(func)
        prior_blocks = [priors_dict[arg] for arg in args]
        block_sizes = [nfunc] * len(args)
        if adaptive:
            block_sizes[0] += 1
    else:
        raise AssertionError('not yet set up for {}'.format(func.__name__))
    return BlockPrior(prior_blocks, block_sizes)


class BasePrior(object):

    """Base class for Priors."""

    def __init__(self, adaptive=False, sort=False, nfunc_min=1):
        """
        Set up prior object's hyperparameter values.

        Parameters
        ----------
        adaptive: bool, optional
        sort: bool, optional
        nfunc_min: int, optional
        """
        self.adaptive = adaptive
        self.sort = sort
        self.nfunc_min = nfunc_min

    def cube_to_physical(self, cube):  # pylint: disable=no-self-use
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        cube: 1d numpy array
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: 1d numpy array
            Physical parameter values corresponding to hypercube.
        """
        return cube

    def __call__(self, cube):
        """
        Evaluate prior on hypercube coordinates.

        Parameters
        ----------
        cube: 1d numpy array
            Point coordinate on unit hypercube (in probabily space).

        Returns
        -------
        theta: 1d numpy array
            Physical parameter values for prior.
        """
        if self.adaptive:
            try:
                nfunc, theta = adaptive_transform(cube, self.nfunc_min)
            except ValueError:
                if np.isnan(cube[0]):
                    return np.full(cube.shape, np.nan)
                else:
                    raise
            if self.sort:
                cube[1:1 + nfunc] = forced_identifiability(
                    cube[1:1+ nfunc])
            # perform prior on adaptively selected components
            theta[1:] = self.cube_to_physical(cube[1:])
            return theta
        else:
            if self.sort:
                cube = forced_identifiability(cube)
            return self.cube_to_physical(cube)


class Gaussian(BasePrior):

    """Symmetric Gaussian prior centred on the origin."""

    def __init__(self, sigma=10.0, positive=False, **kwargs):
        """
        Set up prior object's hyperparameter values.

        Parameters
        ----------
        sigma: float
            Standard deviation of Gaussian prior in each parameter.
        positive: bool
            Whether or not to use a truncated Gaussian prior where values are
            always positive.
        kwargs: dict, optional
            See BasePrior.__init__ for more infomation.
        """
        BasePrior.__init__(self, **kwargs)
        self.sigma = sigma
        self.positive = positive

    def cube_to_physical(self, cube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        cube: 1d numpy array
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: 1d numpy array
            Physical parameter values corresponding to hypercube.
        """
        if self.positive:
            theta = scipy.special.erfinv(cube)
        else:
            theta = scipy.special.erfinv(2 * cube - 1)
        theta *= self.sigma * np.sqrt(2)
        return theta


class Uniform(BasePrior):

    """Uniform prior."""

    def __init__(self, minimum=0.0, maximum=1.0, **kwargs):
        """
        Set up prior object's hyperparameter values.

        Prior is uniform in [minimum, maximum] in each parameter.

        Parameters
        ----------
        minimum: float
        maximum: float
        kwargs: dict, optional
            See BasePrior.__init__ for more infomation.
        """
        BasePrior.__init__(self, **kwargs)
        assert maximum > minimum
        self.maximum = maximum
        self.minimum = minimum

    def cube_to_physical(self, cube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        cube: 1d numpy array

        Returns
        -------
        theta: 1d numpy array
        """
        return self.minimum + (self.maximum - self.minimum) * cube


class Exponential(BasePrior):

    """Exponential prior."""

    def __init__(self, lambd=1.0, **kwargs):
        """
        Set up prior object's hyperparameter values.

        Parameters
        ----------
        lambd: float
        kwargs: dict, optional
            See BasePrior.__init__ for more infomation.
        """
        BasePrior.__init__(self, **kwargs)
        self.lambd = lambd

    def cube_to_physical(self, cube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        cube: 1d numpy array

        Returns
        -------
        theta: 1d numpy array
        """
        return - np.log(1 - cube) / self.lambd


class AdFamPrior(object):

    """Prior for adaptive selection between different families of basis
    functions. First coordinate selects family, then different priors are
    applied to the remaining coordinates depending on its value."""

    def __init__(self, gg_1d_prior, ta_1d_prior, nfunc):
        """Store the different blocks and block sizes for each family."""
        self.gg_1d_prior = gg_1d_prior
        self.ta_1d_prior = ta_1d_prior
        self.nfunc = nfunc

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
        theta[0] = Uniform(0.5, 2.5)(cube[0])
        # Calculate gg prior even if func is ta, so parameters unused by ta
        # are drawn from the gg prior
        theta[1:] = self.gg_1d_prior(cube[1:])
        if theta[0] >= 1.5:
            theta[1:-self.nfunc] = self.ta_1d_prior(cube[1:-self.nfunc])
        return theta


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


def forced_identifiability(cube):
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
