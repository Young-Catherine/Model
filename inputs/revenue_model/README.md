# Revenue Model Input Templates

These files define the default standardized input interface for `Revenue model.py`.

- `unit_params.csv`: physical and operating limits for the CHP/fire-side unit.
- `cost_params.csv`: fuel, startup/shutdown, and heat revenue parameters.
- `carbon_params.csv`: carbon price, actual emission intensities, free allowance benchmarks, and unit conversion.
- `price_series.csv`: hourly spot power prices.
- `heat_demand.csv`: hourly heat load demand.

The model still works without these files by using the embedded default scenario. To run with the template inputs:

```powershell
F:\electricity forecast\venv\Scripts\python.exe "Revenue model.py" --input-dir inputs\revenue_model --export-dir validation_outputs
```

Standard outputs:

- `revenue_model_hourly_results.csv`: hourly dispatch, revenue, cost, carbon cost, and net profit.
- `revenue_model_validation.json`: scenario metadata, verification flags, totals, parameters, and time series.
- `revenue_model_feasible_region.png`: feasible-region figure when plotting is enabled.

The validation JSON uses schema version `revenue_model_io_v1` and records whether inputs came from the embedded default scenario or CSV files.
