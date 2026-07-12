"""API blueprints"""

from app.api.ontology import ontology_bp
from app.api.decision import decision_bp
from app.api.run import run_bp
from app.api.simulation import simulation_bp
from app.api.report import report_bp
from app.api.trash import trash_bp
from app.api.stream import stream_bp

__all__ = [
    'ontology_bp',
    'decision_bp',
    'run_bp',
    'simulation_bp',
    'report_bp',
    'trash_bp',
    'stream_bp',
]
