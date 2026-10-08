"""Run pytest and write results to .test_report.txt (no shell pipes needed)."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
py = root / ".venv" / "Scripts" / "python.exe"
cmd = [str(py), "-m", "pytest", "tests", "-v"]
proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=300)
report = root / ".test_report.txt"
report.write_text(
    f"$ {' '.join(cmd)}\nreturncode={proc.returncode}\n\n=== STDOUT ===\n{proc.stdout}\n\n=== STDERR ===\n{proc.stderr}\n",
    encoding="utf-8",
)
print(f"wrote {report} rc={proc.returncode}")
