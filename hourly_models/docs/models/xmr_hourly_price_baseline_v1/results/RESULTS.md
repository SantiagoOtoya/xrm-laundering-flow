# Hourly price-only baseline

Reserved historical outcomes were inspected previously; this is not a pristine holdout.

Frozen hurdle: 3%. Economically supported selection: False.
No incident data used. Final 20% excluded. Outer scores never select features, hurdle or policy.

| Fold | Rows | Log loss / baseline | Brier / baseline | AUC | Accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 10668 | 0.6850 / 0.6849 | 0.2459 / 0.2458 | 0.4841 | 57.82% |
| 2 | 10767 | 0.6366 / 0.6377 | 0.2221 / 0.2226 | 0.5822 | 67.99% |
| 3 | 7104 | 0.5684 / 0.5809 | 0.1891 / 0.1949 | 0.6404 | 78.24% |

See summary.json for calibration, dependent-label uncertainty, economic results, cost stress and benchmarks.
Portfolio marks missing from the source remain unknown; incomplete risk histories cannot support hurdle selection.
Forecast labels use completed-close returns; paper fills occur one hour later. These are separate clocks.
