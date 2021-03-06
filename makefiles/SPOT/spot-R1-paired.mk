###################
# This only samples from R1.  Duplicates are calculated from paired data.
# These variables must be passed in or set for the makefile to work.  If the genome's
# FAI file is not at $(BWAINDEX).fai, then it must also be specified under FAI.
###################
# SAMPLE_NAME=Example_NoIndex_L007
# BWAINDEX=/path/to/genome/hg19/hg19
# GENOME=hg19
# READLENGTH=36
# ASSAY=DNaseI
###################
# REQUIRED MODULES
###################
# module load java
# module load samtools
# module load python
# module load bedops
# module load bedtools
###################

FAI ?= $(BWAINDEX).fai
SAMPLE_SIZE ?= 5000000 # paired end reads

INDIR ?= $(shell pwd)

BAMFILE ?= $(INDIR)/$(SAMPLE_NAME).uniques.sorted.bam
STAMPIPES ?= ~/stampipes
HOTSPOT_DIR ?= ~/hotspot/hotspot-distr

OUTDIR ?= $(shell pwd)
TMPDIR ?= $(OUTDIR)

SPOTDIR ?= $(TMPDIR)/$(SAMPLE_NAME)_spot_R1

all : calcdup calcspot

SPOT_OUT ?= $(OUTDIR)/$(SAMPLE_NAME).R1.rand.uniques.sorted.spot.out
DUP_OUT ?= $(OUTDIR)/$(SAMPLE_NAME).rand.uniques.sorted.spotdups.txt

RANDOM_SAMPLE_BAM ?= $(TMPDIR)/$(SAMPLE_NAME).rand.uniques.sorted.bam
RANDOM_SAMPLE_BAM_R1 ?= $(TMPDIR)/$(SAMPLE_NAME).R1.rand.uniques.sorted.bam

calcspot : $(SPOT_OUT)
calcdup : $(DUP_OUT)

$(RANDOM_SAMPLE_BAM) : $(BAMFILE)
	samtools view -F 12 -f 3 $^ | awk '{if($$3 != "chrM" && $$3 != "chrC" && $$3 != "random"){print}}' | sort -k 1,1 | awk -f $(STAMPIPES)/awk/matchreadpairs.awk > $(TMPDIR)/linematch.sam
	bash -e $(STAMPIPES)/scripts/SPOT/pairedrandomsample.bash $(SAMPLE_SIZE) $(FAI) $(TMPDIR)/linematch.sam $(TMPDIR)/randsample.bam
	samtools sort $(TMPDIR)/randsample.bam $(basename $@)

# Only use Read 1 from our sample for SPOT score
$(RANDOM_SAMPLE_BAM_R1) : $(RANDOM_SAMPLE_BAM)
	samtools view -f 0x0040 $^ | samtools view -bSt $(FAI) - > $@

$(SPOT_OUT) : $(SPOTDIR)/$(SAMPLE_NAME).R1.rand.uniques.sorted.spot.out
	cp $(SPOTDIR)/$(SAMPLE_NAME).R1.rand.uniques.sorted.spot.out $(SPOT_OUT)

# run the SPOT program
$(SPOTDIR)/$(SAMPLE_NAME).R1.rand.uniques.sorted.spot.out : $(RANDOM_SAMPLE_BAM_R1)
	bash -e $(STAMPIPES)/scripts/SPOT/runhotspot.bash $(HOTSPOT_DIR) $(SPOTDIR) $(RANDOM_SAMPLE_BAM_R1) $(GENOME) $(READLENGTH) $(ASSAY)

# Calculate the duplication score of the random sample
$(DUP_OUT) : $(RANDOM_SAMPLE_BAM)
	java -jar `which MarkDuplicates.jar` INPUT=$(RANDOM_SAMPLE_BAM) OUTPUT=$(TMPDIR)/$(SAMPLE_NAME).R1.rand.uniques.dup \
	  METRICS_FILE=$(OUTDIR)/$(SAMPLE_NAME).R1.rand.uniques.sorted.spotdups.txt ASSUME_SORTED=true VALIDATION_STRINGENCY=SILENT
