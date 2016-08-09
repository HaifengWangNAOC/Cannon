from __future__ import (absolute_import, division, print_function, unicode_literals)
import numpy as np
import matplotlib.pyplot as plt
from .helpers.compatibility import range, map
from .helpers.corner import corner
import scipy.optimize as op

def training_step_objective_function(pars, fluxes_m, ivars_m, lvec, lvec_derivs, ldelta):
    """
    This is just for a single lambda.
    """
    coeff_m = pars[:-1]
    scatter_m = pars[-1] 
    nstars = len(ivars_m)
    Delta2 = np.zeros((nstars))
    for n in range(nstars):
        ldelta2 = np.outer(ldelta[n], ldelta[n])    # 4x4 matrix
        Delta2[n] = np.dot(np.dot(coeff_m.T, lvec_derivs[n]), np.dot(ldelta2, np.dot(lvec_derivs[n].T, coeff_m)))
    inv_var = ivars_m / (1. + ivars_m * (Delta2 + scatter_m ** 2))
    lnLs = 0.5 * np.log(inv_var / (2. * np.pi)) - 0.5 * (fluxes_m - np.dot(coeff_m, lvec.T))**2 * inv_var
    return -np.sum(lnLs)

def train_one_wavelength(fluxes_m, ivars_m, lvec, lvec_derivs, ldelta):
    x0 = np.zeros((len(lvec_derivs[0])+1,))
    x0[0] = 1.
    res = op.minimize(training_step_objective_function, x0, args=(fluxes_m, ivars_m, lvec, lvec_derivs, ldelta), method='Powell')
    coeff_m = res.x[:-1]
    scatter_m = res.x[-1]
    
    return coeff_m, scatter_m
   
def _train_model_new(ds):
    
    label_vals = ds.tr_label
    lams = ds.wl
    npixels = len(lams)
    fluxes = ds.tr_flux
    ivars = ds.tr_ivar
    ldelta = np.zeros((len(fluxes), len(label_vals[1]))) #ds.tr_delta
    
    # for training, ivar can't be zero, otherwise you get singular matrices
    # DWH says: make sure no ivar goes below 1 or 0.01
    ivars[ivars<0.01] = 0.01

    pivots = np.mean(label_vals, axis=0)
    lvec, lvec_derivs = _get_lvec(label_vals, pivots, derivs=True)
#    lvec = np.array([lvec,] * npixels)
#    lvec_derivs = np.array([lvec_derivs,] * npixels)
#    ldelta = np.array([ldelta,] * npixels)

    # Perform REGRESSIONS
    fluxes = fluxes.swapaxes(0,1)  # for consistency with lvec_full
    ivars = ivars.swapaxes(0,1)
    
    coeffs = []
    scatters = []
    for m in range(0, npixels):
        coeffs_m, scatter_m = train_one_wavelength(fluxes[m], ivars[m], lvec, lvec_derivs, ldelta)
        coeffs.append(coeffs_m)
        scatters.append(scatter_m)
    
    #blob = list(map(train_one_wavelength, fluxes, ivars, lvec, lvec_derivs, ldelta))
    #coeffs = np.array([b[0] for b in blob])
    #covs = np.array([np.linalg.inv(b[1]) for b in blob])
    #chis = np.array([b[2] for b in blob])
    #scatters = np.array([b[4] for b in blob])
    
    # Calc chi sq
    #all_chisqs = chis*chis
    all_chisqs = 0
    print("Done training model (Christina)")

    return np.array(coeffs), np.array(scatters), all_chisqs, pivots

def _do_one_regression_at_fixed_scatter(lams, fluxes, ivars, lvec, scatter):
    """
    Parameters
    ----------
    lams: numpy ndarray
        the common wavelength array

    fluxes: numpy ndarray
        flux values for all stars at one pixel
        
    ivars: numpy ndarray
        inverse variance values for all stars at one pixel

    lvec: numpy ndarray
        the label vector

    scatter: float
        fixed scatter value

    Returns
    ------
    coeff: ndarray
        coefficients of the fit

    lTCinvl: ndarray
        inverse covariance matrix for fit coefficients
    
    chi: float
        chi-squared at best fit
    
    logdet_Cinv: float
        inverse of the log determinant of the cov matrix
    """
    Cinv = ivars / (1 + ivars*scatter**2)
    lTCinvl = np.dot(lvec.T, Cinv[:, None] * lvec)
    lTCinvf = np.dot(lvec.T, Cinv * fluxes)
    try:
        coeff = np.linalg.solve(lTCinvl, lTCinvf)
    except np.linalg.linalg.LinAlgError:
        print("np.linalg.linalg.LinAlgError, do_one_regression_at_fixed_scatter")
        print(lTCinvl, lTCinvf, lams, fluxes)
    if not np.all(np.isfinite(coeff)):
        raise RuntimeError('something is wrong with the coefficients')
    chi = np.sqrt(Cinv) * (fluxes - np.dot(lvec, coeff))
    logdet_Cinv = np.sum(np.log(Cinv))
    return (coeff, lTCinvl, chi, logdet_Cinv)


def _do_one_regression(lams, fluxes, ivars, lvec):
    """
    Optimizes to find the scatter associated with the best-fit model.

    This scatter is the deviation between the observed spectrum and the model.
    It is wavelength-independent, so we perform this at a single wavelength.

    Input
    -----
    lams: numpy ndarray
        the common wavelength array

    fluxes: numpy ndarray
        pixel intensities

    ivars: numpy ndarray
        inverse variances associated with pixel intensities

    lvec = numpy ndarray 
        the label vector

    Output
    -----
    output of do_one_regression_at_fixed_scatter
    """
    ln_scatter_vals = np.arange(np.log(0.0001), 0., 0.5)
    # minimize over the range of scatter possibilities
    chis_eval = np.zeros_like(ln_scatter_vals)
    for jj, ln_scatter_val in enumerate(ln_scatter_vals):
        coeff, lTCinvl, chi, logdet_Cinv = \
            _do_one_regression_at_fixed_scatter(lams, fluxes, ivars, lvec,
                                               scatter=np.exp(ln_scatter_val))
        chis_eval[jj] = np.sum(chi*chi) - logdet_Cinv
    if np.any(np.isnan(chis_eval)):
        best_scatter = np.exp(ln_scatter_vals[-1])
        _r = _do_one_regression_at_fixed_scatter(lams, fluxes, ivars, lvec,
                                                scatter=best_scatter)
        return _r + (best_scatter, )
    lowest = np.argmin(chis_eval)
    if (lowest == 0) or (lowest == len(ln_scatter_vals) - 1):
        best_scatter = np.exp(ln_scatter_vals[lowest])
        _r = _do_one_regression_at_fixed_scatter(lams, fluxes, ivars, lvec,
                                                scatter=best_scatter)
        return _r + (best_scatter, )
    ln_scatter_vals_short = ln_scatter_vals[np.array(
        [lowest-1, lowest, lowest+1])]
    chis_eval_short = chis_eval[np.array([lowest-1, lowest, lowest+1])]
    z = np.polyfit(ln_scatter_vals_short, chis_eval_short, 2)
    fit_pder = np.polyder(z)
    best_scatter = np.exp(np.roots(fit_pder)[0])
    _r = _do_one_regression_at_fixed_scatter(lams, fluxes, ivars, lvec,
                                            scatter=best_scatter)
    return _r + (best_scatter, )


def _get_lvec(label_vals, pivots, derivs):
    """
    Constructs a label vector for an arbitrary number of labels
    Assumes that our model is quadratic in the labels
    
    Comment: this is really slow, but we will only have to compute it once!

    Parameters
    ----------
    label_vals: numpy ndarray, shape (nstars, nlabels)
        labels 
    pivots: numpy ndarray
        mean of the label_vals
    derivs: return also the derivatives of the vector wrt the labels

    Returns
    -------
    lvec: numpy ndarray
        label vector
    dlvec_dl: numpy ndarray (if derivs)
        label vector derivatives
    """
    nlabels = label_vals.shape[1]
    nstars = label_vals.shape[0]
    # specialized to second-order model
    linear_offsets = label_vals - pivots
    quadratic_offsets = np.array([np.outer(m, m)[np.triu_indices(nlabels)]
                                  for m in (linear_offsets)])
    ones = np.ones((nstars, 1))
    lvec = np.hstack((ones, linear_offsets, quadratic_offsets))
    if not derivs:
        return lvec
    ones_derivs = np.zeros((nstars, 1, nlabels))
    linear_derivs = np.zeros((nstars, nlabels, nlabels))
    for i in range(nstars):
        linear_derivs[i] = np.eye(nlabels) 
    quadratic_derivs = np.zeros((nstars, len(quadratic_offsets[1]), nlabels))
    for n in range(nstars):
        for k in range(nlabels): 
            foo = np.zeros((nlabels, nlabels))
            foo[k, :] = linear_offsets[n]
            foo[:, k] = linear_offsets[n]
            quadratic_derivs[n, :, k] = np.array(foo[np.triu_indices(nlabels)]) 
    lvec_derivs = np.hstack((ones_derivs, linear_derivs, quadratic_derivs))
    
    return lvec, lvec_derivs

def _train_model(ds):
    """
    This determines the coefficients of the model using the training data

    Parameters
    ----------
    ds: Dataset

    Returns
    -------
    model: model
        best-fit Cannon model
    """
    label_names = ds.get_plotting_labels()
    label_vals = ds.tr_label
    lams = ds.wl
    npixels = len(lams)
    fluxes = ds.tr_flux
    ivars = ds.tr_ivar
    
    # for training, ivar can't be zero, otherwise you get singular matrices
    # DWH says: make sure no ivar goes below 1 or 0.01
    ivars[ivars<0.01] = 0.01

    pivots = np.mean(label_vals, axis=0)
    lvec, lvec_derivs = _get_lvec(label_vals, pivots, derivs=True)
    lvec_full = np.array([lvec,] * npixels)

    # print np.shape(ivars), np.shape(fluxes), lvec.shape, lvec_full.shape

    # Perform REGRESSIONS
    fluxes = fluxes.swapaxes(0,1)  # for consistency with lvec_full
    ivars = ivars.swapaxes(0,1)
    
    # one per pix
    blob = list(map(_do_one_regression, lams, fluxes, ivars, lvec_full))
    coeffs = np.array([b[0] for b in blob])
    covs = np.array([np.linalg.inv(b[1]) for b in blob])
    chis = np.array([b[2] for b in blob])
    scatters = np.array([b[4] for b in blob])

    # Calc chi sq
    all_chisqs = chis*chis
    print("Done training model (Anna)")

    return coeffs, scatters, all_chisqs, pivots
