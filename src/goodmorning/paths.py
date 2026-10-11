"""Public resources shared by checkout and manually copied deployments."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_ASSETS = ROOT / 'assets' / 'web'
