# Evaluation plan

Task 03 fixes investigator capacity at 10% of cases. Thresholds are selected on validation data only and applied unchanged to the frozen holdout. For discrete scores, selection uses the fullest cutoff that does not exceed capacity; this prevents score ties from silently exceeding the review budget.

The generated report includes precision, recall, average precision, trapezoidal PR-AUC, recall at capacity, confusion matrix, false and missed referrals, fit/score latency, precision-recall points, and holdout slices for gender and accident severity. Brier score and calibration points are reported only for the logistic probability output; the discrete rule score is not presented as a calibrated probability. Gender and other protected or socioeconomic features are excluded from model inputs. Task 04 adds citation accuracy and unsupported-claim tests. Task 06 adds pause/restart/resume tests.

An LLM judge may later score writing quality, but it will not determine the principal release gate.
