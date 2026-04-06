from celery import Celery

from observatory.core.config import get_settings

settings = get_settings()

app = Celery(
    "observatory",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "sync-voc-hourly": {
            "task": "observatory.ingestion.voc.tasks.sync_all_voc_sources",
            "schedule": 3600.0,  # every hour
        },
        "sync-telemetry-nightly": {
            "task": "observatory.ingestion.telemetry.tasks.sync_all_telemetry",
            "schedule": 86400.0,  # daily
        },
        "detect-friction-nightly": {
            "task": "observatory.analysis.friction.tasks.detect_friction_signals",
            "schedule": 86400.0,
        },
        "score-priorities-nightly": {
            "task": "observatory.analysis.scoring.tasks.recalculate_priority_scores",
            "schedule": 86400.0,
        },
        "weekly-competitor-scan": {
            "task": "observatory.ingestion.external_intel.tasks.scan_all_competitors",
            "schedule": 604800.0,  # weekly
        },
        "weekly-digest": {
            "task": "observatory.output.digests.tasks.generate_weekly_digests",
            "schedule": 604800.0,
        },
        "scan-social-6h": {
            "task": "observatory.ingestion.external_intel.tasks.scan_social_mentions",
            "schedule": 21600,  # 6 hours
        },
    },
)

# Auto-discover tasks from all observatory modules
app.autodiscover_tasks([
    "observatory.ingestion.voc",
    "observatory.ingestion.telemetry",
    "observatory.ingestion.external_intel",
    "observatory.ingestion.knowledge",
    "observatory.ingestion.research",
    "observatory.analysis.friction",
    "observatory.analysis.scoring",
    "observatory.analysis.experiments",
    "observatory.analysis.competitive",
    "observatory.output.digests",
    "observatory.output.battlecards",
    "observatory.output.briefs",
])
