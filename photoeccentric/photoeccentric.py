import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

import scipy.constants as c
from tqdm import tqdm
import batman

import emcee
import corner

from .stellardensity import *
from .spectroscopy import *

def bls(time, nflux):
    """Applies astropy Box Least-Squares to light curve to fit period

    Parameters
    ----------
    time: np.array
        Time array
    nflux: np.array
        Flux array


    Returns
    -------
    per_guess: float
        Period fit from BLS
    """

    from astropy.timeseries import BoxLeastSquares
    import astropy.units as u

    mod = BoxLeastSquares(time*u.day, nflux, dy=0.01)
    periodogram = mod.autopower(0.2, objective="snr")
    per_guess = np.asarray(periodogram.period)[int(np.median(np.argmax(periodogram.power)))]

    return per_guess

def get_T14(p, rprs, a_rs, i, ecc_prior=False, e=None, w=None):
    """
    Calculates T14 (total transit duration, 1st to 4th contact).
    Assumes a circular orbit (e=0, w=0) if ecc_prior=False.
    If ecc_prior=True, e and w are required. T14 is multiplied by an eccentricity factor.

    Parameters
    ----------
    p: np.array
        Period (days)
    rprs: np.array
        Planet radius/stellar radius
    a_rs: np.array
        Semi-major axis (in stellar radii) (a/Rs)
    i: np.array
        Inclination (degrees)
    ecc: boolean
        Eccentricity taken into account? Default False
    e: float
        Eccentricity if ecc=True, default None
    w: float
        Longitude of periastron (degrees) if ecc=True, default None

    Returns
    -------
    T14: float
        Total transit duration (seconds)
    """
    nf = len(p)

    T14 = np.zeros(nf)
    rs_a = np.zeros(nf)
    b = np.zeros(nf)

    chidot = np.zeros(nf)

    for j in range(nf):

        p[j] = p[j]*86400

        rs_a[j] = 1.0/a_rs[j]                  # Rs/a - rstar in units of semimajor axis
        b[j] = a_rs[j]*np.cos(i[j]*(np.pi/180.0))   # convert i to radians

        T14[j] = (p[j]/np.pi)*np.arcsin(rs_a[j]*(np.sqrt(((1+rprs[j])**2)-b[j]**2))/np.sin(i[j]*(np.pi/180.0))) #Equation 14 in exoplanet textbook

        if ecc_prior==True:
            chidot[j] = np.sqrt(1-e[j]**2)/(1+e[j]*np.sin(w[j]*(np.pi/180.0))) #Equation 16 in exoplanet textbook
            return T14[j]*chidot[j]

    return T14


def get_T23(p, rprs, a_rs, i, ecc_prior=False, e=None, w=None):
    """
    Calculates T23 (full transit duration, 1st to 4th contact).
    Assumes a circular orbit (e=0, w=0) if ecc_prior=False.
    If ecc_prior=True, e and w are required. T23 is multiplied by an eccentricity factor.

    p: np.array
        Period (days)
    rprs: np.array
        Planet radius/stellar radius
    a_rs: np.array
        Semi-major axis (in stellar radii) (a/Rs)
    i: np.array
        Inclination (degrees)
    ecc: boolean
        Eccentricity taken into account? Default False
    e: float
        Eccentricity if ecc=True, default None
    w: float
        Longitude of periastron (degrees) if ecc=True, default None

    Returns
    -------
    T23: float
        Full transit time (seconds)
    """

    nf = len(p)

    T23 = np.zeros(nf)
    rs_a = np.zeros(nf)
    b = np.zeros(nf)

    chidot = np.zeros(nf)

    for j in range(nf):

        p[j] = p[j]#*86400

        rs_a[j] = 1.0/a_rs[j]                  # Rs/a - rstar in units of semimajor axis
        b[j] = a_rs[j]*np.cos(i[j]*(np.pi/180.0))   # convert i to radians

        T23[j] = (p[j]/np.pi)*np.arcsin(rs_a[j]*(np.sqrt(((1-rprs[j])**2)-b[j]**2))/np.sin(i[j]*(np.pi/180.0))) #Equation 14 in exoplanet textbook

        if ecc_prior==True:
            chidot[j] = np.sqrt(1-e[j]**2)/(1+e[j]*np.sin(w[j]*(np.pi/180.0))) #Equation 16 in exoplanet textbook
            return T23[j]*chidot[j]

    return T23


def calc_a(period, smass, srad):
    """Calculates semi-major axis from planet period and stellar mass
    Kepler's 3rd law

    Parameters
    ----------
    period: float
        Planet period (SECONDS)
    smass: float
        Stellar mass (KG)
    srad: float
        Stellar radius (METERS)

    Returns
    -------
    a: float
        a/Rs: Semi-major axis of planet's orbit (units of stellar radii)
    """

    a = np.cbrt((period**2*c.G*smass)/(4*np.pi**2*srad**3)) # a on rstar

    return a


def get_rho_circ(rprs, T14, T23, p):
    """Returns stellar density, assuming a perfectly circular planetary orbit.

    Parameters
    ----------
    rprs: float
        Planet radius/stellar radii
    T14: float
        Total transit time - first to fourth contact (seconds)
    T23: float
        Full transit time - second to third contact (seconds)
    p: float
        Orbital period (seconds)

    Returns
    -------
    rho_circ: float
        Stellar density, assuming a circular orbit (kg/m^3)
    """

    delta = rprs**2

    if T14 >= T23:
        rho_circ = (((2*(delta**(0.25)))/np.sqrt(T14**2-T23**2))**3)*((3*p)/(c.G*(c.pi**2)))
    else:
        rho_circ = np.nan

    return rho_circ

def get_planet_params(p, T14, T23):
    """Returns planet parameters in correct units.

    Parameters
    ----------
    p: float
        Planet orbital period (days)
    rp_earth: float
        Planet radius (earth radii)
    rs: float
        Stellar radius (solar radii)
    T14: float
        Total transit time - first to fourth contact (hours)
    a: float
        Planet semi-major axis (AU)
    i: float
        Orbital inclination (degrees)

    Returns
    -------
    p_seconds: float
        Orbital period (seconds)
    rprs: float
        Planet radius (stellar host radii)
    T14_seconds: float
        Total transit time - first to fourth contact (seconds)
    T23_seconds: float
        Full transit time - second to third contact (seconds)
    """

    p_seconds = p*86400
    T14_seconds = T14*3600
    T23_seconds = T23*3600

    return p_seconds, T14_seconds, T23_seconds


def get_g(rho_circ, rho_star):
    """Gets g

    Parameters
    ----------
    rho_circ: float
        Stellar density, assuming a circular orbit (kg/m^3)
    rho_star: float
        Stellar density, calculated from Kepler/Gaia/spectroscopy (kg/m^3)

    Returns
    -------
    g: float
        Cube root of ratio between rho_circ and rho_star
    """
    g = np.cbrt(rho_circ/rho_star)
    return g

def get_g_from_def(e, w):
    """Gets g from e and omega

    Parameters
    ----------
    e: float
        Eccentricity
    w: float
        Angle of periapse or something

    Returns
    -------
    g: float
        Cube root of ratio between rho_circ and rho_star
    """
    g = (1+e*np.sin(w))/np.sqrt(1-e**2)
    return g


def get_e(g, w):
    """Gets eccentricity (from photoeccentric effect)

    Parameters
    ----------
    g: float
        Cube root of ratio between rho_circ and rho_star
    w: float
        Angle of apoapse or periapse (?) (degrees, -90 < w < 90)

    Returns
    -------
    e: float
        Eccentricity of planet orbit
    """
    e = (np.sqrt(2)*(np.sqrt(2*g**4 - g**2*np.cos(2*w) - g**2 - 2*np.sin(w))))/(2*(g**2 + np.sin(w)**2))
    return e

def row_to_top(df, index):
    """Bring row to top

    Parameters
    ----------
    df: pandas.dataframe
        Dataframe to copy
    index: int
        Index of row to bring to top

    Returns
    -------
    df_cp: pandas.dataframe
        Copy of dataframe with specified row at top

    """
    df_cp = pd.concat([df.iloc[[index],:], df.drop(index, axis=0)], axis=0)
    return df_cp



def get_g_distribution(rhos, per_dist, rprs_dist, T14_dist, T23_dist):
    """Gets g distribution for a KOI.

    Parameters
    ----------
    rhos: np.array
        Density histogram
    per_dist: np.array
        Best-fit period (days)
    rprs_dist: np.array
        Best-fit rp/rs
    T14_dist: np.array
        Total transit duration (seconds) calculated from best-fit planet parameters
    T23_dist: np.array
        Full transit duration (seconds) calculated from best-fit planet parameters

    Returns
    -------
    gs: np.array
        g distribution for star/planet.
    rho_circ: np.array
        Density distribution assuming a circular orbit
    """

    gs = np.zeros((len(rhos)))
    rho_circ = np.zeros(len(rhos))

    #for element in histogram for star:
    for j in range(len(rhos)):

        per_dist[j] = per_dist[j]#*86400.

        rho_circ[j] = get_rho_circ(rprs_dist[j], T14_dist[j], T23_dist[j], per_dist[j])

        g = get_g(rho_circ[j], rhos[j])
        gs[j] = g

    return gs, rho_circ

def get_inclination(b, a_rs):
    """Get inclination (in degrees) from an impact parameter and semi-major axis (on stellar radius).

    Parameters
    ----------
    b: float
        Impact parameter
    a_rs: float
        Ratio of semi-major axis to stellar radius (a/Rs)

    Returns
    -------
    i: float
        Inclination (degrees)
    """

    i_radians = np.arccos(b*(1./a_rs))
    i = i_radians*(180./np.pi)
    return i

def stellar_params_from_archive(df, kep_name):
    """Get stellar parameters for the host of a KOI from exoplanet archive (downloaded data).

    Parameters
    ----------
    df: pandas.DataFrame
        dataframe of exop. archive downloaded data
    kep_name: str
        Kepler name of planet

    Returns
    -------
    smass: float
        Stellar mass (solar mass)
    srad: float
        Stellar radius (solar radius)
    limbdark_mod: str
        Limb darkening model
    ldm_c1: float
        Limb darkening coefficient 1
    ldm_c2: float
        Limb darkening coefficient 2

    """
    smass = float(df.loc[df['kepler_name'] == kep_name].koi_smass) #stellar mass (/solar mass)
    smass_uerr = float(df.loc[df['kepler_name'] == kep_name].koi_smass_err1) #stellar mass upper error
    smass_lerr = float(df.loc[df['kepler_name'] == kep_name].koi_smass_err2) #stellar mass lower error

    srad = float(df.loc[df['kepler_name'] == kep_name].koi_srad) #stellar radius (/solar radius)
    srad_uerr = float(df.loc[df['kepler_name'] == kep_name].koi_srad_err1) #stellar radius upper error
    srad_lerr = float(df.loc[df['kepler_name'] == kep_name].koi_srad_err2) #stellar radius lower error

    limbdark_mod = str(df.loc[df['kepler_name'] == kep_name].koi_limbdark_mod) #LDM Model
    ldm_c2 = float(df.loc[df['kepler_name'] == kep_name].koi_ldm_coeff2) #LDM coef 2
    ldm_c1 = float(df.loc[df['kepler_name'] == kep_name].koi_ldm_coeff1) #LDM coef 1

    return smass, smass_uerr, smass_lerr, srad, srad_uerr, srad_lerr, limbdark_mod, ldm_c1, ldm_c2

def planet_params_from_archive(df, kep_name):
    """Get stellar parameters for the host of a KOI from exoplanet archive (downloaded data).

    Parameters
    ----------
    df: pandas.DataFrame
        dataframe of exop. archive downloaded data
    kep_name: str
        Kepler name of planet

    Returns
    -------
    period: float
        Orbital period (days)
    rprs: float
        Planet radius (stellar radii)
    a: float
        Semi-major axis (stellar radii)
    e: float
        Eccentricity
    w: float
        Longitude of periastron (degrees)
    i: float
        Inclination (degrees)

    """

    period = float(df.loc[df['kepler_name'] == kep_name].koi_period) #period (days)
    period_uerr = float(df.loc[df['kepler_name'] == kep_name].koi_period_err1) #period upper error (days)
    period_lerr = float(df.loc[df['kepler_name'] == kep_name].koi_period_err2) #period lower error (days)

    rprs = float(df.loc[df['kepler_name'] == kep_name].koi_ror) #planet rad/stellar rad
    rprs_uerr = float(df.loc[df['kepler_name'] == kep_name].koi_ror_err1) #planet rad upper error (days)
    rprs_lerr = float(df.loc[df['kepler_name'] == kep_name].koi_ror_err2) #planet rad lower error (days)

    a_rs = float(df.loc[df['kepler_name'] == kep_name].koi_dor) #semi-major axis/r_star (a on Rstar)
    a_rs_uerr = float(df.loc[df['kepler_name'] == kep_name].koi_dor_err1) #semi-major axis/r_star upper error
    a_rs_lerr = float(df.loc[df['kepler_name'] == kep_name].koi_dor_err2) #semi-major axis/r_star upper error

    i = float(df.loc[df['kepler_name'] == kep_name].koi_incl) #inclination (degrees)

    e = float(df.loc[df['kepler_name'] == kep_name].koi_eccen) #eccentricity (assumed 0)
    w = float(df.loc[df['kepler_name'] == kep_name].koi_longp) #longtitude of periastron (assumed 0)

    return period, period_uerr, period_lerr, rprs, rprs_uerr, rprs_lerr, a_rs, a_rs_uerr, a_rs_lerr, i, e, w


def get_sigmas(dist):
    """Gets + and - sigmas from a distribution (gaussian or not). Ignores nan values.

    Parameters
    ----------
    dist: np.array
        Distribution from which sigmas are needed

    Returns
    -------
    sigma_minus: float
        - sigma
    sigma_plus: float
        + sigma
    """

    sigma_minus = np.nanpercentile(dist, 50)-np.nanpercentile(dist, 16)
    sigma_plus = np.nanpercentile(dist, 84)-np.nanpercentile(dist, 50)

    return sigma_minus, sigma_plus

def get_e_from_def(g, w):
    """Gets eccentricity from definition (eqn 4)

    Parameters
    ----------
    g: float
        g value
    w: float
        Omega (angle periapse/apoapse)

    Returns
    -------
    e: float
        Eccentricity calculated solely on g and w

    """
    num = np.sqrt(2)*np.sqrt(2*g**4-g**2*np.cos(2*w)-g**2-2*np.sin(w))
    den = 2*(g**2+np.sin(w)**2)
    e = num/den
    return e

def planetlc_fitter(time, per, rp, a, inc, w):
    """Always assumes e=0.
    w is a free parameter."""

    params = batman.TransitParams()       #object to store transit parameters
    params.t0 = 0.                        #time of inferior conjunction
    params.per = per                      #orbital period
    params.rp = rp                        #planet radius (in units of stellar radii)
    params.a = a                          #semi-major axis (in units of stellar radii)
    params.inc = inc                      #orbital inclination (in degrees)
    params.ecc = 0.0                      #eccentricity
    params.w = w                        #longitude of periastron (in degrees)
    #params.limb_dark = "linear"
    #params.u = [0.3]
    #params.limb_dark = "quadratic"
    #params.u = [0.1, 0.3]
    params.limb_dark = "uniform"
    params.u = []

    #times to calculate light curve
    m = batman.TransitModel(params, time)

    flux = m.light_curve(params)

    return flux


def log_likelihood(theta, g, gerr):
    """Log of likelihood
    model = g(e,w)
    gerr = sigma of g distribution
    """
    w, e = theta
    model = (1+e*np.sin(w*(np.pi/180.)))/np.sqrt(1-e**2)
    sigma2 = gerr ** 2
    return -0.5 * np.sum((g - model) ** 2 / sigma2 + np.log(sigma2))

def log_prior(theta):
    """Log of prior
    e between 0 and 1
    w between -90 and 300
    """
    w, e = theta
    if 0.0 < e < 1.0 and -90.0 < w < 300.0:
        return 0.0
    return -np.inf

def log_probability(theta, g, gerr):
    """Log of probability
    """
    lp = log_prior(theta)
    if not np.isfinite(lp):
        return -np.inf
    return lp + log_likelihood(theta, g, gerr)

    

def tfit_log_likelihood(theta, time, flux, flux_err):
    """
    Transit fit emcee function

    model = ph.planetlc_fitter()
    gerr = sigma of g distribution

    """
    per, rp, a, inc = theta
    model = planetlc_fitter(time, per, rp, a, inc, 0.0)
    sigma2 = flux_err ** 2
    return -0.5 * np.sum((flux - model) ** 2 / sigma2 + np.log(sigma2))



def tfit_log_prior(theta):
    """
    Transit fit emcee function

    e must be between 0 and 1
    w must be between -90 and 300

    """
    per, rp, a, inc = theta
    if 0.0 < rp < 1.0 and 0.0 < inc < 90.0:
        return 0.0
    return -np.inf

def tfit_log_probability(theta, time, flux, flux_err):
    """
    Transit fit emcee function
    """
    lp = tfit_log_prior(theta)
    if not np.isfinite(lp):
        return -np.inf
    return lp + tfit_log_likelihood(theta, time, flux, flux_err)





def mcmc_fitter(guess_transit, time, nflux, flux_err, nwalk, nsteps, ndiscard, e, w, directory, plot_Tburnin=True, plot_Tcorner=True):
    """One-step MCMC transit fitting with `photoeccentric`.

    NB: (nsteps-ndiscard)*nwalkers must equal the length of rho_star.

    Parameters
    ----------
    guess_transit: np.array
        Initial guess: [period (days), Rp/Rs, a/Rs, i (deg)]
    time: np.array
        Time axis of light curve to fit
    nflux: np.array
        Flux of light curve to fit
    flux_err: np.array
        Flux errors of light curve to fit
    nwalkers: int
        Number of `emcee` walkers
    nsteps: int
        Number of `emcee` steps to run
    ndiscard: int
        Number of `emcee` steps to discard (after burn-in)
    e: float
        True eccentricity (just to name directory)
    w: float
        True longitude of periastron (just to name directory)
    directory: str
        Full directory path to save plots
    plot_Tburnin: boolean, default True
        Plot burn-in and save to directory
    plot_Tcorner: boolean, default True
        Plot corner plot and save to directory

    Returns
    -------
    results: list
        Fit results [period, Rp/Rs, a/Rs, i]
    results_errs: list
        Fit results errors [period err, Rp/Rs err, a/Rs err, i err]
    per_dist: np.array
        MCMC period distribution
    rprs_dist: np.array
        MCMC Rp/Rs distribution
    ars_dist: np.array
        MCMC a/Rs distribution
    i_dist: np.array
        MCMC i distribution

    """

    solnx = (guess_transit[0], guess_transit[1], guess_transit[2], guess_transit[3])
    pos = solnx + 1e-4 * np.random.randn(nwalk, 4)
    nwalkers, ndim = pos.shape

    sampler = emcee.EnsembleSampler(nwalkers, ndim, tfit_log_probability, args=(time, nflux, flux_err), threads=4)
    sampler.run_mcmc(pos, nsteps, progress=True);
    samples = sampler.get_chain()

    if plot_Tburnin==True:
        fig, axes = plt.subplots(4, figsize=(10, 7), sharex=True)
        labels = ["period", "rprs", "a/Rs", "i"]
        for i in range(ndim):
            ax = axes[i]
            ax.plot(samples[:, :, i], "k", alpha=0.3)
            ax.set_xlim(0, len(samples))
            ax.set_ylabel(labels[i])
            ax.yaxis.set_label_coords(-0.1, 0.5)

        axes[-1].set_xlabel("step number");
        fig.savefig(directory + 'lcfit_burnin.png')
        plt.close(fig)

    flat_samples = sampler.get_chain(discard=ndiscard, thin=1, flat=True)

    if plot_Tcorner==True:
        fig = corner.corner(flat_samples, labels=labels);
        fig.savefig(directory + 'transit_corner.png')
        plt.close(fig)

    results = []
    results_errs = []

    for i in range(ndim):
        results.append(np.percentile(flat_samples[:,i], 50))
        results_errs.append(np.mean((np.percentile(flat_samples[:,i], 16), np.percentile(flat_samples[:,i], 84))))

    per_dist = flat_samples[:,0]
    rprs_dist = flat_samples[:,1]
    ars_dist = flat_samples[:,2]
    i_dist = flat_samples[:,3]

    return results, results_errs, per_dist, rprs_dist, ars_dist, i_dist
