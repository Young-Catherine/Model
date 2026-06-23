import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize


SOURCE = {
    "title": "Combined Heat and Power Economic Dispatching within Energy Network using Hybrid Metaheuristic Technique",
    "journal": "Energies 2023, 16, 1221",
    "url": "https://www.mdpi.com/1996-1073/16/3/1221",
    "doi": "10.3390/en16031221",
}

POWER_DEMAND = 160.0
HEAT_DEMAND = 220.0

POWER_UNIT = {
    "id": 1,
    "p_min": 35.0,
    "p_max": 135.0,
    "cost": {"a3": 0.000115, "a2": 0.00172, "a1": 0.6997, "a0": 254.8863},
}

CHP_UNITS = {
    2: {
        "for": [(44.0, 0.0), (44.0, 15.9), (40.0, 75.0), (110.2, 135.6), (125.8, 32.4), (125.8, 0.0)],
        "cost": {"c": 1250.0, "b": 36.0, "a": 0.0435, "d": 0.027, "f": 0.011, "e": 0.6},
    },
    3: {
        "for": [(20.0, 0.0), (10.0, 40.0), (45.0, 55.0), (60.0, 0.0)],
        "cost": {"c": 2650.0, "b": 34.5, "a": 0.1035, "d": 0.025, "f": 0.051, "e": 2.203},
    },
    4: {
        "for": [(35.0, 0.0), (35.0, 20.0), (90.0, 45.0), (90.0, 25.0), (105.0, 0.0)],
        "cost": {"c": 1565.0, "b": 20.0, "a": 0.072, "d": 0.02, "f": 0.04, "e": 0.34},
    },
}

HEAT_UNIT = {
    "id": 5,
    "h_min": 0.0,
    # Table A1 visually shows 2695.20, but Table 1 solutions in the same paper
    # consistently cap H5 at 60 MWth. Use the internally consistent test-system
    # limit for reproduction and record the discrepancy in the report.
    "h_max": 60.0,
    "table_a1_h_max_visual": 2695.2,
    "cost": {"c": 950.0, "a": 0.038, "b": 2.0109},
}

PAPER_TABLE_1 = {
    "JAYA": {
        "P1": 41.8990,
        "P2": 64.0012,
        "P3": 10.0000,
        "P4": 44.1006,
        "H2": 95.5961,
        "H3": 40.0000,
        "H4": 24.4042,
        "H5": 60.0000,
        "reported_min_cost": 11753.1479,
    },
    "Rao-3": {
        "P1": 41.9101,
        "P2": 63.8002,
        "P3": 10.0000,
        "P4": 44.2904,
        "H2": 95.6299,
        "H3": 40.0000,
        "H4": 24.3700,
        "H5": 60.0000,
        "reported_min_cost": 11749.8400,
    },
    "Hybrid CHPED": {
        "P1": 39.2114,
        "P2": 60.1594,
        "P3": 10.0000,
        "P4": 50.6289,
        "H2": 92.8700,
        "H3": 40.0001,
        "H4": 27.1304,
        "H5": 60.0000,
        "reported_min_cost": 11746.7751,
        "reported_ca_cost": 11746.2099,
    },
}


def polygon_orientation(points):
    area = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        area += x1 * y2 - x2 * y1
    return 1.0 if area >= 0 else -1.0


def polygon_edge_margins(points, p, h):
    orient = polygon_orientation(points)
    margins = []
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        cross = (x2 - x1) * (h - y1) - (y2 - y1) * (p - x1)
        margins.append(orient * cross)
    return np.array(margins, dtype=float)


def point_in_triangle(point, triangle):
    margins = polygon_edge_margins(triangle, point[0], point[1])
    return bool(np.min(margins) >= -1e-8)


def triangulate_polygon(points):
    """Ear-clip the simple FOR polygon into convex triangles."""
    vertices = list(points)
    orient = polygon_orientation(vertices)
    triangles = []
    guard = 0
    while len(vertices) > 3 and guard < 100:
        guard += 1
        clipped = False
        n = len(vertices)
        for i in range(n):
            prev_pt = vertices[(i - 1) % n]
            cur_pt = vertices[i]
            next_pt = vertices[(i + 1) % n]
            cross = (
                (cur_pt[0] - prev_pt[0]) * (next_pt[1] - prev_pt[1])
                - (cur_pt[1] - prev_pt[1]) * (next_pt[0] - prev_pt[0])
            )
            if orient * cross < -1e-9:
                continue
            triangle = [prev_pt, cur_pt, next_pt]
            contains_other_vertex = any(
                point_in_triangle(pt, triangle)
                for j, pt in enumerate(vertices)
                if j not in {((i - 1) % n), i, ((i + 1) % n)}
            )
            if contains_other_vertex:
                continue
            triangles.append(triangle)
            del vertices[i]
            clipped = True
            break
        if not clipped:
            raise RuntimeError(f"Failed to triangulate polygon: {points}")
    triangles.append(vertices)
    return triangles


TRIANGLES_BY_UNIT = {
    unit_id: triangulate_polygon(unit["for"]) for unit_id, unit in CHP_UNITS.items()
}


def power_cost(p):
    c = POWER_UNIT["cost"]
    return c["a3"] * p**3 + c["a2"] * p**2 + c["a1"] * p + c["a0"]


def chp_cost(unit_id, p, h):
    c = CHP_UNITS[unit_id]["cost"]
    return c["a"] * p**2 + c["b"] * p + c["c"] + c["d"] * h**2 + c["e"] * h + c["f"] * p * h


def heat_cost(h):
    c = HEAT_UNIT["cost"]
    return c["a"] * h**2 + c["b"] * h + c["c"]


def total_cost(x):
    p1, p2, p3, p4, h2, h3, h4, h5 = x
    return (
        power_cost(p1)
        + chp_cost(2, p2, h2)
        + chp_cost(3, p3, h3)
        + chp_cost(4, p4, h4)
        + heat_cost(h5)
    )


def vector_from_solution(solution):
    return np.array(
        [
            solution["P1"],
            solution["P2"],
            solution["P3"],
            solution["P4"],
            solution["H2"],
            solution["H3"],
            solution["H4"],
            solution["H5"],
        ],
        dtype=float,
    )


def equality_residuals(x):
    p1, p2, p3, p4, h2, h3, h4, h5 = x
    return {
        "power_balance_mw": p1 + p2 + p3 + p4 - POWER_DEMAND,
        "heat_balance_mwth": h2 + h3 + h4 + h5 - HEAT_DEMAND,
    }


def for_min_margin(x):
    _, p2, p3, p4, h2, h3, h4, _ = x
    pairs = {2: (p2, h2), 3: (p3, h3), 4: (p4, h4)}
    margins = []
    for unit_id, (p, h) in pairs.items():
        triangle_margins = [
            float(np.min(polygon_edge_margins(triangle, p, h)))
            for triangle in TRIANGLES_BY_UNIT[unit_id]
        ]
        margins.append(max(triangle_margins))
    return min(margins)


def for_validity(x, tolerance=1e-6):
    return bool(for_min_margin(x) >= -tolerance)


def constraints(triangles_by_unit):
    cons = [
        {"type": "eq", "fun": lambda x: x[0] + x[1] + x[2] + x[3] - POWER_DEMAND},
        {"type": "eq", "fun": lambda x: x[4] + x[5] + x[6] + x[7] - HEAT_DEMAND},
    ]
    for unit_id, p_index, h_index in [(2, 1, 4), (3, 2, 5), (4, 3, 6)]:
        points = triangles_by_unit[unit_id]
        orient = polygon_orientation(points)
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
            cons.append(
                {
                    "type": "ineq",
                    "fun": lambda x, x1=x1, y1=y1, x2=x2, y2=y2, orient=orient, p_index=p_index, h_index=h_index: orient
                    * ((x2 - x1) * (x[h_index] - y1) - (y2 - y1) * (x[p_index] - x1)),
                }
            )
    return cons


def bounds():
    chp_bounds = []
    for unit_id in [2, 3, 4]:
        points = CHP_UNITS[unit_id]["for"]
        chp_bounds.append((min(p for p, _ in points), max(p for p, _ in points)))
    for unit_id in [2, 3, 4]:
        points = CHP_UNITS[unit_id]["for"]
        chp_bounds.append((min(h for _, h in points), max(h for _, h in points)))
    return [
        (POWER_UNIT["p_min"], POWER_UNIT["p_max"]),
        *chp_bounds[:3],
        *chp_bounds[3:],
        (HEAT_UNIT["h_min"], HEAT_UNIT["h_max"]),
    ]


def random_feasible_seed(rng):
    # Start around the paper's feasible candidates and jitter. SLSQP repairs equality and FOR constraints.
    base = vector_from_solution(PAPER_TABLE_1["Hybrid CHPED"])
    jitter = np.array([15, 20, 12, 20, 25, 10, 12, 25], dtype=float) * rng.normal(size=8)
    candidate = base + jitter
    lower = np.array([b[0] for b in bounds()])
    upper = np.array([b[1] for b in bounds()])
    return np.minimum(np.maximum(candidate, lower), upper)


def solve_case():
    starts = [vector_from_solution(v) for v in PAPER_TABLE_1.values()]
    rng = np.random.default_rng(20260623)
    starts.extend(random_feasible_seed(rng) for _ in range(80))
    best = None
    all_runs = []
    run_id = 0
    for tri2 in TRIANGLES_BY_UNIT[2]:
        for tri3 in TRIANGLES_BY_UNIT[3]:
            for tri4 in TRIANGLES_BY_UNIT[4]:
                selected_triangles = {2: tri2, 3: tri3, 4: tri4}
                for start in starts:
                    result = minimize(
                        total_cost,
                        start,
                        method="SLSQP",
                        bounds=bounds(),
                        constraints=constraints(selected_triangles),
                        options={"ftol": 1e-10, "maxiter": 2000, "disp": False},
                    )
                    record = {
                        "run": run_id,
                        "success": bool(result.success),
                        "message": str(result.message),
                        "cost": float(result.fun) if result.success else None,
                        "x": result.x.tolist(),
                        "power_balance_mw": equality_residuals(result.x)["power_balance_mw"],
                        "heat_balance_mwth": equality_residuals(result.x)["heat_balance_mwth"],
                        "for_min_margin": float(for_min_margin(result.x)),
                        "triangles": {
                            "unit_2": tri2,
                            "unit_3": tri3,
                            "unit_4": tri4,
                        },
                    }
                    run_id += 1
                    all_runs.append(record)
                    if (
                        result.success
                        and record["for_min_margin"] >= -1e-6
                        and (best is None or result.fun < best.fun)
                    ):
                        best = result
    if best is None:
        raise RuntimeError("No successful SLSQP run found.")
    return best, all_runs


def summarize_solution(name, x, reported_min_cost=None, reported_ca_cost=None):
    residuals = equality_residuals(x)
    cost = total_cost(x)
    row = {
        "case": name,
        "P1": x[0],
        "P2": x[1],
        "P3": x[2],
        "P4": x[3],
        "H2": x[4],
        "H3": x[5],
        "H4": x[6],
        "H5": x[7],
        "recalculated_cost": cost,
        "reported_min_cost": reported_min_cost,
        "reported_ca_cost": reported_ca_cost,
        "diff_vs_reported_min": None if reported_min_cost is None else cost - reported_min_cost,
        "diff_vs_reported_ca": None if reported_ca_cost is None else cost - reported_ca_cost,
        "power_balance_mw": residuals["power_balance_mw"],
        "heat_balance_mwth": residuals["heat_balance_mwth"],
        "for_min_margin": for_min_margin(x),
        "for_valid": for_validity(x),
    }
    return row


def write_outputs(rows, runs, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "mdpi_energies_2023_reproduction.csv"
    json_path = output_dir / "mdpi_energies_2023_reproduction.json"
    md_path = output_dir / "mdpi_energies_2023_reproduction.md"

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "source": SOURCE,
                "demands": {"power_mw": POWER_DEMAND, "heat_mwth": HEAT_DEMAND},
                "rows": rows,
                "solver": {
                    "method": "SciPy SLSQP multi-start",
                    "successful_runs": sum(1 for r in runs if r["success"]),
                    "total_runs": len(runs),
                },
                "runs": runs,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    best = next(row for row in rows if row["case"] == "This reproduction")
    paper = next(row for row in rows if row["case"] == "Paper Hybrid CHPED")
    md_path.write_text(
        "\n".join(
            [
                "# MDPI Energies 2023 CHPED 5-Unit Reproduction",
                "",
                f"Source: {SOURCE['journal']}, DOI [{SOURCE['doi']}]({SOURCE['url']})",
                "",
                "## Result Summary",
                "",
                f"- Reproduction cost: {best['recalculated_cost']:.4f} $/h",
                f"- Paper Hybrid CHPED reported minimum cost: {paper['reported_min_cost']:.4f} $/h",
                f"- Difference vs paper minimum: {best['recalculated_cost'] - paper['reported_min_cost']:.4f} $/h",
                f"- Power balance residual: {best['power_balance_mw']:.6e} MW",
                f"- Heat balance residual: {best['heat_balance_mwth']:.6e} MWth",
                f"- Minimum FOR edge margin: {best['for_min_margin']:.6e}",
                f"- FOR validity: {best['for_valid']}",
                "",
                "## Interpretation",
                "",
                "The solver reproduces the 5-unit CHPED case using the paper's Appendix A parameters and equality constraints.",
                "The paper's Table 1 dispatch values are used as published comparison points; recalculating them with Equation (1)-(5) and Table A1 coefficients gives a cost different from Table 2's reported statistical cost.",
                "The heat-only unit limit is set to 60 MWth because all three Table 1 solutions use H5 = 60 MWth; the Appendix A PDF visually shows 2695.20, which would make the reported dispatch economically dominated.",
                "This report therefore shows both the equation-based recalculation and the fresh optimization result, which is the safer validation basis for model verification.",
                "",
                "## Dispatch Comparison",
                "",
                "| Case | P1 | P2 | P3 | P4 | H2 | H3 | H4 | H5 | Cost ($/h) | FOR valid |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
                *[
                    f"| {row['case']} | {row['P1']:.4f} | {row['P2']:.4f} | {row['P3']:.4f} | {row['P4']:.4f} | {row['H2']:.4f} | {row['H3']:.4f} | {row['H4']:.4f} | {row['H5']:.4f} | {row['recalculated_cost']:.4f} | {row['for_valid']} |"
                    for row in rows
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    return csv_path, json_path, md_path


def main():
    output_dir = Path("validation_outputs") / "mdpi_energies_2023"
    rows = []
    for name, solution in PAPER_TABLE_1.items():
        rows.append(
            summarize_solution(
                f"Paper {name}",
                vector_from_solution(solution),
                reported_min_cost=solution.get("reported_min_cost"),
                reported_ca_cost=solution.get("reported_ca_cost"),
            )
        )

    best, runs = solve_case()
    rows.append(summarize_solution("This reproduction", best.x))
    csv_path, json_path, md_path = write_outputs(rows, runs, output_dir)

    print("MDPI Energies 2023 CHPED 5-unit reproduction")
    print(f"Source: {SOURCE['url']}")
    print(f"Outputs: {csv_path}, {json_path}, {md_path}")
    for row in rows:
        print(
            f"{row['case']:<24} cost={row['recalculated_cost']:>12.4f} "
            f"P=({row['P1']:.4f}, {row['P2']:.4f}, {row['P3']:.4f}, {row['P4']:.4f}) "
            f"H=({row['H2']:.4f}, {row['H3']:.4f}, {row['H4']:.4f}, {row['H5']:.4f}) "
            f"power_res={row['power_balance_mw']:.2e} heat_res={row['heat_balance_mwth']:.2e}"
        )


if __name__ == "__main__":
    main()
