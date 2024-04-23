# Import packages
import os
import random
import copy

from timeit import default_timer as timer

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.manifold import TSNE
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score, precision_recall_curve, auc, confusion_matrix
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import KNeighborsClassifier
import torch
from torch.utils.data import Dataset
import vitaldb

import torch.nn as nn
import torch.nn.functional as F
from tqdm import tqdm
from datetime import datetime


VITALDB_CACHE = './vitaldb_cache'
VITAL_ALL = f"{VITALDB_CACHE}/vital_all"
VITAL_MINI = f"{VITALDB_CACHE}/vital_mini"
VITAL_METADATA = f"{VITALDB_CACHE}/metadata"
VITAL_MODELS = f"{VITALDB_CACHE}/models"
VITAL_PREPROCESS_SCRATCH = f"{VITALDB_CACHE}/data_scratch"
VITAL_EXTRACTED_SEGMENTS = f"{VITALDB_CACHE}/segments"

TRACK_CACHE = None
# when USE_DISK_CACHING is enabled, track and segment data will be flushed to disk
USE_DISK_CACHING = False
# when USE_MEMORY_CACHING is enabled, track data will be persisted in an in-memory cache. Not useful once we have already pre-extracted all event segments
USE_MEMORY_CACHING = False

# When RESET_CACHE is set to True, it will ensure the TRACK_CACHE is disposed and recreated when we do dataset initialization.
# Use as a shortcut to wiping cache rather than restarting kernel
RESET_CACHE = False
PREDICTION_WINDOW = 3
ALL_PREDICTION_WINDOWS = [3, 5, 10, 15]

# Maximum number of cases of interest for which to download data.
# Set to a small value (ex: 20) for demo purposes, else set to None to disable and download and process all.
MAX_CASES = None
#MAX_CASES = 20

# Preloading Cases: when true, all matched cases will have the _mini tracks extracted and put into in-mem dict
PRELOADING_CASES = True

if not os.path.exists(VITALDB_CACHE):
  os.mkdir(VITALDB_CACHE)
if not os.path.exists(VITAL_ALL):
  os.mkdir(VITAL_ALL)
if not os.path.exists(VITAL_MINI):
  os.mkdir(VITAL_MINI)
if not os.path.exists(VITAL_METADATA):
  os.mkdir(VITAL_METADATA)
if not os.path.exists(VITAL_MODELS):
  os.mkdir(VITAL_MODELS)
if not os.path.exists(VITAL_PREPROCESS_SCRATCH):
  os.mkdir(VITAL_PREPROCESS_SCRATCH)
if not os.path.exists(VITAL_EXTRACTED_SEGMENTS):
  os.mkdir(VITAL_EXTRACTED_SEGMENTS)

print(os.listdir(VITALDB_CACHE))


# Returns the Pandas DataFrame for the specified dataset.
#   One of 'cases', 'labs', or 'trks'
# If the file exists locally, create and return the DataFrame.
# Else, download and cache the csv first, then return the DataFrame.
def vitaldb_dataframe_loader(dataset_name):
    if dataset_name not in ['cases', 'labs', 'trks']:
        raise ValueError(f'Invalid dataset name: {dataset_name}')
    file_path = f'{VITAL_METADATA}/{dataset_name}.csv'
    if os.path.isfile(file_path):
        print(f'{dataset_name}.csv exists locally.')
        df = pd.read_csv(file_path)
        return df
    else:
        print(f'downloading {dataset_name} and storing in the local cache for future reuse.')
        df = pd.read_csv(f'https://api.vitaldb.net/{dataset_name}')
        df.to_csv(file_path, index=False)
        return df
		
cases = vitaldb_dataframe_loader('cases')
cases = cases.set_index('caseid')

trks = vitaldb_dataframe_loader('trks')
trks = trks.set_index('caseid')
		
TRACK_NAMES = ['SNUADC/ART', 'SNUADC/ECG_II', 'BIS/EEG1_WAV']
TRACK_SRATES = [500, 500, 128]

# As in the paper, select cases which meet the following criteria:
#
# For patients, the inclusion criteria were as follows:
# (1) adults (age >= 18)
# (2) administered general anaesthesia
# (3) undergone non-cardiac surgery. 
#
# For waveform data, the inclusion criteria were as follows:
# (1) no missing monitoring for ABP, ECG, and EEG waveforms
# (2) no cases containing false events or non-events due to poor signal quality
#     (checked in second stage of data preprocessing)

# Adult
inclusion_1 = cases.loc[cases['age'] >= 18].index
print(f'{len(cases)-len(inclusion_1)} cases excluded, {len(inclusion_1)} remaining due to age criteria')

# General Anesthesia
inclusion_2 = cases.loc[cases['ane_type'] == 'General'].index
print(f'{len(cases)-len(inclusion_2)} cases excluded, {len(inclusion_2)} remaining due to anesthesia criteria')

# Non-cardiac surgery
inclusion_3 = cases.loc[
    ~cases['opname'].str.contains("cardiac", case=False)
    & ~cases['opname'].str.contains("aneurysmal", case=False)
].index
print(f'{len(cases)-len(inclusion_3)} cases excluded, {len(inclusion_3)} remaining due to non-cardiac surgery criteria')

# ABP, ECG, EEG waveforms
inclusion_4 = trks.loc[trks['tname'].isin(TRACK_NAMES)].index.value_counts()
inclusion_4 = inclusion_4[inclusion_4 == len(TRACK_NAMES)].index
print(f'{len(cases)-len(inclusion_4)} cases excluded, {len(inclusion_4)} remaining due to missing waveform data')

# SQI filter
# NOTE: this depends on a sqi_filter.csv generated by external processing
inclusion_5 = pd.read_csv('sqi_filter.csv', header=None, names=['caseid','sqi']).set_index('caseid').index
print(f'{len(cases)-len(inclusion_5)} cases excluded, {len(inclusion_5)} remaining due to SQI threshold not being met')

cases_of_interest_idx = inclusion_1 \
    .intersection(inclusion_2) \
    .intersection(inclusion_3) \
    .intersection(inclusion_4) \
    .intersection(inclusion_5)

cases_of_interest = cases.loc[cases_of_interest_idx]

print()
print(f'{cases_of_interest_idx.shape[0]} out of {cases.shape[0]} total cases remaining after exclusions applied')

# Trim cases of interest to MAX_CASES
if MAX_CASES:
    cases_of_interest_idx = cases_of_interest_idx[:MAX_CASES]
print(f'{cases_of_interest_idx.shape[0]} cases of interest selected')


# Ensure the full vital file dataset is available for cases of interest.
count_downloaded = 0
count_present = 0

#for i, idx in enumerate(cases.index):
for i, idx in enumerate(cases_of_interest_idx):
    full_path = f'{VITAL_ALL}/{idx:04d}.vital'
    if not os.path.isfile(full_path):
        print(f'Missing vital file: {full_path}')
        # Download and save the file.
        vf = vitaldb.VitalFile(idx)
        vf.to_vital(full_path)
        count_downloaded += 1
    else:
        count_present += 1

print()
print(f'Count of cases of interest:           {cases_of_interest_idx.shape[0]}')
print(f'Count of vital files downloaded:      {count_downloaded}')
print(f'Count of vital files already present: {count_present}')


# Convert vital files to "mini" versions including only the subset of tracks defined in TRACK_NAMES above.
# Only perform conversion for the cases of interest.
# NOTE: If this cell is interrupted, it can be restarted and will continue where it left off.
count_minified = 0
count_present = 0

for i, idx in enumerate(cases_of_interest_idx):
    full_path = f'{VITAL_ALL}/{idx:04d}.vital'
    mini_path = f'{VITAL_MINI}/{idx:04d}_mini.vital'
    if not os.path.isfile(mini_path):
        print(f'Creating mini vital file: {idx}')
        vf = vitaldb.VitalFile(full_path, TRACK_NAMES)
        vf.to_vital(mini_path)
        count_minified += 1
    else:
        count_present += 1

print()
print(f'Count of cases of interest:           {cases_of_interest_idx.shape[0]}')
print(f'Count of vital files minified:        {count_minified}')
print(f'Count of vital files already present: {count_present}')

from scipy.signal import butter, lfilter, spectrogram

# define two methods for data preprocessing

def apply_bandpass_filter(data, lowcut, highcut, fs, order=5):
    b, a = butter(order, [lowcut, highcut], fs=fs, btype='band')
    y = lfilter(b, a, np.nan_to_num(data))
    return y

def apply_zscore_normalization(signal):
    mean = np.nanmean(signal)
    std = np.nanstd(signal)
    return (signal - mean) / std


# Preprocess data tracks
ABP_TRACK_NAME = "SNUADC/ART"
ECG_TRACK_NAME = "SNUADC/ECG_II"
EEG_TRACK_NAME = "BIS/EEG1_WAV"
MINI_FILE_FOLDER = VITAL_MINI
CACHE_FILE_FOLDER = VITAL_PREPROCESS_SCRATCH

if RESET_CACHE:
    TRACK_CACHE = None

if TRACK_CACHE is None:
    TRACK_CACHE = {}

def get_track_data(case, print_when_file_loaded = False):
    parsedFile = None
    abp = None
    eeg = None
    ecg = None

    for i, (track_name, rate) in enumerate(zip(TRACK_NAMES, TRACK_SRATES)):
        # use integer case id and track name, delimited by pipe, as cache key
        cache_label = f"{case}|{track_name}"
        if cache_label not in TRACK_CACHE:
            if parsedFile is None:
                file_path = f"{MINI_FILE_FOLDER}/{case:04d}_mini.vital"
                if print_when_file_loaded:
                    print(f"[{datetime.now()}] Loading vital file {file_path}")
                parsedFile = vitaldb.VitalFile(file_path, TRACK_NAMES)
            dataset = np.array(parsedFile.get_track_samples(track_name, 1/rate))
            if track_name == ABP_TRACK_NAME:
                # no filtering for ABP
                abp = dataset
                if USE_MEMORY_CACHING:
                    TRACK_CACHE[cache_label] = abp
            elif track_name == ECG_TRACK_NAME:
                ecg = dataset
                # apply ECG filtering: first bandpass then do z-score normalization
                ecg = apply_bandpass_filter(ecg, 1, 40, rate, 2)
                ecg = apply_zscore_normalization(ecg)
                if USE_MEMORY_CACHING:
                    TRACK_CACHE[cache_label] = ecg
            elif track_name == EEG_TRACK_NAME:
                eeg = dataset
                # apply EEG filtering: bandpass only
                eeg = apply_bandpass_filter(eeg, 0.5, 50, rate, 2)
                if USE_MEMORY_CACHING:
                    TRACK_CACHE[cache_label] = eeg
        else:
            # cache hit, pull from cache
            if track_name == ABP_TRACK_NAME:
                abp = TRACK_CACHE[cache_label]
            elif track_name == ECG_TRACK_NAME:
                ecg = TRACK_CACHE[cache_label]
            elif track_name == EEG_TRACK_NAME:
                eeg = TRACK_CACHE[cache_label]

    return (abp, ecg, eeg)

# ABP waveforms are used without further pre-processing
# ECG waveforms are band-pass filtered between 1 and 40 Hz, and Z-score normalized
# EEG waveforms are band-pass filtered between 0.5 and 50 Hz
if PRELOADING_CASES:
    # determine disk cache file label
    maxlabel = "ALL"
    if MAX_CASES is not None:
        maxlabel = str(MAX_CASES)
    picklefile = f"{CACHE_FILE_FOLDER}/{PREDICTION_WINDOW}_minutes_MAX{maxlabel}.trackcache"

    #for track in tqdm(cases_of_interest_idx):
        # getting track data will cause a cache-check and fill when missing
        # will also apply appropriate filtering per track
        #get_track_data(track, False)
    
    print(f"Generated track cache, {len(TRACK_CACHE)} records generated")


# Generate hypotensive events
# Hypotensive events are defined as a 1-minute interval with sustained ABP of less than 65 mmHg
# Note: Hypotensive events should be at least 20 minutes apart to minimize potential residual effects from previous events
# Generate hypotension non-events
# To sample non-events, 30-minute segments where the ABP was above 75 mmHG were selected, and then
# three one-minute samples of each waveform were obtained from the middle of the segment
# both occur in extract_segments
#VITAL_EXTRACTED_SEGMENTS
def extract_segments(cases_of_interest_idx, min_before_event=3, debug=False):
    # Sampling rate for ABP and ECG, Hz. These rates should be the same. Default = 500
    ABP_ECG_SRATE_HZ = 500

    # Sampling rate for EEG. Default = 128
    EEG_SRATE_HZ = 128

    # Length of feature segment, seconds.
    FEATURE_LENGTH_SEC = 60
    # Look ahead to predict hypotension, seconds.
    MIDDLE_LENGTH_SEC  = 60 * min_before_event
    # Length of label segment, seconds.
    LABEL_LENGTH_SEC   = 60

    # Length to move down the ABP track for starting a new analysis segment, seconds.
    NEW_SEGMENT_OFFSET_SEC = 10

    # Final dataset for training and testing the model.
    # inputs with shape of (segments, timepoints)
    samples = []
    invalid_samples = []

    # Process each case and extract segments. For each segment identify presence of an event in the label zone.
    time_start = timer()
    
    count_cases = len(cases_of_interest_idx)

    for case_count, caseid in tqdm(enumerate(cases_of_interest_idx), total=count_cases):
        if debug:
            print(f'Loading case: {caseid:04d}, ({case_count + 1} of {count_cases})')
        
        if areCaseSegmentsCached(caseid):
            # skip records we've already cached
            continue

        # read the arterial waveform
        (abp, ecg, eeg) = get_track_data(caseid)

        track_length_seconds = int(len(abp) / ABP_ECG_SRATE_HZ)
        
        iohEvents = []
        cleanEvents = []
        i = 0
        started = False
        eofReached = False
        trackStartIndex = None
        
        # FIRST PASS
        # FIRST PASS
        # FIRST PASS
        # in the first forward pass, we are going to identify the start/end boundaries of all IOH events within the case
        while i < track_length_seconds - 60:
            segmentStart = None
            segmentEnd = None
            segFound = False
            
            # look forward one minute
            abpSeg = abp[i * ABP_ECG_SRATE_HZ:(i + 60)* ABP_ECG_SRATE_HZ]
            
            # roll forward until we hit a one minute window where mean ABP >= 65 so we know leads are connected and it's tracking
            if not started:
                if np.nanmean(abpSeg) >= 65:
                    started = True
                    trackStartIndex = i
            # if we're started and mean abp for the window is <65, we are starting a new IOH event
            elif np.nanmean(abpSeg) < 65:
                segmentStart = i
                # now seek forward to find end of event, perpetually checking the lats minute of the IOH event
                for j in range(i + 60, track_length_seconds):
                    # look backward one minute
                    abpSegForward = abp[(j - 60) * ABP_ECG_SRATE_HZ:j * ABP_ECG_SRATE_HZ]
                    if np.nanmean(abpSegForward) >= 65:
                        segmentEnd = j - 1
                        break
                if segmentEnd is None:
                    eofReached = True
                else:
                    # otherwise, end of the IOH segment has been reached, record it
                    iohEvents.append((segmentStart, segmentEnd))
                    segFound = True
            
            i += 1
            if not started:
                continue
            elif eofReached:
                break
            elif segFound:
                i = segmentEnd + 1

        # SECOND PASS
        # SECOND PASS
        # SECOND PASS
        # in the second forward pass, we are going to identify the start/end boundaries of all non-overlapping 30 minute "clean" windows
        # reuse the 'start of signal' index from our first pass
        if trackStartIndex is None:
            trackStartIndex = 0
        i = trackStartIndex
        eofReached = False
        while i < track_length_seconds - 1800:
            segmentStart = None
            segmentEnd = None
            segFound = False
            
            startIndex = i
            endIndex = i + 1800

            # check to see if this 30 minute window overlaps any IOH events, if so ffwd to end of latest overlapping IOH
            overlapFound = False
            latestEnd = None
            for event in iohEvents:
                # case 1: starts during an event
                if startIndex >= event[0] and startIndex < event[1]:
                    latestEnd = event[1]
                    overlapFound = True
                # case 2: ends during an event
                elif endIndex >= event[0] and endIndex < event[1]:
                    latestEnd = event[1]
                    overlapFound = True
                # case 3: event occurs entirely inside of the window
                elif startIndex < event[0] and endIndex > event[1]:
                    latestEnd = event[1]
                    overlapFound = True
            
            # FFWD if we found an overlap
            if overlapFound:
                i = latestEnd + 1
                continue

            # look forward 30 minutes
            abpSeg = abp[startIndex * ABP_ECG_SRATE_HZ:endIndex * ABP_ECG_SRATE_HZ]

            # if we're started and mean abp for the window is >= 75, we are starting a new clean event
            if np.nanmean(abpSeg) >= 75:
                forwardStart = j - 1800
                forwardEnd = j

                overlapFound = False
                latestEnd = None
                for event in iohEvents:
                    # case 1: starts during an event
                    if forwardStart >= event[0] and forwardStart < event[1]:
                        latestEnd = event[1]
                        overlapFound = True
                    # case 2: ends during an event
                    elif forwardEnd >= event[0] and forwardEnd < event[1]:
                        latestEnd = event[1]
                        overlapFound = True
                    # case 3: event occurs entirely inside of the window
                    elif forwardStart < event[0] and forwardEnd > event[1]:
                        latestEnd = event[1]
                        overlapFound = True
                
                if not overlapFound:
                    segFound = True
                    segmentEnd = endIndex
                    cleanEvents.append((startIndex, endIndex))

            i += 10
            if segFound:
                i = segmentEnd + 1

        if debug:
            print(f"IOH Events for case {caseid}: {iohEvents}")
            print(f"Clean Events for case {caseid}: {cleanEvents}")

        positiveSegments = []
        negativeSegments = []

        # THIRD PASS
        # THIRD PASS
        # THIRD PASS
        # in the third pass, we will use the collections of ioh event windows to generate our actual extracted segments based on our prediction window (positive labels)
        for i in range(0, len(iohEvents)):
            # we want to review current event boundaries, as well as previous event boundaries if available
            event = iohEvents[i]
            previousEvent = None
            if i > 0:
                previousEvent = iohEvents[i - 1]
            
            for predWindow in ALL_PREDICTION_WINDOWS:
                predictiveSegmentStart = event[0] - (predWindow*60)
                predictiveSegmentEnd = predictiveSegmentStart + 60

                if (predictiveSegmentStart < 0):
                    # don't rewind before the beginning of the track
                    continue
                elif (predictiveSegmentStart < trackStartIndex):
                    # don't rewind before the beginning of signal in track
                    continue
                elif previousEvent is not None:
                    # does this event window come before or during the previous event?
                    overlapFound = False
                    # case 1: starts during an event
                    if predictiveSegmentStart >= previousEvent[0] and predictiveSegmentStart < previousEvent[1]:
                        overlapFound = True
                    # case 2: ends during an event
                    elif predictiveSegmentEnd >= previousEvent[0] and predictiveSegmentEnd < previousEvent[1]:
                        overlapFound = True
                    # case 3: event occurs entirely inside of the window
                    elif predictiveSegmentStart < previousEvent[0] and predictiveSegmentEnd > previousEvent[1]:
                        overlapFound = True
                    # do not extract a case if we overlap witha nother IOH
                    if overlapFound:
                        continue
                
                # track the positive segment
                positiveSegments.append((predictiveSegmentStart, predictiveSegmentEnd, predWindow))

        # FOURTH PASS
        # FOURTH PASS
        # FOURTH PASS
        # in the fourth and final pass, we will use the collections of clean event windows to generate our actual extracted segments based (negative labels)
        for i in range(0, len(cleanEvents)):
            # everything will be 30 minutes long at least
            event = cleanEvents[i]
            # choose sample 1 @ 10 minutes
            # choose sample 2 @ 15 minutes
            # choose sample 3 @ 20 minutes
            timeAtTen = event[0] + 600
            timeAtFifteen = event[0] + 900
            timeAtTwenty = event[0] + 1200

            negativeSegments.append((timeAtTen, timeAtTen + 60))
            negativeSegments.append((timeAtFifteen, timeAtFifteen + 60))
            negativeSegments.append((timeAtTwenty, timeAtTwenty + 60))

        saveCaseSegments(caseid, positiveSegments, negativeSegments)


    # total processing time
    time_end = timer()
    time_delta = np.round(time_end - time_start, 3)

    
    return pd.DataFrame(samples, columns=['segment_abp', 'segment_ecg', 'segment_eeg', 'segment_label', 'segment_valid', 'caseidx', 'segment_key'])


def areCaseSegmentsCached(caseid):
    seg_folder = f"{VITAL_EXTRACTED_SEGMENTS}/{caseid:04d}"
    return os.path.exists(seg_folder)

def saveCaseSegments(caseid, positiveSegments, negativeSegments):
    
    if len(positiveSegments) == 0 and len(negativeSegments) == 0:
        # exit early if no events found
        return

    seg_folder = f"{VITAL_EXTRACTED_SEGMENTS}/{caseid:04d}"
    if not os.path.exists(seg_folder):
        os.mkdir(seg_folder)
    else:
        # exit early if folder already exists, case already produced
        return

    file_path = f"{MINI_FILE_FOLDER}/{caseid:04d}_mini.vital"
    vf = vitaldb.VitalFile(file_path, TRACK_NAMES)

    for i in range(0, len(positiveSegments)):
        event = positiveSegments[i]
        seg_filename = f"{caseid:04d}_{event[0]}_{event[2]:02d}_True.track"
        seg_fullpath = f"{seg_folder}/{seg_filename}"
        segmentvf = copy.deepcopy(vf)
        segmentvf.crop(event[0], event[1])
        segmentvf.to_vital(seg_fullpath)
    
    for i in range(0, len(negativeSegments)):
        event = negativeSegments[i]
        seg_filename = f"{caseid:04d}_{event[0]}_0_False.track"
        seg_fullpath = f"{seg_folder}/{seg_filename}"
        segmentvf = copy.deepcopy(vf)
        segmentvf.crop(event[0], event[1])
        segmentvf.to_vital(seg_fullpath)  


# samples = extract_segments(cases_of_interest_idx, min_before_event=PREDICTION_WINDOW, debug=True)
caselist = list(cases_of_interest_idx)
random.shuffle(caselist)
print(caselist)
samples = extract_segments(caselist, min_before_event=PREDICTION_WINDOW, debug=False)