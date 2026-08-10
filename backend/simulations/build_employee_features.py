"""CLI helper to regenerate Data/Simulation/Simulation_Employee_Features.csv.

Run from the repository root:
    python -m backend.simulations.build_employee_features
"""

from pathlib import Path

from .feature_builder import write_employee_simulation_features


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = repo_root / "Data"
    output = data_dir / "Simulation" / "Simulation_Employee_Features.csv"
    write_employee_simulation_features(data_dir, output)
    print(f"Wrote simulation employee features: {output}")
