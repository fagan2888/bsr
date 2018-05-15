#!/usr/bin/env python
"""
Python priors for use with PolyChord.

PolyChord v1.14 requires priors to be callables with parameter and return
types:

Parameters
----------
hypercube: float or 1d numpy array
    Parameter positions in the prior hypercube.

Returns
-------
theta: float or 1d numpy array
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
        hypercube: list of floats
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: list of floats
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
        hypercube: list of floats
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: list of floats
            Physical parameter values corresponding to hypercube.
        """
        return self.minimum + (self.maximum - self.minimum) * hypercube


class SortedUniform(Uniform):

    """Uniform prior with sorting imposed so values have decreasing size."""

    def __call__(self, cube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        hypercube: list of floats
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: list of floats
            Physical parameter values corresponding to hypercube.
        """
        theta = np.zeros(cube.shape)
        theta[-1] = cube[-1] ** (1. / cube.shape[0])
        for n in range(cube.shape[0] - 2, -1, -1):
            theta[n] = cube[n] ** (1. / (n + 1)) * theta[n + 1]
        return Uniform.__call__(self, theta)


class AdaptiveSortedUniform(SortedUniform):

    """Adaptive sorted uniform prior."""

    def __init__(self, minimum, maximum, nfuncs_min=1):
        """
        Set up prior object's hyperparameter values.

        Parameters
        ----------
        minimum: float
        maximum: float
        nfuncs_min: int, optional
        """
        SortedUniform.__init__(self, minimum, maximum)
        self.minimum = minimum
        self.maximum = maximum
        self.nfuncs_min = nfuncs_min

    def __call__(self, cube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        hypercube: list of floats
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: list of floats
            Physical parameter values corresponding to hypercube.
        """
        # First get integer number of funcs
        theta = np.zeros(cube.shape)
        nfuncs_max = cube.shape[0] - 1
        # first component is a number of funcs
        theta[0] = ((self.nfuncs_min - 0.5)
                    + (1.0 + nfuncs_max - self.nfuncs_min) * cube[0])
        nfuncs = int(np.round(theta[0]))
        # perform SortedUniform on the next nfuncs components
        theta[1:1 + nfuncs] = SortedUniform.__call__(self, cube[1:1 + nfuncs])
        # do uniform prior on remaining components
        if len(cube) > 1 + nfuncs:
            theta[1 + nfuncs:] = (self.minimum
                                  + (self.maximum - self.minimum)
                                  * cube[1 + nfuncs:])
        return theta


class BlockPrior(object):

    """Prior object which applies a list of priors to different blocks within
    the parameters."""

    def __init__(self, priors, block_sizes):
        """Store prior and size of each block."""
        assert len(priors) == len(block_sizes)
        self.priors = priors
        self.block_sizes = block_sizes

    def __call__(self, cube):
        """
        Map hypercube values to physical parameter values.

        Parameters
        ----------
        hypercube: list of floats
            Point coordinate on unit hypercube (in probabily space).
            See the PolyChord papers for more details.

        Returns
        -------
        theta: list of floats
            Physical parameter values corresponding to hypercube.
        """
        theta = np.zeros(cube.shape)
        start = 0
        end = 0
        for i, prior in enumerate(self.priors):
            end += self.block_sizes[i]
            theta[start:end] = prior(cube[start:end])
            start += self.block_sizes[i]
