# Frozen-model reserved-20% evaluation

Period: 2024-10-20T00:00:00Z through 2026-10-03T00:00:00Z (exclusive).
Target: gross XMR/USD return strictly above 3% over 120 hours. No fitting, scaler estimation or tuning.

Reserved historical outcomes were inspected earlier in the project; this is not an untouched historical holdout. Stronger confirmation requires future observations after a full policy freeze.

The price-only outer development scores were inspected before this catalog-date amendment. These paired chronological results are exploratory retrospective evidence, not prospectively specified independent tests. Catalog dates and eventual losses can introduce look-ahead and reporting-selection bias; next-day activation does not eliminate either. No live incident-alert edge is established.

| Subset | Model | Rows | Log loss | Brier | AUC | Accuracy |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| overall | full_incident | 9716 | 0.634900 | 0.221418 | 0.514608 | 66.93% |
| overall | market | 9716 | 0.635243 | 0.221580 | 0.512070 | 66.94% |
| overall | presence | 9716 | 0.634859 | 0.221396 | 0.515097 | 66.93% |
| overall | prevalence | 9716 | 0.635583 | 0.221744 | 0.500000 | 66.95% |
| active_incident | full_incident | 1111 | 0.674635 | 0.241057 | 0.634200 | 58.51% |
| active_incident | market | 1111 | 0.676815 | 0.242086 | 0.642311 | 58.51% |
| active_incident | presence | 1111 | 0.674270 | 0.240865 | 0.642238 | 58.51% |
| active_incident | prevalence | 1111 | 0.688624 | 0.247476 | 0.500000 | 58.24% |
| ordinary | full_incident | 8605 | 0.629770 | 0.218882 | 0.490500 | 68.02% |
| ordinary | market | 8605 | 0.629876 | 0.218932 | 0.490658 | 68.03% |
| ordinary | presence | 8605 | 0.629771 | 0.218883 | 0.490519 | 68.02% |
| ordinary | prevalence | 8605 | 0.628735 | 0.218422 | 0.500000 | 68.08% |

| Paper policy | Completed | Unresolved | Unfilled | Net return | Max drawdown | Time invested |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| full_incident | 1 | 0 | 0 | 0.69% | 0.74% | 0.70% |
| market | 1 | 0 | 0 | 0.69% | 0.74% | 0.70% |
| presence | 1 | 0 | 0 | 0.69% | 0.74% | 0.70% |
| buy_and_hold | 1 | 0 | 0 | 234.33% | unavailable | 99.99% |
| cash | 0 | 0 | 0 | 0.00% | 0.00% | 0.00% |
| full_incident (4% cost) | 1 | 0 | 0 | 0.49% | 0.74% | 0.70% |
| market (4% cost) | 1 | 0 | 0 | 0.49% | 0.74% | 0.70% |
| presence (4% cost) | 1 | 0 | 0 | 0.49% | 0.74% | 0.70% |

The policy uses p >= 0.60, 10% equity per position, one long position, a one-hour delayed fill and 120 hours held from that fill; costs are subtracted once. Classification instead measures 120 hours from the decision close. Signals are not filtered by future target or exit validity.
Buy-and-hold uses 100% initial XMR exposure and a next-hour entry, versus 10% per model trade. Unknown marks make drawdown unavailable; a missing scheduled exit remains unresolved. Cash returns zero.

9716 identical classification rows; 1111 incident-active rows; 73 distinct active catalog groups.
Probability distributions, calibration, 168-hour paired block intervals, all feature/price exclusions, policy signals and trade ledgers are saved alongside this report.

Labels overlap 119/120 hourly intervals. Catalog dates and eventual loss estimates remain retrospective proxies. These reserved-model scores do not establish causal incident effects, verified live incident availability or executable cross-venue fills. Do not change settings in response to these scores.
