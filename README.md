# CS598 Deep Health for Healthcare Project - Team 24

This repository contains code to reproduce the paper *Predicting intraoperative hypotension using deep learning with waveforms of arterial blood pressure, electroencephalogram, and electrocardiogram: Retrospective study* by Y-Y Jo et al. (2022) [1]

Team members, alphabetically by first name:
- Aaron Barrie (abarrie2@illinois.edu)
- Maciej Wieczorek (maciejw2@illinois.edu)
- Shaun Phillips (shaunap2@illinois.edu)

## How to run

The code can be run locally, or in Google Colab. Complete instructions are contained inside of the notebook.

### Quickstart

The fastest way to run a demo version of the code is in Google Colab.

1. Open the [DL4H_Team_24.ipnyb](https://github.com/abarrie2/cs598-dlh-project/blob/main/DL4H_Team_24.ipynb) notebook.
2. Click on "Open in Colab" in the top left.
3. Set the runtime type to "T4 GPU". The code will also run in the default "CPU" instance, but training will take ~10x longer. To do this, in the top right click on the down arrow (Additional connection options) next to "Reconnect", select "Change runtime type", select "T4 GPU" and hit "Save".
4. In the Runtime menu, click on "Run all".

In the default demo mode, the notebook should take approximately 5 minutes to run, including 6 training epochs.

## VitalDB Resources

Open Dataset
https://vitaldb.net/dataset/

Github
https://github.com/vitaldb

Open source code for processing vital files.
https://github.com/vitaldb/vitalutils

Jupyter Notebook Examples
https://github.com/vitaldb/examples

## References

1. Jo Y-Y, Jang J-H, Kwon J-m, Lee H-C, Jung C-W, Byun S, et al. “Predicting intraoperative hypotension using deep learning with waveforms of arterial blood pressure, electroencephalogram, and electrocardiogram: Retrospective study.” PLoS ONE, (2022) 17(8): e0272055 https://doi.org/10.1371/journal.pone.0272055
2. Hatib, Feras, Zhongping J, Buddi S, Lee C, Settels J, Sibert K, Rhinehart J, Cannesson M “Machine-learning Algorithm to Predict Hypotension Based on High-fidelity Arterial Pressure Waveform Analysis” Anesthesiology (2018) 129:4 https://doi.org/10.1097/ALN.0000000000002300
3. Bao, X., Kumar, S.S., Shah, N.J. et al. "AcumenTM hypotension prediction index guidance for prevention and treatment of hypotension in noncardiac surgery: a prospective, single-arm, multicenter trial." Perioperative Medicine (2024) 13:13 https://doi.org/10.1186/s13741-024-00369-9
4. Lee, HC., Park, Y., Yoon, S.B. et al. VitalDB, a high-fidelity multi-parameter vital signs database in surgical patients. Sci Data 9, 279 (2022). https://doi.org/10.1038/s41597-022-01411-5
5. Li Q., Mark R.G. & Clifford G.D. "Artificial arterial blood pressure artifact models and an evaluation of a robust blood pressure and heart rate estimator." BioMed Eng OnLine. (2009) 8:13. pmid:19586547 https://doi.org/10.1186/1475-925X-8-13
6. Park H-J, "VitalDB Python Example Notebooks" GitHub Repository https://github.com/vitaldb/examples/blob/master/hypotension_art.ipynb