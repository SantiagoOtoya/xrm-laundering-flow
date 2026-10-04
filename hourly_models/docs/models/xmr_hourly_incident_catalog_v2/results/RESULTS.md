# Retrospective catalog-date incident comparison

Reserved historical outcomes were inspected earlier in the project; this is not an untouched historical holdout. Stronger confirmation requires future observations after a full policy freeze.

The price-only outer development scores were inspected before this catalog-date amendment. These paired chronological results are exploratory retrospective evidence, not prospectively specified independent tests. Catalog dates and eventual losses can introduce look-ahead and reporting-selection bias; next-day activation does not eliminate either. No live incident-alert edge is established.

Frozen hurdle: 3%. Economically supported selection: False.

| Comparison | Pooled rows | Log loss | Brier | AUC | Accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| prevalence | 28539 | 0.6412 | 0.2244 | 0.5321 | 66.74% |
| market | 28539 | 0.6377 | 0.2228 | 0.5438 | 66.74% |
| presence | 28539 | 0.6400 | 0.2238 | 0.5419 | 66.74% |
| full_incident | 28539 | 0.6400 | 0.2238 | 0.5410 | 66.74% |

| Outer block | Comparison | Rows | L2 | Log loss | Brier | AUC | Accuracy |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | market | 10668 | 1.0 | 0.6850 | 0.2459 | 0.4841 | 57.82% |
| 1 | presence | 10668 | 1.0 | 0.6851 | 0.2459 | 0.4889 | 57.82% |
| 1 | full_incident | 10668 | 1.0 | 0.6851 | 0.2459 | 0.4818 | 57.82% |
| 1 | prevalence | 10668 | constant | 0.6849 | 0.2458 | 0.5000 | 57.82% |
| 2 | market | 10767 | 1.0 | 0.6366 | 0.2221 | 0.5822 | 67.99% |
| 2 | presence | 10767 | 1.0 | 0.6366 | 0.2221 | 0.5756 | 67.99% |
| 2 | full_incident | 10767 | 1.0 | 0.6366 | 0.2221 | 0.5725 | 67.99% |
| 2 | prevalence | 10767 | constant | 0.6377 | 0.2226 | 0.5000 | 67.99% |
| 3 | market | 7104 | 0.1 | 0.5684 | 0.1891 | 0.6404 | 78.24% |
| 3 | presence | 7104 | 1.0 | 0.5773 | 0.1932 | 0.6084 | 78.24% |
| 3 | full_incident | 7104 | 1.0 | 0.5773 | 0.1932 | 0.6134 | 78.24% |
| 3 | prevalence | 7104 | constant | 0.5809 | 0.1949 | 0.5000 | 78.24% |

Catalog activation is assumed at next-day UTC midnight. Frozen reported losses and catalog absence are retrospective proxies; unavailable detection/publication fields remain unchanged.
The baseline's saved 3% fallback was inherited without any new hurdle search. Every comparator was refitted on exactly the same training/test population.

See summary.json for each outer block, incident/ordinary groups, calibration curves, probability distributions, paper returns, unresolved exits, drawdown, exposure and paired 168-hour uncertainty.
No reserved outcomes were evaluated. The fallback, if used, is descriptive and supplies no claim of a tradable edge.
