"""
Research package (phase P2): does a statistically reliable predictive signal exist?

Separate from the monitoring pipeline: nothing here changes daily reports. Every input is
point-in-time (see panel.py); every hypothesis (feature, expected sign, horizon) is fixed in
code before results are seen (factors.py); every result is reported with its sample, test
statistics and multiple-testing correction (stats.py, experiment.py).
"""
