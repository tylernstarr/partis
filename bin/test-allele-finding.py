#!/usr/bin/env python
import numpy
import copy
import random
import argparse
import time
import sys
import os
import glob

from subprocess import check_call
sys.path.insert(1, './python')
partis_dir = os.path.dirname(os.path.realpath(__file__)).replace('/bin', '')

import utils
import glutils

# ----------------------------------------------------------------------------------------
def get_outfname(args, method):
    if method == 'partis' or method == 'full':  # parameter directory, not regular file (although, could change it to the gls .fa in sw/)
        return args.outdir + '/' + method
    else:
        return args.outdir + '/' + method + '/' + args.locus + '/' + args.locus + 'v' + '.fasta'

# ----------------------------------------------------------------------------------------
def simulate(args):
    if utils.output_exists(args, args.simfname):
        return
    cmd_str = args.partis_path + ' simulate --n-sim-events ' + str(args.n_sim_events) + ' --n-leaves ' + str(args.n_leaves) + ' --rearrange-from-scratch --outfname ' + args.simfname
    if args.n_leaf_distribution is None:
        cmd_str += ' --constant-number-of-leaves'
    else:
        cmd_str += ' --n-leaf-distribution ' + args.n_leaf_distribution
    if args.mut_mult is not None:
        cmd_str += ' --mutation-multiplier ' + str(args.mut_mult)

    cmd_str += ' --n-procs ' + str(args.n_procs)
    if args.slurm:
        cmd_str += ' --batch-system slurm --subsimproc'

    allele_prevalence_fname = args.workdir + '/allele-prevalence-freqs.csv'

    # figure what genes we're using
    if args.gls_gen:
        assert args.sim_v_genes is None and args.allele_prevalence_freqs is None

        n_genes_per_region = '20:5:3'
        n_sim_alleles_per_gene = '1,2:1,2:1,2'  # NOTE default is also in bin/partis
        min_allele_prevalence_freq = 0.1
        remove_template_genes = False

        sglfo = glutils.read_glfo('data/germlines/human', locus=args.locus)
        glutils.remove_v_genes_with_bad_cysteines(sglfo)
        glutils.generate_germline_set(sglfo, n_genes_per_region, n_sim_alleles_per_gene, min_allele_prevalence_freq, allele_prevalence_fname, snp_positions=args.snp_positions, remove_template_genes=remove_template_genes)
        cmd_str += ' --allele-prevalence-fname ' + allele_prevalence_fname
    else:
        sglfo = glutils.read_glfo('data/germlines/human', locus=args.locus, only_genes=(args.sim_v_genes + args.dj_genes))
        added_snp_names = None
        if args.snp_positions is not None:  # not necessarily explicitly set on the command line, i.e. can also be filled based on --nsnp-list
            snps_to_add = [{'gene' : args.sim_v_genes[ig], 'positions' : args.snp_positions[ig]} for ig in range(len(args.snp_positions))]
            added_snp_names = glutils.add_some_snps(snps_to_add, sglfo, debug=True, remove_template_genes=args.remove_template_genes)

        if args.allele_prevalence_freqs is not None:
            if not utils.is_normed(args.allele_prevalence_freqs):
                raise Exception('--allele-prevalence-freqs %s not normalized' % args.allele_prevalence_freqs)

            if len(args.allele_prevalence_freqs) != len(sglfo['seqs']['v']):  # already checked when parsing args, but, you know...
                raise Exception('--allele-prevalence-freqs not the right length')
            gene_list = sorted(sglfo['seqs']['v']) if added_snp_names is None else list(set(args.sim_v_genes)) + added_snp_names
            prevalence_freqs = {'v' : {g : f for g, f in zip(gene_list, args.allele_prevalence_freqs)}, 'd' : {}, 'j' : {}}
            glutils.write_allele_prevalence_freqs(prevalence_freqs, allele_prevalence_fname)
            cmd_str += ' --allele-prevalence-fname ' + allele_prevalence_fname

    print '  simulating with %d v: %s' % (len(sglfo['seqs']['v']), ' '.join([utils.color_gene(g) for g in sglfo['seqs']['v']]))
    glutils.write_glfo(args.outdir + '/germlines/simulation', sglfo)
    cmd_str += ' --initial-germline-dir ' + args.outdir + '/germlines/simulation'

    # run simulation
    if args.seed is not None:
        cmd_str += ' --seed ' + str(args.seed)
    utils.simplerun(cmd_str)

# ----------------------------------------------------------------------------------------
def run_other_method(args, method):
    if utils.output_exists(args, get_outfname(args, method)):
        return
    simfasta = utils.getprefix(args.simfname) + '.fa'
    utils.csv_to_fasta(args.simfname, outfname=simfasta, overwrite=False)
    cmd = './test/%s-run.py' % method
    cmd += ' --infname ' + simfasta
    cmd += ' --outfname ' + get_outfname(args, method)
    if args.gls_gen:
        cmd += ' --gls-gen'
        cmd += ' --glfo-dir ' + partis_dir + '/data/germlines/human'  # the partis mehods have this as the default internally, but we want/have to set it explicitly here
    else:
        cmd += ' --glfo-dir ' + args.inf_glfo_dir
    if method != 'igdiscover':  # for now we're saving all the igdiscover output/intermediate files, so we write them to an output dir
        cmd += ' --workdir ' + args.workdir + '/' + method
    cmd += ' --n-procs ' + str(args.n_procs)

    utils.simplerun(cmd)

# ----------------------------------------------------------------------------------------
def run_partis(args, method):
    if utils.output_exists(args, get_outfname(args, method)):
        return

    paramdir = get_outfname(args, method)
    plotdir = args.outdir + '/' + method + '/plots'

    # remove any old sw cache files
    sw_cachefiles = glob.glob(paramdir + '/sw-cache-*.csv')
    if len(sw_cachefiles) > 0:
        for cachefname in sw_cachefiles:
            check_call(['rm', '-v', cachefname])
            sw_cache_gldir = cachefname.replace('.csv', '-glfo')
            if os.path.exists(sw_cache_gldir):  # if stuff fails halfway through, you can get one but not the other
                glutils.remove_glfo_files(sw_cache_gldir, args.locus)
                # os.rmdir(sw_cache_gldir)

    # generate germline set and cache parameters
    cmd_str = args.partis_path + ' cache-parameters --infname ' + args.simfname + ' --only-smith-waterman'
    if method == 'partis':
        cmd_str += ' --find-new-alleles --debug-allele-finding' # --always-find-new-alleles'
    elif method == 'full':
        cmd_str += ' --dont-remove-unlikely-alleles'
    else:
        assert False

    cmd_str += ' --n-procs ' + str(args.n_procs)
    if args.n_max_queries is not None:
        cmd_str += ' --n-max-queries ' + str(args.n_max_queries)  # NOTE do *not* use --n-random-queries, since it'll change the cluster size distribution
    if args.slurm:
        cmd_str += ' --batch-system slurm'

    if not args.gls_gen:  # otherwise it uses the default (full) germline dir
        cmd_str += ' --dont-remove-unlikely-alleles --initial-germline-dir ' + args.inf_glfo_dir

    cmd_str += ' --parameter-dir ' + paramdir
    cmd_str += ' --only-overall-plots --plotdir ' + plotdir
    if args.seed is not None:
        cmd_str += ' --seed ' + str(args.seed)
    if args.plot_and_fit_absolutely_everything is not None:
        cmd_str += ' --plot-and-fit-absolutely-everything ' + str(args.plot_and_fit_absolutely_everything)
    utils.simplerun(cmd_str)

# ----------------------------------------------------------------------------------------
def write_inf_glfo(args):  # read default glfo, restrict it to the specified alleles, and write to somewhere where all the methods can read it
    # NOTE this dir should *not* be modified by any of the methods
    inf_glfo = glutils.read_glfo('data/germlines/human', locus=args.locus, only_genes=args.inf_v_genes + args.dj_genes)
    print '  writing initial inference glfo with %d v: %s' % (len(inf_glfo['seqs']['v']), ' '.join([utils.color_gene(g) for g in inf_glfo['seqs']['v']]))
    glutils.write_glfo(args.inf_glfo_dir, inf_glfo)

# ----------------------------------------------------------------------------------------
def run_tests(args):
    print 'seed %d' % args.seed

    if not args.nosim:
        simulate(args)

    if not args.gls_gen:
        write_inf_glfo(args)
    for method in args.methods:
        if method == 'partis' or method == 'full':
            run_partis(args, method)
        else:
            run_other_method(args, method)

# ----------------------------------------------------------------------------------------
def multiple_tests(args):
    def getlogdir(iproc):
        return args.outdir + '/' + str(iproc) + '/logs/' + '-'.join(args.methods)
    def cmd_str(iproc):
        clist = copy.deepcopy(sys.argv)
        utils.remove_from_arglist(clist, '--n-tests', has_arg=True)
        utils.replace_in_arglist(clist, '--outdir', args.outdir + '/' + str(iproc))
        utils.replace_in_arglist(clist, '--seed', str(args.seed + iproc))
        # clist.append('--slurm')
        return ' '.join(clist)

    for iproc in range(args.iteststart, args.n_tests):  # don't overwrite old log files... need to eventually fix this so it isn't necessary
        def lfn(iproc, ilog):
            logfname =  args.outdir + '/' + str(iproc) + '/log'
            if ilog > 0:
                logfname += '.' + str(ilog)
            return logfname

    for iproc in range(args.iteststart, args.n_tests):
        logd = getlogdir(iproc)
        if os.path.exists(logd + '/log'):
            ilog = 0
            while os.path.exists(logd + '/log.' + str(ilog)):
                ilog += 1
            check_call(['mv', '-v', logd + '/log', logd + '/log.' + str(ilog)])
    cmdfos = [{'cmd_str' : cmd_str(iproc),
               'workdir' : args.workdir + '/' + str(iproc),
               'logdir' : getlogdir(iproc),
               'outfname' : args.outdir + '/' + str(iproc)}
              for iproc in range(args.iteststart, args.n_tests)]
    print '  look for logs in %s' % args.outdir
    utils.run_cmds(cmdfos, debug='write')

# ----------------------------------------------------------------------------------------

# # ----------------------------------------------------------------------------------------
# from hist import Hist
# import plotting
# fig, ax = plotting.mpl_init()

# ntrees = 1000
# distrs = [
#     # (1.5, 'geo'),
#     # (3, 'geo'),
#     (10, 'geo'),
#     # (25, 'geo'),
#     # (2.3, 'zipf'),
#     # (1.8, 'zipf'),
#     # (1.3, 'zipf'),
# ]

# # ----------------------------------------------------------------------------------------
# def getsubsample(vals):
#     print vals
#     iclust = 0
#     seqs = []
#     for v in vals:
#         seqs += [iclust for _ in range(v)]
#         iclust += 1
#     print seqs
#     subseqs = numpy.random.choice(seqs, size=ntrees)
#     # subseqs = seqs[:ntrees]
#     print subseqs
#     import itertools
#     subvals = []
#     for _, group in itertools.groupby(sorted(subseqs)):
#         for what in set(group):
#             subg = [s for s in subseqs if s == what]
#             print what, len(subg)
#             subvals.append(len(subg))
#     print subvals
#     return subvals

# ih = 0
# for n_leaves, fcn in distrs:
#     if fcn == 'zipf':
#         vals = numpy.random.zipf(n_leaves, size=ntrees)  # NOTE <n_leaves> is not the mean here
#     elif fcn == 'geo':
#         vals = numpy.random.geometric(1. / n_leaves, size=ntrees)
#     else:
#         assert False
#     nbins = 100
#     htmp = Hist(nbins, -0.5, nbins - 0.5)
#     for v in vals:
#         htmp.fill(v)
#     htmp.mpl_plot(ax, color=plotting.default_colors[ih], errors=False, label='%s %.1f' % (fcn, numpy.mean(vals)))
# # ----------------------------------------------------------------------------------------
#     hsub = Hist(nbins, -0.5, nbins - 0.5)
#     subvals = getsubsample(vals)
#     for v in subvals:
#         hsub.fill(v)
#     hsub.mpl_plot(ax, color=plotting.default_colors[ih], errors=False, label='%s %.1f' % (fcn, numpy.mean(subvals)), linestyle='--')
# # ----------------------------------------------------------------------------------------
#     ih += 1

# plotting.mpl_finish(ax, utils.fsdir() + '/partis/tmp/tmp', 'baz', xbounds=(0.9, nbins), log='y')
# sys.exit()
# # ----------------------------------------------------------------------------------------

example_str = '\n    '.join(['example usage:',
                             './bin/test-allele-finding.py --n-sim-events 2000 --n-procs 10 --sim-v-genes=IGHV1-18*01 --inf-v-genes=IGHV1-18*01 --snp-positions 27,55,88',
                             './bin/test-allele-finding.py --n-sim-events 2000 --n-procs 10 --sim-v-genes=IGHV4-39*01:IGHV4-39*02 --inf-v-genes=IGHV4-39*01'])
parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, epilog=example_str)
parser.add_argument('--nosim', action='store_true', help='run inference on (presumably) existing simulation')
parser.add_argument('--n-sim-events', type=int, default=20, help='number of simulated rearrangement events')
parser.add_argument('--n-max-queries', type=int, help='number of queries to use for inference from the simulation sample')
parser.add_argument('--n-leaves', type=float, default=1.)
parser.add_argument('--n-leaf-distribution')
parser.add_argument('--n-procs', type=int, default=2)
parser.add_argument('--seed', type=int, default=int(time.time()))
parser.add_argument('--gls-gen', action='store_true', help='generate a random germline set from scratch (parameters specified above), and infer a germline set from scratch, instead of using --sim-v-genes, --dj-genes, --inf-v-genes, and --snp-positions.')
parser.add_argument('--sim-v-genes', default='IGHV4-39*01:IGHV4-39*06', help='.')
parser.add_argument('--inf-v-genes', default='IGHV4-39*01', help='.')
parser.add_argument('--dj-genes', default='IGHD6-19*01:IGHJ4*02', help='.')
parser.add_argument('--snp-positions', help='colon-separated list (length must equal length of <--sim-v-genes>) of comma-separated snp positions for each gene, e.g. for two genes you might have \'3,71:45\'')
parser.add_argument('--nsnp-list', help='colon-separated list (length must equal length of <--sim-v-genes> unless --gls-gen) of the number of snps to generate for each gene (each snp at a random position). If --gls-gen, then this still gives the number of snpd genes, but it isn\'t assumed to be the same length as anything [i.e. we don\'t yet know how many v genes there\'ll be]')
parser.add_argument('--allele-prevalence-freqs', help='colon-separated list of allele prevalence frequencies, including newly-generated snpd genes (ordered alphabetically)')
parser.add_argument('--remove-template-genes', action='store_true', help='when generating snps, remove the original gene before simulation')
parser.add_argument('--mut-mult', type=float)
parser.add_argument('--slurm', action='store_true')
parser.add_argument('--overwrite', action='store_true')
parser.add_argument('--methods', default='partis')
parser.add_argument('--outdir', default=utils.fsdir() + '/partis/allele-finder')
parser.add_argument('--inf-glfo-dir', help='default set below')
parser.add_argument('--simfname', help='default set below')
parser.add_argument('--workdir', default=utils.fsdir() + '/_tmp/hmms/' + str(random.randint(0, 999999)))
parser.add_argument('--n-tests', type=int)
parser.add_argument('--iteststart', type=int, default=0)
parser.add_argument('--plot-and-fit-absolutely-everything', type=int, help='fit every single position for this <istart> and write every single corresponding plot (slow as hell, and only for debugging/making plots for paper)')
parser.add_argument('--partis-path', default='./bin/partis')
parser.add_argument('--locus', default='igh')

args = parser.parse_args()
args.dj_genes = utils.get_arg_list(args.dj_genes)
args.sim_v_genes = utils.get_arg_list(args.sim_v_genes)
args.inf_v_genes = utils.get_arg_list(args.inf_v_genes)
args.snp_positions = utils.get_arg_list(args.snp_positions)
args.nsnp_list = utils.get_arg_list(args.nsnp_list, intify=True)
args.allele_prevalence_freqs = utils.get_arg_list(args.allele_prevalence_freqs, floatify=True)
args.methods = utils.get_arg_list(args.methods)
if args.snp_positions is not None:
    args.snp_positions = [[int(p) for p in pos_str.split(',')] for pos_str in args.snp_positions]
    if len(args.snp_positions) != len(args.sim_v_genes):
        raise Exception('--snp-positions %s and --sim-v-genes %s not the same length (%d vs %d)' % (args.snp_positions, args.sim_v_genes, len(args.snp_positions), len(args.sim_v_genes)))
if args.nsnp_list is not None:
    if not args.gls_gen and len(args.nsnp_list) != len(args.sim_v_genes):
        raise Exception('--nsnp-list %s and --sim-v-genes %s not the same length (%d vs %d)' % (args.nsnp_list, args.sim_v_genes, len(args.nsnp_list), len(args.sim_v_genes)))
    if args.snp_positions is not None:
        raise Exception('can\'t specify both --nsnp-list and --snp-positions')
    args.snp_positions = [[None for _ in range(nsnp)] for nsnp in args.nsnp_list]  # the <None> tells glutils to choose a position at random
    args.nsnp_list = None
if args.allele_prevalence_freqs is not None:
    # easier to check the length after we've generated snpd genes (above)
    if not utils.is_normed(args.allele_prevalence_freqs):
        raise Exception('--allele-prevalence-freqs %s not normalized' % args.allele_prevalence_freqs)
if args.inf_glfo_dir is None:
    args.inf_glfo_dir = args.outdir + '/germlines/inference'
if args.simfname is None:
    args.simfname = args.outdir + '/simu.csv'

# if we're generating/inferring a whole germline set these are either set automatically or not used
if args.gls_gen:
    args.sim_v_genes = None
    args.inf_v_genes = None
    args.dj_genes = None
    args.allele_prevalence_freqs = None
    args.inf_glfo_dir = None

if args.seed is not None:
    random.seed(args.seed)
    numpy.random.seed(args.seed)

if args.n_tests is not None:
    multiple_tests(args)
else:
    run_tests(args)
