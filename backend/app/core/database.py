from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def configure_sqlite(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async def create_schema() -> None:
    from app.models import entities  # noqa: F401
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        
        # 兼容性迁移：检查 model_configs 表结构并动态补全缺失列
        def migrate_sqlite_tables(sync_conn):
            inspector = inspect(sync_conn)
            if "model_configs" in inspector.get_table_names():
                columns = [c["name"] for c in inspector.get_columns("model_configs")]
                if "name" not in columns:
                    sync_conn.execute(text("ALTER TABLE model_configs ADD COLUMN name VARCHAR(100) DEFAULT 'LLM 配置'"))
                if "preferences_json" not in columns:
                    sync_conn.execute(text("ALTER TABLE model_configs ADD COLUMN preferences_json JSON DEFAULT '{}'"))
                if "is_active" not in columns:
                    sync_conn.execute(text("ALTER TABLE model_configs ADD COLUMN is_active BOOLEAN DEFAULT 1"))
                if "context_window_tokens" not in columns:
                    sync_conn.execute(text(
                        "ALTER TABLE model_configs ADD COLUMN context_window_tokens INTEGER NOT NULL DEFAULT 1000000"
                    ))
                if "supports_multimodal" not in columns:
                    sync_conn.execute(text(
                        "ALTER TABLE model_configs ADD COLUMN supports_multimodal BOOLEAN NOT NULL DEFAULT 0"
                    ))
                if "capabilities_json" not in columns:
                    sync_conn.execute(text("ALTER TABLE model_configs ADD COLUMN capabilities_json JSON NOT NULL DEFAULT '[]'"))
                    sync_conn.execute(text(
                        "UPDATE model_configs SET capabilities_json = "
                        "CASE WHEN supports_multimodal = 1 THEN '[\"text_generation\",\"structured_output\",\"vision_review\"]' "
                        "ELSE '[\"text_generation\",\"structured_output\"]' END"
                    ))
                if "api_mode" not in columns:
                    sync_conn.execute(text("ALTER TABLE model_configs ADD COLUMN api_mode VARCHAR(50) NOT NULL DEFAULT 'text_chat'"))
                if "adapter_config_json" not in columns:
                    sync_conn.execute(text("ALTER TABLE model_configs ADD COLUMN adapter_config_json JSON NOT NULL DEFAULT '{}'"))

            for table_name in ("course_projects", "course_intake_sessions"):
                if table_name in inspector.get_table_names():
                    table_columns = [c["name"] for c in inspector.get_columns(table_name)]
                    if "model_config_id" not in table_columns:
                        sync_conn.execute(text(
                            f"ALTER TABLE {table_name} ADD COLUMN model_config_id VARCHAR(36)"
                        ))

            compatibility_columns = {
                "generation_runs": {
                    "course_task_id": "VARCHAR(36)",
                    "trigger_type": "VARCHAR(30) NOT NULL DEFAULT 'initial'",
                    "agent_profile_id": "VARCHAR(36)",
                    "memory_revision": "INTEGER NOT NULL DEFAULT 0",
                    "context_manifest_json": "JSON NOT NULL DEFAULT '{}'",
                    "context_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
                    "batch_id": "VARCHAR(40) NOT NULL DEFAULT ''",
                },
                "artifacts": {
                    "source_versions_json": "JSON NOT NULL DEFAULT '{}'",
                    "agent_profile_id": "VARCHAR(36)",
                    "memory_revision_created": "INTEGER NOT NULL DEFAULT 0",
                },
                "agent_messages": {
                    "task_id": "VARCHAR(36)",
                    "run_id": "VARCHAR(36)",
                    "status": "VARCHAR(20) NOT NULL DEFAULT 'completed'",
                    "metadata_json": "JSON NOT NULL DEFAULT '{}'",
                },
                "course_tasks": {
                    "current_agent_profile_id": "VARCHAR(36)",
                    "agent_profile_status": "VARCHAR(30) NOT NULL DEFAULT 'pending'",
                    "agent_profile_error_json": "JSON",
                    "optional_reference_types_json": "JSON NOT NULL DEFAULT '[]'",
                    "required_input_contract_json": "JSON NOT NULL DEFAULT '{}'",
                    "last_context_revision": "INTEGER NOT NULL DEFAULT 0",
                },
                "agent_chat_sessions": {
                    "image_model_config_id": "VARCHAR(36)",
                    "vision_model_config_id": "VARCHAR(36)",
                    "video_model_config_id": "VARCHAR(36)",
                    "speech_model_config_id": "VARCHAR(36)",
                },
                "artifact_assets": {
                    "duration_ms": "INTEGER NOT NULL DEFAULT 0",
                    "source_scene_id": "VARCHAR(80) NOT NULL DEFAULT ''",
                    "metadata_json": "JSON NOT NULL DEFAULT '{}'",
                },
                "pipeline_tool_calls": {
                    "model_call_id": "VARCHAR(120) NOT NULL DEFAULT ''",
                },
                "video_scene_jobs": {
                    "api_mode": "VARCHAR(50) NOT NULL DEFAULT ''",
                    "provider_file_id": "VARCHAR(200) NOT NULL DEFAULT ''",
                    "actual_model_name": "VARCHAR(120) NOT NULL DEFAULT ''",
                },
            }
            for table_name, definitions in compatibility_columns.items():
                if table_name not in inspector.get_table_names():
                    continue
                table_columns = {c["name"] for c in inspector.get_columns(table_name)}
                for column_name, definition in definitions.items():
                    if column_name not in table_columns:
                        sync_conn.execute(text(
                            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                        ))

        await connection.run_sync(migrate_sqlite_tables)


async def get_db():
    async with SessionLocal() as session:
        yield session
