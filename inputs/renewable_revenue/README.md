# Renewable Revenue Model Input Templates

These files define the default standardized input interface for `renewable_revenue_model.py`.

- `generation_history.csv`: monthly renewable generation history used for P10/P50/P90 generation forecasting.
- `power_price_scenario.csv`: monthly power price scenarios.
- `green_premium_scenario.csv`: monthly green power premium scenarios.
- `gec_price_scenario.csv`: monthly green certificate price scenarios.

Run the model with:

```powershell
python renewable_revenue_model.py --input-dir inputs\renewable_revenue --export-dir validation_outputs\renewable_revenue
```

Standard outputs:

- `renewable_revenue_scenarios.csv`: scenario-level generation, power revenue, green premium revenue, GEC revenue, and total revenue.
- `renewable_revenue_summary.json`: summary metrics, risk indicators, assumptions, and sensitivity ranking.
- `renewable_revenue_dashboard.png`: report-ready dashboard.
- `renewable_revenue_dashboard.pdf`: vector-friendly report export.

The JSON uses schema version `renewable_revenue_io_v1`.
