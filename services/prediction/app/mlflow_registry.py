"""Experiment and Model Registry registration in MLflow (phase 3).

Flow:
  1. log_run → record parameters/metrics/artifact
  2. register_model → register in the Model Registry
  3. promote_model → move Staging → Production
  4. load_production_model_uri → the Production model URI for online serving
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
    """Prevent a long hang when the MLflow server is unavailable."""
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
            logger.warning("Initial connection to MLflow failed: %s", exc)
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
            logger.debug("ensure_experiment failed: %s", exc)
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
        """Record a training run and return run_id (or None on failure)."""
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
                        logger.debug("Logging the sklearn model failed.")
                logger.info("MLflow run recorded: %s (model=%s)", run.info.run_id, model_name)
                return run.info.run_id
        except Exception as exc:  # noqa: BLE001
            logger.debug("MLflow recording failed (%s); training continues without the Registry.", exc)
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
            logger.warning("Standard register_model failed (%s); metadata is recorded instead.", exc)
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
            logger.info("Model %s version %s moved to stage %s.", REGISTERED_MODEL_NAME, version, stage)
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
