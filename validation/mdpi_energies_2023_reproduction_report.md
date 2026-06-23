# MDPI Energies 2023 CHPED 5-Unit Reproduction

Source: Energies 2023, 16, 1221, DOI [10.3390/en16031221](https://www.mdpi.com/1996-1073/16/3/1221)

## Result Summary

- Reproduction cost: 11404.5891 $/h
- Paper Hybrid CHPED reported minimum cost: 11746.7751 $/h
- Difference vs paper minimum: -342.1860 $/h
- Power balance residual: 1.932676e-11 MW
- Heat balance residual: -3.038281e-11 MWth
- Minimum FOR edge margin: -5.707079e-10
- FOR validity: True

## Interpretation

The solver reproduces the 5-unit CHPED case using the paper's Appendix A parameters and equality constraints.
The paper's Table 1 dispatch values are used as published comparison points; recalculating them with Equation (1)-(5) and Table A1 coefficients gives a cost different from Table 2's reported statistical cost.
The heat-only unit limit is set to 60 MWth because all three Table 1 solutions use H5 = 60 MWth; the Appendix A PDF visually shows 2695.20, which would make the reported dispatch economically dominated.
This report therefore shows both the equation-based recalculation and the fresh optimization result, which is the safer validation basis for model verification.

## Dispatch Comparison

| Case | P1 | P2 | P3 | P4 | H2 | H3 | H4 | H5 | Cost ($/h) | FOR valid |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Paper JAYA | 41.8990 | 64.0012 | 10.0000 | 44.1006 | 95.5961 | 40.0000 | 24.4042 | 60.0000 | 11410.9328 | False |
| Paper Rao-3 | 41.9101 | 63.8002 | 10.0000 | 44.2904 | 95.6299 | 40.0000 | 24.3700 | 60.0000 | 11407.6863 | False |
| Paper Hybrid CHPED | 39.2114 | 60.1594 | 10.0000 | 50.6289 | 92.8700 | 40.0001 | 27.1304 | 60.0000 | 11417.4693 | False |
| This reproduction | 46.0396 | 68.9604 | 10.0000 | 35.0000 | 100.0000 | 40.0000 | 20.0000 | 60.0000 | 11404.5891 | True |
