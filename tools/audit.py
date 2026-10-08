"""Write a full project inventory + compile report (works around flaky shell capture)."""
import py_compile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out_lines: list[str] = []
out_lines.append("=== TREE (excluding .venv/__pycache__) ===")
for p in sorted(root.rglob("*")):
    if ".venv" in p.parts or "__pycache__" in p.parts:
        continue
    rel = p.relative_to(root)
    out_lines.append(f"{'DIR ' if p.is_dir() else 'FILE'} {rel} ({p.stat().st_size if p.is_file() else 0}b)")

out_lines.append("\n=== COMPILE CHECK ===")
ok = True
for py in sorted(root.rglob("*.py")):
    if ".venv" in py.parts:
        continue
    try:
        py_compile.compile(str(py), doraise=True)
        out_lines.append(f"OK {py.relative_to(root)}")
    except Exception as exc:
        ok = False
        out_lines.append(f"FAIL {py.relative_to(root)}: {exc!r}")

out_lines.append("\nRESULT: " + ("ALL OK" if ok else "FAILURES PRESENT"))
report = root / ".audit_report.txt"
report.write_text("\n".join(out_lines), encoding="utf-8")
print(f"wrote {report} ok={ok}")
