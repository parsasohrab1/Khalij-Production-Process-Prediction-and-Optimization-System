"""ثبت Experiment و Model Registry در MLflow (فاز ۳).

جریان:
  1. log_run → ثبت پارامتر/متریک/artifact
  2. register_model → ثبت در Model Registry
  3. promote_model → انتقال Staging → Production
  4. load_production_model_uri → URI مدل Production برای سرو آنلاین
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

import mlflow
from mlflow.tracking import MlflowClient

logger = logging.getLogger(__name__)

EXPERIMENT_NAME = "reactor_temp_prediction"
REGISTERED_MODEL_NAME = "reactor_temp_predictor"


def _configure_mlflow_timeouts() -> None:
    """جلوگیری از hang طولانی هنگام در دسترس نبودن سرور MLflow."""
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")


class MLflowModelManager:
    def __init__(self, tracking_uri: str):
        _configure_mlflow_timeouts()
        self.tracking_uri = tracking_uri
        self._enabled = True
        try:
            mlflow.set_tracking_uri(tracking_uri)
            self._client = MlflowClient(tracking_uri)
        except Exception as exc:  # noqa: BLE001
            logger.warning("اتصال اولیه به MLflow ناموفق بود: %s", exc)
            self._enabled = False
            self._client = None

    def ensure_experiment(self) -> str | None:
        if not self._enabled or self._client is None:
            return None
        try:
            exp = self._client.get_experiment_by_name(EXPERIMENT_NAME)
            if exp is None:
                return self._client.create_experiment(EXPERIMENT_NAME)
            return exp.experiment_id
        except Exception as exc:  # noqa: BLE001
            logger.debug("ensure_experiment ناموفق: %s", exc)
            self._enabled = False
            return None

    def log_training_run(
        self,
        *,
        model_name: str,
        params: dict[str, Any],
        metrics: dict[str, float],
        model_artifact: Any | None = None,
        artifact_path: str = "model",
        tags: dict[str, str] | None = None,
    ) -> str | None:
        """ثبت یک اجرای آموزش و برگرداندن run_id (یا None در صورت شکست)."""
        experiment_id = self.ensure_experiment()
        if experiment_id is None:
            return None
        try:
            with mlflow.start_run(experiment_id=experiment_id, run_name=f"{model_name}_train") as run:
                mlflow.log_params({k: str(v) for k, v in params.items()})
                mlflow.log_metrics(metrics)
                if tags:
                    mlflow.set_tags(tags)
                if model_artifact is not None and hasattr(model_artifact, "save"):
                    with tempfile.TemporaryDirectory() as tmp:
                        path = os.path.join(tmp, "model.json")
                        model_artifact.save(path)
                        mlflow.log_artifact(path, artifact_path=artifact_path)
                elif model_artifact is not None:
                    try:
                        from mlflow import sklearn as mlflow_sklearn

                        mlflow_sklearn.log_model(model_artifact, artifact_path=artifact_path)
                    except Exception:  # noqa: BLE001
                        logger.debug("لاگ مدل sklearn ناموفق بود.")
                logger.info("MLflow run ثبت شد: %s (model=%s)", run.info.run_id, model_name)
                return run.info.run_id
        except Exception as exc:  # noqa: BLE001
            logger.debug("ثبت MLflow ناموفق بود (%s)؛ آموزش بدون Registry ادامه می‌یابد.", exc)
            self._enabled = False
            return None

    def register_and_transition(
        self,
        run_id: str,
        *,
        artifact_path: str = "model",
        stage: str = "Staging",
    ) -> str | None:
        if not self._enabled or self._client is None:
            return None
        model_uri = f"runs:/{run_id}/{artifact_path}"
        try:
            result = mlflow.register_model(model_uri, REGISTERED_MODEL_NAME)
            version = str(result.version)
        except Exception as exc:  # noqa: BLE001
            logger.warning("register_model استاندارد ناموفق بود (%s)؛ ثبت metadata انجام می‌شود.", exc)
            try:
                self._client.create_registered_model(REGISTERED_MODEL_NAME)
            except Exception:  # noqa: BLE001
                pass
            try:
                mv = self._client.create_model_version(
                    name=REGISTERED_MODEL_NAME,
                    source=model_uri,
                    run_id=run_id,
                )
                version = str(mv.version)
            except Exception:  # noqa: BLE001
                return None

        try:
            self._client.transition_model_version_stage(
                name=REGISTERED_MODEL_NAME,
                version=version,
                stage=stage,
                archive_existing_versions=(stage == "Production"),
            )
            logger.info("مدل %s نسخه %s به مرحله %s منتقل شد.", REGISTERED_MODEL_NAME, version, stage)
            return version
        except Exception:  # noqa: BLE001
            return version

    def promote_best_to_production(self, run_id: str, artifact_path: str = "model") -> str | None:
        version = self.register_and_transition(run_id, artifact_path=artifact_path, stage="Staging")
        if version is None or self._client is None:
            return None
        try:
            self._client.transition_model_version_stage(
                name=REGISTERED_MODEL_NAME,
                version=version,
                stage="Production",
                archive_existing_versions=True,
            )
        except Exception:  # noqa: BLE001
            pass
        return version

    def get_production_model_info(self) -> dict | None:
        if not self._enabled or self._client is None:
            return None
        try:
            versions = self._client.get_latest_versions(REGISTERED_MODEL_NAME, stages=["Production"])
            if not versions:
                return None
            mv = versions[0]
            return {
                "name": mv.name,
                "version": mv.version,
                "run_id": mv.run_id,
                "source": mv.source,
                "stage": mv.current_stage,
            }
        except Exception:  # noqa: BLE001
            return None
