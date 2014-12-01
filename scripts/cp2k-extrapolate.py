#!/usr/bin/env python
from __future__ import division
import numpy as np
import scipy.special as scsp
import argparse
import asetk.format.cp2k as cp2k
import asetk.format.cube as cube
import asetk.atomistic.constants as constants
import asetk.util.progressbar as progressbar
import os.path

# Define command line parser
parser = argparse.ArgumentParser(
    description='Performs wave function extrapolation for \
                 Scanning Tunneling Microscopy Simulation.')
parser.add_argument('--version', action='version', version='%(prog)s 30.12.2014')
parser.add_argument(
    'cubes',
    nargs='+',
    metavar='WILDCARD',
    help='Gaussian cube files containing the Kohn-Sham orbitals psi_i. \
            Note: |psi_i|^2 cannot be extrapolated!')
parser.add_argument(
    '--hartree',
    metavar='FILENAME',
    required=True,
    help='Gaussian cube file containing Hartree potential from CP2K.')
parser.add_argument(
    '--levelsfile',
    metavar='FILENAME',
    required=True,
    help='File containing the energy levels. Can be either CP2K output\
          or .MOLog file.')
parser.add_argument(
    '--mode',
    metavar='KEYWORD',
    default='plane',
    help='Currently only "plane" is implemented.')
parser.add_argument(
    '--height',
    metavar='DISTANCE',
    default=+5.0,
    type=float,
    help='Distance between extrapolation plane and outermost atom in a.u.')
parser.add_argument(
    '--extent',
    metavar='DISTANCE',
    default=+15.0,
    type=float,
    help='Extent of extrapolation in a.u.')

args = parser.parse_args()
a02A = constants.a0 / constants.Angstrom  # Bohr radius in Angstroms
eV2Ha = constants.eV / constants.Ha       # convert eV to Ha

lfname, lfext = os.path.splitext(args.levelsfile)
if lfext == '.MOLog':
    spectrum = cp2k.Spectrum.from_mo(args.levelsfile)
else:
    spectrum = cp2k.Spectrum.from_output(args.levelsfile)


print("Read spectrum from {f}".format(f=args.levelsfile))
print(spectrum)

# Reading Hartree potential

# Reading cube files is the most time consuming part of the routine.
# Since we need only one plane from the Hartree potential,
# we save it to disk for reuse.
print("Reading Hartree potential from {}".format(args.hartree))
hartree_planefile = "{}.z{:.2f}".format(args.hartree,args.height)

hartree_plane = None
if( os.path.isfile(hartree_planefile) ):
    hartree_plane = np.genfromtxt(hartree_planefile)
else:
    hartree_cube = cube.Cube.from_file(args.hartree, read_data=True)
    hartree_plane = hartree_cube.get_plane_above_atoms( \
            args.height*a02A, verbose=True)
    np.savetxt(hartree_planefile, hartree_plane)

hartree_avg = np.mean(hartree_plane) / eV2Ha
hartree_min = np.min(hartree_plane) / eV2Ha
hartree_max = np.max(hartree_plane) / eV2Ha
print("Hartree potential on extrapolation surface:")
print("   min {:+.4f} eV, max {:+4f} eV, avg {:+.4f} eV" \
        .format(hartree_min, hartree_max, hartree_avg))
if hartree_max - hartree_min > 1.0:
    print("Warning: min and max differ by more than 1 eV!")
    print("Assumption of constant Hartree potential is violated.")
print("")

#bar = progressbar.ProgressBar(niter=len(args.cubes))
#
#for fname in args.cubes:
#    cubes.append( cp2k.WfnCube.from_file(fname) )
#    bar.iterate()
#print("")

# Extrapolating cube files
print("Extrapolating {} cube files".format(len(args.cubes)))
for fname in args.cubes:
    print("------------")
    print("Reading {}".format(fname))
    cube = cp2k.WfnCube.from_file(fname, read_data=True)

    try:
        cube.energy = spectrum.energylevels[cube.spin-1].levels[cube.wfn-1].energy
    except:
        print("Error: Missing energy level for cube file {}.")
        print("       Did you use the correct levels file?".format(fname))
    print("Spin {}, n = {}, E = {:.4f} eV"\
            .format(cube.spin, cube.wfn, cube.energy))

    plane = cube.get_plane_above_atoms(args.height*a02A)

    E = (cube.energy - hartree_avg) * eV2Ha * np.dot(cube.dz, cube.dz) / a02A**2
    dKX = 2*np.pi*np.linalg.norm(cube.dz) / np.linalg.norm(cube.cell[0])
    dKY = 2*np.pi*np.linalg.norm(cube.dz) / np.linalg.norm(cube.cell[1])

    fourier = np.fft.rfft2(plane)
    nKX, nKY = fourier.shape

    # Prepare matrix with prefactors that propagates Fourier components
    # to next z-plane
    #print("Calculating prefactors")
    p = lambda i,j: np.exp( -np.sqrt( (i*dKX)**2 + (j*dKY)**2 - 2*E) )
    prefactors = np.zeros(fourier.shape)
    for i in range(nKX):
        for j in range(nKY):
            # rfft2 storage order in 1st dimension is 
            #   0..G -(G-1)..-1 for even nKX
            #   0..G -G..-1 for odd nKX
            # Note: Could use np.fft.rfftfreq instead of hand-made formula
            i_mod = i - (i//(nKX//2+1)) * nKX
            prefactors[i,j] = p(i_mod, j)

    iz_start = cube.get_index_above_atoms(args.height*a02A)
    iz_end = cube.get_index_above_atoms((args.height+args.extent)*a02A)
    print("Extrapolation surface at z-index {}".format(iz_end+1))
    cube.resize([ cube.shape[0], cube.shape[1], iz_end + 1])

    for iz in range(iz_start+1, iz_end+1):
        fourier *= prefactors
        cube.set_plane('z', iz, np.fft.irfft2(fourier, plane.shape))
        #print(np.mean(np.abs(tmp)))

    fname_out = 'extrapolated2.' + fname
    print("Writing {}".format(fname_out))
    cube.write_cube_file(fname_out)


# Extrapolating cube files
print("")
print("Job done.")
    
