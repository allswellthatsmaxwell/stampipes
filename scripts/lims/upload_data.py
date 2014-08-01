import os, sys, logging, re
import requests
import json
import fileinput
import argparse

token = None
headers = None
lane_tags = None
flowcell_lane_cache = dict()
flowcell_contenttype = None
base_api_url = None

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

script_options = {
    "base_api_url": "https://lims.stamlab.org/api",
    "basedir": os.getcwd(),
    "quiet": False,
    "debug": False,
    "alignment_id": None,
    "fastqc_files": [],
    "spot_file": None,
    "dup_file": None,
    "counts_file": None,
    "flowcell": None,
    "flowcell_lane_id": None,
}

def parser_setup():

    parser = argparse.ArgumentParser()

    parser.add_argument("-q", "--quiet", dest="quiet", action="store_true",
        help="Don't print info messages to standard out.")
    parser.add_argument("-d", "--debug", dest="debug", action="store_true",
        help="Print all debug messages to standard out.")

    parser.add_argument("-a", "--api", dest="base_api_url",
        help="The base API url, if not the default live LIMS.")

    parser.add_argument("-t", "--token", dest="token",
        help="Your authentication token.  Required.")
    parser.add_argument("-f", "--flowcell", dest="flowcell",
        help="The flowcell we're working on.  Enter it to clear cache after uploading.")

    # these should go together
    parser.add_argument("--alignment_id", dest="alignment_id", type=int)
    parser.add_argument("--spotfile", dest="spot_file",
        help="The SPOT output file.  Best paired with a dupfile.  Needs alignment id.")
    parser.add_argument("--dupfile", dest="dup_file",
        help="The Picard dup results file.  Best paired with a spotfile.  Needs alignment id.")
    
    # also needs alignment_id
    parser.add_argument("--countsfile", dest="counts_file",
        help="A tab delineated list of counts.  Needs alignnment id.")
    
        # A lane can have multiple fastQC files, one for each read
    parser.add_argument("--flowcell_lane_id", dest="flowcell_lane_id", type=int,
        help="The ID of the flowcell lane we're working on.")
    parser.add_argument("--fastqcfile", dest="fastqc_files", action="append",
        help="A FastQC file to upload.")
    parser.add_argument("--insertsfile", dest="inserts_file",
        help="A Picard CollectInsertSizeMetrics text file.")

    parser.set_defaults( **script_options )
    parser.set_defaults( quiet=False, debug=False )

    return parser

def split_sample_name(samplename):

    m = re.match(r'(?P<sample>[^/]+)_(?P<barcode>[AGTC-]+|NoIndex)_L00(?P<lane>[0-9])', samplename)
    
    if not m:
        print "Could not parse sample name: %s" % samplename
        return None
    
    return { "sample": m.group('sample'), "barcode": m.group('barcode'), "lane": m.group('lane') }

def get_spot_score(spot_file):
    
    contents = open(spot_file, 'r').read()
    stats = contents.split("\n")[1].split()
    
    return {"total_tags": int(stats[0]), "tags_in_hotspots": int(stats[1]), "spot_score": stats[2]}

def get_dup_score(spotdup_file):
    
    infile = open(spotdup_file, 'r')
    
    try:
        for line in infile:
            if line.startswith("LIBRARY"):
                percent_duplication = float(infile.next().strip().split("\t")[7])
        
        return percent_duplication
    except UnboundLocalError as e:
        print "Unbound Local Error for %s" % spotdup_file
        print e
    except IndexError as e:
        print e
    
    return None

class UploadLIMS(object):

    def __init__(self, api_url, token):
       self.api_url = api_url
       self.token = token
       self.headers = {'Authorization': "Token %s" % token}
       self.fastqc_tags = None
       self.count_types = {}
       self.flowcelllane_contenttype = None
       self.flowcell_lane_cache = {}
       self.alignment_counts = {}
       self.picard_metrics = None

    def clear_flowcell_cache(self, flowcell):
       
       r = requests.get("%s/flowcell_run/?label=%s" % (self.api_url, flowcell), headers = self.headers)
       
       if not r.ok:
           print "Failure to reset flowcell cache for %s" % flowcell
           print r
           return
              
       flowcell_results = r.json()
       if flowcell_results["count"] != 1:
           print "Could not find one flowcell for label %s" % flowcell
           print flowcell_results
       
       print requests.get("%s/clear_cache/" % flowcell_results['results'][0]['url'], headers = self.headers).json()
       
    def get_fastqc_tags(self):

       if not self.fastqc_tags:
           tags_url = '%s/fastqc_tag/' % self.api_url
           tags = list()

           tags_results = requests.get(tags_url, headers = self.headers).json()
           tags.extend(tags_results['results'])

           while tags_results['next']:
               tags_results = requests.get(tags_results['next'], headers = self.headers).json()
               tags.extend(tags_results['results'])

           self.fastqc_tags = dict([(tag['slug'], tag) for tag in tags])
        
       return self.fastqc_tags

    def get_picard_metrics(self):

       if not self.picard_metrics:
           metrics_url = '%s/picard_metric/' % self.api_url
           picard_metrics = list()

           metrics_results = requests.get(metrics_url, headers = self.headers).json()
           picard_metrics.extend(metrics_results['results'])

           while metrics_results['next']:
               metrics_results = requests.get(metrics_results['next'], headers = self.headers).json()
               picard_metrics.extend(metrics_results['results'])

           self.picard_metrics = dict([(metric['name'], metric) for metric in picard_metrics])
        
       return self.picard_metrics

    def get_flowcelllane_contenttype(self):
        if not self.flowcelllane_contenttype: 
            contenttype_url = '%s/content_type/?model=flowcelllane' % self.api_url
            contenttype_results = requests.get(contenttype_url, headers = self.headers).json()
            self.flowcelllane_contenttype = contenttype_results['results'][0]
        return self.flowcelllane_contenttype

    def get_count_type(self, name):
        
        if not name:
            return None
        
        if not name in self.count_types:
            exists = requests.get("%s/flowcell_lane_count_type/?codename=%s" % (self.api_url, name), headers = self.headers)
            if exists.ok:
                self.count_types[name] = exists.json()['results'][0]
            else:
                print "Count type %s not found" % name
                self.count_types[name] = None

        return self.count_types[name]
                
    # TODO : make sure that no more of one count type exists
    def get_alignment_counts(self, alignment_id):
        
        print "Getting alignment counts for %d" % alignment_id
        
        if not alignment_id in self.alignment_counts:
            counts_url = "%s/flowcell_lane_count/?alignment=%d" % (self.api_url, alignment_id)
            counts = list()
            
            counts_results = requests.get(counts_url, headers = self.headers).json()
            counts.extend(counts_results['results'])
            
            while counts_results['next']:
                counts_results = requests.get(counts_results['next'], headers = self.headers).json()
                counts.extend(counts_results['results'])
            
            self.alignment_counts[alignment_id] = dict([(count['count_type_name'], count) for count in counts])
        else:
            return self.alignment_counts[alignment_id]
        
    def get_flowcell_lane(self, flowcell_lane_id):
        
        if flowcell_lane_id in self.flowcell_lane_cache:
            return self.flowcell_lane_cache[flowcell_lane_id]
        print "%s/flowcell_lane/%d" % (self.api_url, flowcell_lane_id)
        exists = requests.get("%s/flowcell_lane/%d" % (self.api_url, flowcell_lane_id), headers = self.headers)
        if exists.ok:
            self.flowcell_lane_cache[flowcell_lane_id] = exists.json()
        else:
            print "Flowcell lane %d not found" % flowcell_lane_id
            print exists
            self.flowcell_lane_cache[flowcell_lane_id] = None

        return self.flowcell_lane_cache[flowcell_lane_id]

    def upload_counts(self, alignment_id, counts_file):
        
        content = open(counts_file, 'r')
        
        self.get_alignment_counts(alignment_id)
        
        for line in content:
            values = line.split()
            count_type_name = values[0]
            count = int(values[1])
            
            if not count_type_name:
                continue
            
            self.upload_count(alignment_id, count_type_name, count)

        content.close()

    def upload_count(self, alignment_id, count_type_name, count):
     
        if count_type_name in self.alignment_counts[alignment_id]:
            exists = self.alignment_counts[alignment_id][count_type_name]
            if exists['count'] != count:
                print "Updating count %s (%d) for alignment %d" % (count_type_name, count, alignment_id)
                exists['count'] = count
                result = requests.put(exists['url'], headers = self.headers, data = exists)
                print result.json()
            return

        count_type = self.get_count_type(count_type_name)
        
        if not count_type:
            print "Error: no count type named %s" % count_type_name
            return

        print "Uploading new count %s (%d) for alignment ID %d" % (count_type_name, count, alignment_id)
        data = {
            "alignment": "%s/flowcell_lane_alignment/%d/" % (self.api_url, alignment_id),
            "count_type": "%s/flowcell_lane_count_type/%d/" % (self.api_url, count_type['id']),
            "count": count,
        }
        
        print "%s/flowcell_lane_count/"
        result = requests.post("%s/flowcell_lane_count/" % self.api_url, headers = self.headers, data = data)
        
        print result
                
    def upload_spot(self, alignment_id, spot_file, dup_file):
        
        if not spot_file and dup_file:
            print "Error, do not have both files for alignment %s" % alignment_id

        spot_stats = get_spot_score(spot_file)
        percent_dup = get_dup_score(dup_file)
        
        data = {
            "alignment": "%s/flowcell_lane_alignment/%d/" % (self.api_url, alignment_id)
        }
        
        if spot_stats:
            data.update(spot_stats)
        
        data["percent_duplication"] = percent_dup
        
        print data["percent_duplication"]
        
        exists = requests.get("%s/flowcell_lane_spot/?alignment=%d" % (self.api_url, alignment_id), headers = self.headers)   

        if not exists.ok:
            print exists
        else:
            exists = exists.json()
            
        if exists["count"] == 1:
            origspot = exists['results'][0]
            if data["spot_score"] != origspot["spot_score"] or \
              data["total_tags"] != origspot["total_tags"] or \
              data["tags_in_hotspots"] != origspot["tags_in_hotspots"] or\
              data["percent_duplication"] != origspot["percent_duplication"]:
                print "Updating SPOT score for %d" % alignment_id
                print exists['results'][0]['url']
                print data
                result = requests.patch(exists['results'][0]['url'], headers = self.headers, data = data)
                print result.json()
        elif exists["count"] == 0:
            print "Uploading new spot for %d" % alignment_id
            result = requests.post("%s/flowcell_lane_spot/" % (self.api_url), headers = self.headers, data = data)
            print result.json()
        else:
            print "Could not figure out which SPOT score to upload to!"
            print exists

    def upload_fastqc(self, flowcell_lane_id, filename):

        if not self.fastqc_tags:
            self.fastqc_tags = self.get_fastqc_tags()
        if not self.flowcelllane_contenttype:
            self.get_flowcelllane_contenttype()

        m = re.search(r'(?P<samplename>[^/]+)_(?P<barcode>[AGTC-]+|NoIndex)_L00(?P<lane>[0-9])_(?P<read>R[12])', filename)

        if not m:
            print "Could not figure out %s" % filename
            return None

        print m.groups()

        fastqc_report = None

        try:
            fastqc_report = open(filename, 'r').read()
        except:
            print "Could not read fastqc file %s" % filename
            return None
        
        samplename = m.group('samplename')
        read = m.group('read')
            
        lane_info = self.get_flowcell_lane(flowcell_lane_id)   
   
        if not lane_info:
            return False
 
        tag = self.fastqc_tags[read]
    
        upload = dict()
    
        upload['tags'] = [tag['url']]
        upload['raw_data'] = fastqc_report
        upload['content_type'] = self.flowcelllane_contenttype["url"]
        upload['object_id'] = lane_info['id']
        upload['label'] = "FC%s %s %s %s %s" % (lane_info['flowcell_label'], samplename, str(lane_info["lane"]), lane_info["barcode_index"], read)

        # does this report already exist?
        exists = requests.get("%s/fastqc_report/?label=%s&object_id=%d&content_type=%d" % (self.api_url, upload['label'], upload['object_id'], self.flowcelllane_contenttype["id"]), headers = self.headers).json()
   
        # replace content 
        if exists['count'] == 1:
            report = exists['results'][0]
            if report['raw_data'] != upload['raw_data']:
                print "Updating report %s" % upload['label']
                result = requests.patch(exists['results'][0]['url'], headers = self.headers, data = upload)
                print result.json()
        else:
            print "Uploading new fastqc report %s" % upload['label']
            result = requests.post("%s/fastqc_report/" % self.api_url, headers = self.headers, data = upload)
            print result
            print result.json()
       
    def upload_inserts(self, flowcell_lane_id, filename, metric="CollectInsertSizeMetrics"):

        if not self.picard_metrics:
            self.picard_metrics = self.get_picard_metrics()
        if not self.flowcelllane_contenttype:
            self.get_flowcelllane_contenttype()

        picard_metric  = None

        try:
            picard_metric = open(filename, 'r').read()
        except:
            print "Could not read picard metric file %s" % filename
            return None
            
        lane_info = self.get_flowcell_lane(flowcell_lane_id)   
   
        if not lane_info:
            return False
 
        metric = self.picard_metrics[metric]
    
        upload = dict()
    
        upload['metrics'] = [metric['url']]
        upload['raw_data'] = picard_metric
        upload['content_type'] = self.flowcelllane_contenttype["url"]
        upload['object_id'] = lane_info['id']
        upload['label'] = "FC%s %s %s %s" % (lane_info['flowcell_label'], lane_info["samplesheet_name"], str(lane_info["lane"]), lane_info["barcode_index"])

        # does this report already exist?
        exists = requests.get("%s/picard_report/?label=%s&object_id=%d&content_type=%s" % (self.api_url, upload['label'], upload['object_id'], self.flowcelllane_contenttype["id"]), headers = self.headers).json()
   
        # replace content 
        if exists['count'] == 1:
            report = exists['results'][0]
            if report['raw_data'] != upload['raw_data']:
                print "Updating report %s" % upload['label']
                result = requests.put(exists['results'][0]['url'], headers = self.headers, data = upload).json()
                print result
        else:
            print "Uploading new picard report %s" % upload['label']
            result = requests.post("%s/picard_report/" % self.api_url, headers = self.headers, data = upload)
            print result.json()
            
def main(args = sys.argv):
    """This is the main body of the program that by default uses the arguments
from the command line."""

    parser = parser_setup()
    poptions = parser.parse_args()

    if poptions.quiet:
        logging.basicConfig(level=logging.WARNING, format=log_format)
    elif poptions.debug:
        logging.basicConfig(level=logging.DEBUG, format=log_format)
    else:
        # Set up the logging levels
        logging.basicConfig(level=logging.INFO, format=log_format)

    if not poptions.base_api_url and "LIMS_API_URL" in os.environ:
        api_url = os.environ["LIMS_API_URL"]
    elif poptions.base_api_url:
        api_url = poptions.base_api_url
    else:
        sys.stderr.write("Could not find LIMS API URL.\n")
        sys.exit(1)

    if not poptions.token and "LIMS_API_TOKEN" in os.environ:
        token = os.environ["LIMS_API_TOKEN"]
    elif poptions.token:
        token = poptions.token
    else:
        sys.stderr.write("Could not find LIMS API TOKEN.\n")
        sys.exit(1)

    uploader = UploadLIMS(api_url, token)

    for fastqc_file in poptions.fastqc_files:
        uploader.upload_fastqc(poptions.flowcell_lane_id, fastqc_file)

    if poptions.inserts_file:
        uploader.upload_inserts(poptions.flowcell_lane_id, poptions.inserts_file)

    if poptions.spot_file or poptions.dup_file:
        uploader.upload_spot(poptions.alignment_id, poptions.spot_file, poptions.dup_file)
        
    if poptions.counts_file:
        uploader.upload_counts(poptions.alignment_id, poptions.counts_file)
    
    if poptions.flowcell:
        uploader.clear_flowcell_cache(poptions.flowcell)

    
# This is the main body of the program that only runs when running this script
# doesn't run when imported, so you can use the functions above in the shell after importing
# without automatically running it
if __name__ == "__main__":
    main()