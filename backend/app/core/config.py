from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LessonForge AI"
    environment: str = "development"
    secret_key: str = "development-only-change-this-secret-key"
    access_token_expire_minutes: int = 60 * 24 * 30  # 记住我模式默认30天
    access_token_expire_minutes_session: int = 60 * 24  # 未记住我模式默认1天
    database_url: str = "sqlite+aiosqlite:///../storage/app.db"
    storage_root: Path = Path("../storage")
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]
    max_upload_mb: int = 30
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"
    llm_provider: str = "mock"
    llm_timeout_seconds: int = 180
    llm_max_tokens: int = 16000
    ppt_agent_runtime_enabled: bool = True
    # 教学设计 Agent V2 动态工具化流水线开关；关闭时回退旧单次生成路径。
    lesson_plan_agent_runtime_enabled: bool = True
    # 学习任务单 Agent V3 动态工具化流水线开关；关闭时回退旧单次生成路径。
    task_sheet_agent_runtime_enabled: bool = True
    # 视频脚本 Agent V4 动态工具化流水线开关（动态章节 + 意图识别 + 工具 + QA 返修）；
    # 关闭时回退旧单次生成路径。
    video_script_agent_runtime_enabled: bool = False
    # 教师逐字稿 Agent V2 动态工具化流水线开关（意图识别 + 工具修改候选稿 + QA 返修 +
    # 流式可视化）；关闭时回退旧的单次确定性派生路径。默认开启。
    verbatim_agent_runtime_enabled: bool = True
    # 课后练习 Agent V2 动态工具化流水线开关（意图识别 + 多角色 LLM 工具循环 +
    # LLM 语义质询 + QA 返修）；关闭时回退旧单次生成 + 后置质检路径。默认开启。
    exercise_agent_runtime_enabled: bool = True
    ffmpeg_binary: str = ""
    ffprobe_binary: str = ""
    video_max_mb: int = 500
    video_max_concurrency: int = 2
    video_max_duration_seconds: int = 1800
    # Gemini Interactions 原生有声视频仍依赖本地网关暴露 Interactions/Files 代理。
    # 默认关闭，能力探测通过后由部署环境显式开启。
    gemini_interactions_video_enabled: bool = False
    default_language: str = "zh-CN"
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value):
        return value.split(",") if isinstance(value, str) else value

    def prepare_storage(self) -> None:
        for name in ("uploads", "generated", "temp"):
            (self.storage_root / name).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
