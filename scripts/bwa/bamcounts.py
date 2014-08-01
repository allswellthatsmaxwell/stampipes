#!/usr/bin/env python

import os, sys, logging, re
from pysam import Samfile
from optparse import OptionParser

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

usage = """usage:
%prog BAMFILE COUNTFILE [OPTIONS]"""

script_options = {
  "debug": False,
  "quiet": True,
}

def parser_setup():

    parser = OptionParser(usage=usage)

    parser.add_option("-q", "--quiet", dest="quiet", action="store_true", 
        help="Don't print info messages to standard out.")
    parser.add_option("-d", "--debug", dest="debug", action="store_true", 
        help="Print all debug messages to standard out.")

    parser.set_defaults( **script_options )
    parser.set_defaults( quiet=False, debug=False )

    return parser

class BAMFilter(object):

    def __init__(self):

        self.max_mismatches = 2
        self.previous_read = None
        self.min_map_quality = 30

    def process_read(self, read, counts, chrcounts, inbam):

        # change this to false if we run into a condition that excludes this read
        output = True

        if self.min_map_quality > read.mapq:
            return

        if not read.tags:
            return

        tags = dict(read.tags)
        
        if read.flag & 12:
            return False

        if read.is_unmapped:
            counts['nm'] += 1
            return False
            
        counts['u'] += 1
        
        if read.is_qcfail:
            return False
        
        counts['u-pf'] += 1
        
        if "N" in read.seq:
            return False
        else:
            counts['u-pf-n'] += 1
        
        ## 8 = mismatch, sums up all mismatch bases
        #mismatches = sum([mismatch[1] for mismatch in read.cigar if mismatch[0] == 8])
        #
        #if mismatches > self.max_mismatches:
        #    return False
        #else:
        #    counts['u-pf-n-mm%d' % self.max_mismatches] += 1
        
        if tags['NM'] > self.max_mismatches:
            return False
        else:
            counts['u-pf-n-mm%d' % self.max_mismatches] += 1
        
        chr = inbam.getrname(read.rname)
        
        if not chr in chrcounts:
            chrcounts[chr] = 1
        else:
            chrcounts[chr] += 1 
        
        if not "chrM" == chr:
            counts['u-pf-n-mm%d-mito' % self.max_mismatches] += 1
        
        self.previous_read = read

        return output

    def filter(self, infile, countfile):

        inbam = Samfile(infile, 'rb')
        #outbam = Samfile(outfile, 'wb', template=inbam)
        
        count_labels = ['u', 'u-pf', 'u-pf-n', 'u-pf-n-mm%d' % self.max_mismatches,
          'u-pf-n-mm%d-mito' % self.max_mismatches, ] #'qc', 'mm', 'nm', 'pf', 'total']
        
        counts = dict([(label, 0) for label in count_labels])

        chrcounts = {}

        for read in inbam:
            self.process_read(read, counts, chrcounts, inbam)
            #if output:
            #    outbam.write(read)
        
        countout = open(countfile, 'w')
        
        # checks
        
        #if counts['pf'] + counts['qc'] != counts['total']:
        #    print "WARNING: pf + qc != total"
        #
        #if counts['mm'] + counts['nm'] + counts['u'] != counts['total']:
        #    print "WARNING: mm + nm + u != total"
        #
        #if sum(chrcounts.values()) != counts['u-pf-n-mm%d' % self.max_mismatches]:
        #    print "WARNING: chromosome counts != u-pf-n-mm%d" % self.max_mismatches
        
        for count in count_labels:
            countout.write("%s\t%d\n" % (count, counts[count]))
        
        for count in sorted(chrcounts.keys()):
            countout.write("%s\t%d\n" % (count, chrcounts[count]))
        
        countout.close()
        
def main(args = sys.argv):
    """This is the main body of the program that by default uses the arguments
from the command line."""
    
    parser = parser_setup()
    (poptions, pargs) = parser.parse_args()
    
    if poptions.quiet:
        logging.basicConfig(level=logging.WARNING, format=log_format)
    elif poptions.debug:
        logging.basicConfig(level=logging.DEBUG, format=log_format)    
    else:
        # Set up the logging levels
        logging.basicConfig(level=logging.INFO, format=log_format)

    bamfile = pargs[0]
    # outfile = pargs[1]
    countfile = pargs[1]
    
    filter = BAMFilter()
    
    filter.filter(bamfile, countfile)
    
# This is the main body of the program that only runs when running this script
# doesn't run when imported, so you can use the functions above in the shell after importing
# without automatically running it
if __name__ == "__main__":
    main()